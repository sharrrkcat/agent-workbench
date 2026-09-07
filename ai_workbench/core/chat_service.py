"""Persona/session validation and deterministic chat configuration resolution."""

from uuid import uuid4
from sqlmodel import Session as DbSession, delete

from ai_workbench.core.attachments import attachment_filename_from_id, attachment_mime_type, resolve_attachment_uri
from ai_workbench.core.models.schema import GenerationParameters
from ai_workbench.core.schema.persona import CHAT_PERSONA_ID, PersonaInput, ResolvedChatConfig
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.session import Session
from ai_workbench.core.settings import DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION
from ai_workbench.core.time import utc_now
from ai_workbench.db.models import SessionRecord, SessionKnowledgeBindingRecord, SessionWorldbookBindingRecord


TERMINAL_RUNS = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}


class ChatError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

    def payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


class ChatService:
    def __init__(self, *, personas, sessions, runs, model_manager, app_settings, knowledge, worldbooks, tool_registry=None):
        self.personas = personas
        self.sessions = sessions
        self.runs = runs
        self.model_manager = model_manager
        self.app_settings = app_settings
        self.knowledge = knowledge
        self.worldbooks = worldbooks
        self.tool_registry = tool_registry

    def persona(self, persona_id: str):
        try:
            return self.personas.get(persona_id)
        except KeyError as exc:
            raise ChatError("PERSONA_NOT_FOUND", "Persona does not exist.", 404) from exc

    def validate_persona(self, values: PersonaInput) -> None:
        if self.tool_registry is not None:
            try:
                self.tool_registry.validate_allowlist(values.tools_allowed)
            except Exception as exc:
                raise ChatError("TOOL_NOT_FOUND", "Persona references an unknown tool.") from exc
        if values.model_profile_id is not None:
            self.model_manager.profile(values.model_profile_id, "llm")
        if values.avatar_attachment_id is not None:
            try:
                attachment_filename_from_id(values.avatar_attachment_id)
                path = resolve_attachment_uri(values.avatar_attachment_id)
                if not path.is_file() or not attachment_mime_type(values.avatar_attachment_id).startswith("image/"):
                    raise ValueError()
            except ValueError as exc:
                raise ChatError("PERSONA_AVATAR_INVALID", "Choose an existing image attachment.") from exc

    def validate_session(self, session: Session) -> None:
        for member in session.personas:
            self.persona(member.persona_id)
        if session.model_profile_id is not None:
            self.model_manager.profile(session.model_profile_id, "llm")
        if self.tool_registry is not None and session.tools_allowed is not None:
            try:
                self.tool_registry.validate_allowlist(session.tools_allowed)
            except Exception as exc:
                raise ChatError("TOOL_NOT_FOUND", "Session references an unknown tool.") from exc

    def create_session(self, values: dict) -> Session:
        candidate = Session(session_id="new", **values)
        self.validate_session(candidate)
        return self.sessions.create_session(**values)

    def update_session(self, session_id: str, values: dict) -> Session:
        current = self.sessions.get_session(session_id)
        candidate = Session.model_validate({**current.model_dump(), **values})
        self.validate_session(candidate)
        return self.sessions.update_session(session_id, values)

    def assert_idle(self, session_id: str) -> None:
        if any(r.status not in TERMINAL_RUNS for r in self.runs.list_runs(session_id)):
            raise ChatError("SESSION_BUSY", "Cancel the active run before changing conversation history.", 409)

    def delete_persona(self, persona_id: str):
        self.persona(persona_id)
        if persona_id == CHAT_PERSONA_ID:
            raise ChatError("PERSONA_DEFAULT", "The default Chat persona can be edited but cannot be deleted.", 409)
        if any(any(m.persona_id == persona_id for m in s.personas) for s in self.sessions.list_sessions()):
            raise ChatError("PERSONA_IN_USE", "Remove this persona from sessions before deleting it.", 409)
        if any(r.persona_id == persona_id and r.status not in TERMINAL_RUNS for r in self.runs.list_all_runs()):
            raise ChatError("PERSONA_IN_USE", "This persona is used by an unfinished run.", 409)
        return self.personas.delete(persona_id)

    def validate_bindings(self, kind: str, ids: list[str]) -> None:
        if len(ids) != len(set(ids)):
            raise ChatError("BINDING_DUPLICATE", "Context bindings must be unique.")
        store = self.knowledge if kind == "knowledge" else self.worldbooks
        get = store.get_knowledge_base if kind == "knowledge" else store.get_worldbook
        for value in ids:
            try:
                get(value)
            except KeyError as exc:
                raise ChatError("BINDING_NOT_FOUND", "A selected context resource does not exist.", 404) from exc

    def effective_binding_ids(self, session: Session, kind: str, persona_id: str | None = None) -> list[str]:
        if getattr(session, kind + "_binding_mode") == "inherit":
            return self.personas.binding_ids(persona_id or session.current_persona_id, kind)
        store = self.knowledge if kind == "knowledge" else self.worldbooks
        field = "knowledge_base_id" if kind == "knowledge" else "worldbook_id"
        return [getattr(b, field) for b in store.list_session_bindings(session.session_id) if b.enabled]

    def binding_response(self, session_id: str, kind: str) -> dict:
        session = self.sessions.get_session(session_id)
        store = self.knowledge if kind == "knowledge" else self.worldbooks
        field = "knowledge_base_id" if kind == "knowledge" else "worldbook_id"
        return {"session_id": session_id, "mode": getattr(session, kind + "_binding_mode"),
            field + "s": [getattr(b, field) for b in store.list_session_bindings(session_id) if b.enabled],
            "effective_" + field + "s": self.effective_binding_ids(session, kind)}

    def update_bindings(self, session_id: str, kind: str, mode: str, ids: list[str] | None) -> None:
        self.sessions.get_session(session_id)
        if ids is not None:
            self.validate_bindings(kind, ids)
        store = self.knowledge if kind == "knowledge" else self.worldbooks
        engine = getattr(self.sessions, "engine", None)
        if engine is None:
            if ids is not None:
                store.replace_session_bindings(session_id, ids)
            self.sessions.update_session(session_id, {kind + "_binding_mode": mode})
            return
        record = SessionKnowledgeBindingRecord if kind == "knowledge" else SessionWorldbookBindingRecord
        key = "knowledge_base_id" if kind == "knowledge" else "worldbook_id"
        with DbSession(engine) as db:
            session = db.get(SessionRecord, session_id)
            setattr(session, kind + "_binding_mode", mode)
            session.updated_at = utc_now()
            db.add(session)
            if ids is not None:
                db.exec(delete(record).where(record.session_id == session_id))
                for index, resource_id in enumerate(ids):
                    values = {key: resource_id, "session_id": session_id, "sort_order": index}
                    if kind == "worldbook":
                        values["id"] = str(uuid4())
                    db.add(record(**values))
            db.commit()

    def resolve(self, session: Session, *, persona_id: str | None = None) -> ResolvedChatConfig:
        selected_id = persona_id or session.current_persona_id
        if not any(m.enabled and m.persona_id == selected_id for m in session.personas):
            raise ChatError("PERSONA_NOT_MEMBER", "Select an enabled session persona.", 409)
        persona = self.persona(selected_id)
        model_id = session.model_profile_id or persona.model_profile_id or self.model_manager.settings.get().default_model_profile_id
        model_source = "session" if session.model_profile_id else "persona" if persona.model_profile_id else "global"
        parameters = {}
        if model_id:
            try:
                parameters = self.model_manager.profiles.get(model_id).parameters
            except KeyError:
                pass  # Readable sessions remain editable when a referenced model is unavailable.
        generation = session.generation if session.generation is not None else persona.generation
        settings = self.app_settings.get()
        return ResolvedChatConfig(
            persona_id=persona.id, persona_name=persona.name, avatar_attachment_id=persona.avatar_attachment_id,
            system_prompt=persona.system_prompt, context_mode=session.context_mode,
            group_transcript_instruction=settings.group_transcript_system_instruction or DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION,
            context_policy=session.context_policy or persona.context_policy,
            model_profile_id=model_id, model_source=model_source,
            generation=GenerationParameters.model_validate({**parameters, **generation.model_dump(exclude_none=True)}),
            harness_enabled=persona.harness_enabled if session.harness_enabled is None else session.harness_enabled,
            tools_allowed=persona.tools_allowed if session.tools_allowed is None else session.tools_allowed,
            knowledge_base_ids=self.effective_binding_ids(session, "knowledge", selected_id),
            worldbook_ids=self.effective_binding_ids(session, "worldbook", selected_id),
        )

    def session_response(self, session: Session) -> dict:
        payload = session.model_dump(mode="json")
        members = []
        for member in session.personas:
            persona = self.persona(member.persona_id)
            members.append({**member.model_dump(), "name": persona.name, "avatar_attachment_id": persona.avatar_attachment_id})
        payload["personas"] = members
        payload["effective"] = self.resolve(session).public_summary()
        return payload
