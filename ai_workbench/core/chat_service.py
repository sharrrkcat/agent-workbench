"""Persona/session validation and deterministic chat configuration resolution."""

from sqlmodel import Session as DbSession, delete

from ai_workbench.core.attachments import attachment_filename_from_id, attachment_mime_type, resolve_attachment_uri
from ai_workbench.core.models.schema import GenerationParameters
from ai_workbench.core.schema.persona import USER_PERSONA_ID, PersonaInput, ResolvedChatConfig
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.session import Session
from ai_workbench.core.time import utc_now
from ai_workbench.db.models import SessionRecord, SessionKnowledgeBindingRecord


TERMINAL_RUNS = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}


class ChatError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

    def payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


class ChatService:
    def __init__(self, *, personas, sessions, runs, model_manager, knowledge, worldbooks, tool_registry=None):
        self.personas = personas
        self.sessions = sessions
        self.runs = runs
        self.model_manager = model_manager
        self.knowledge = knowledge
        self.worldbooks = worldbooks
        self.tool_registry = tool_registry

    def persona(self, persona_id: str):
        try:
            return self.personas.get(persona_id)
        except KeyError as exc:
            raise ChatError("PERSONA_NOT_FOUND", "Persona does not exist.", 404) from exc

    def validate_persona(self, values: PersonaInput) -> None:
        if values.avatar_attachment_id is not None:
            try:
                attachment_filename_from_id(values.avatar_attachment_id)
                path = resolve_attachment_uri(values.avatar_attachment_id)
                if not path.is_file() or not attachment_mime_type(values.avatar_attachment_id).startswith("image/"):
                    raise ValueError()
            except ValueError as exc:
                raise ChatError("PERSONA_AVATAR_INVALID", "Choose an existing image attachment.") from exc

    def validate_session(self, session: Session) -> None:
        self.agent_persona(session.persona_id)
        if session.model_profile_id is not None:
            self.model_manager.profile(session.model_profile_id, "llm")
        if self.tool_registry is not None:
            try:
                self.tool_registry.validate_allowlist(session.tools_allowed)
            except Exception as exc:
                raise ChatError("TOOL_NOT_FOUND", "Session references an unknown tool.") from exc

    def create_session(self, values: dict) -> Session:
        if values.get("model_profile_id") is None:
            profile = self.model_manager.default_chat_profile()
            values = {**values, "model_profile_id": profile.id if profile else None}
        if "tools_allowed" not in values:
            values = {**values, "tools_allowed": [tool.name for tool in self.tool_registry.list()] if self.tool_registry else []}
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
        persona = self.persona(persona_id)
        if persona.is_protected:
            raise ChatError("PERSONA_PROTECTED", "This persona can be edited but cannot be deleted.", 409)
        if any(s.persona_id == persona_id for s in self.sessions.list_sessions()):
            raise ChatError("PERSONA_IN_USE", "Select another persona in its sessions before deleting it.", 409)
        if any(r.persona_id == persona_id and r.status not in TERMINAL_RUNS for r in self.runs.list_all_runs()):
            raise ChatError("PERSONA_IN_USE", "This persona is used by an unfinished run.", 409)
        return self.personas.delete(persona_id)

    def agent_persona(self, persona_id: str):
        persona = self.persona(persona_id)
        if persona.collection != "agent":
            raise ChatError("PERSONA_COLLECTION_INVALID", "Ordinary sessions require an Agent Persona.", 422)
        return persona

    def persona_for_resource(self, persona_id: str, kind: str):
        persona = self.persona(persona_id)
        if persona.resource_kind != kind:
            raise ChatError("PERSONA_RESOURCE_FORBIDDEN", "This resource is not supported by the persona collection.", 422)
        return persona

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

    def session_knowledge_ids(self, session_id: str) -> list[str]:
        return [b.knowledge_base_id for b in self.knowledge.list_session_bindings(session_id) if b.enabled]

    def effective_knowledge_ids(self, session: Session, persona_id: str | None = None) -> list[str]:
        user_ids = self.personas.binding_ids(USER_PERSONA_ID, "knowledge")
        agent_ids = self.personas.binding_ids(persona_id or session.persona_id, "knowledge")
        return list(dict.fromkeys([*user_ids, *agent_ids, *self.session_knowledge_ids(session.session_id)]))

    def knowledge_response(self, session_id: str) -> dict:
        session = self.sessions.get_session(session_id)
        return {"session_id": session_id,
            "knowledge_base_ids": self.session_knowledge_ids(session_id),
            "user_persona_knowledge_base_ids": self.personas.binding_ids(USER_PERSONA_ID, "knowledge"),
            "agent_persona_knowledge_base_ids": self.personas.binding_ids(session.persona_id, "knowledge"),
            "effective_knowledge_base_ids": self.effective_knowledge_ids(session)}

    def update_knowledge(self, session_id: str, ids: list[str]) -> None:
        self.sessions.get_session(session_id)
        self.validate_bindings("knowledge", ids)
        engine = getattr(self.sessions, "engine", None)
        if engine is None:
            self.knowledge.replace_session_bindings(session_id, ids)
            self.sessions.touch_session(session_id)
            return
        with DbSession(engine) as db:
            session = db.get(SessionRecord, session_id)
            session.updated_at = utc_now()
            db.add(session)
            db.exec(delete(SessionKnowledgeBindingRecord).where(SessionKnowledgeBindingRecord.session_id == session_id))
            for index, resource_id in enumerate(ids):
                db.add(SessionKnowledgeBindingRecord(knowledge_base_id=resource_id, session_id=session_id, sort_order=index))
            db.commit()

    def resolve(self, session: Session, *, persona_id: str | None = None) -> ResolvedChatConfig:
        selected_id = persona_id or session.persona_id
        persona = self.agent_persona(selected_id)
        user_persona = self.persona(USER_PERSONA_ID)
        model_id = session.model_profile_id
        parameters = {}
        if model_id:
            try:
                parameters = self.model_manager.profiles.get(model_id).parameters
            except KeyError:
                pass  # Readable sessions remain editable when a referenced model is unavailable.
        generation = session.generation
        return ResolvedChatConfig(
            persona_id=persona.id, persona_name=persona.name, avatar_attachment_id=persona.avatar_attachment_id,
            system_prompt=persona.system_prompt, user_persona_id=user_persona.id, user_persona_prompt=user_persona.system_prompt,
            context_policy=session.context_policy,
            model_profile_id=model_id, model_source="session",
            generation=GenerationParameters.model_validate({**parameters, **generation.model_dump(exclude_none=True)}),
            harness_enabled=session.harness_enabled,
            tools_allowed=session.tools_allowed,
            knowledge_base_ids=self.effective_knowledge_ids(session, selected_id),
        )

    def session_response(self, session: Session) -> dict:
        payload = session.model_dump(mode="json")
        payload["user_persona"] = self.persona(USER_PERSONA_ID).identity().model_dump(mode="json")
        payload["effective"] = self.resolve(session).public_summary()
        return payload
