"""Persona/session validation and deterministic chat configuration resolution."""

from sqlmodel import Session as DbSession, delete

from ai_workbench.core.attachments import attachment_filename_from_id, attachment_mime_type, resolve_attachment_uri
from ai_workbench.core.models.schema import GenerationParameters
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.schema.persona import USER_PERSONA_ID, PersonaInput, ResolvedChatConfig
from ai_workbench.core.schema.project import WorkspaceProject
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.session import ChatSettings, OrdinarySession, Session, WorkspaceSession, parse_session
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
    def __init__(self, *, personas, projects, sessions, runs, model_manager, knowledge, worldbooks, tool_registry=None):
        self.personas = personas
        self.projects = projects
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

    def validate_tools(self, tools: list[str]) -> None:
        if self.tool_registry is not None:
            try:
                self.tool_registry.validate_allowlist(tools)
            except ToolExecutionError as exc:
                raise ChatError("TOOL_NOT_FOUND", "Session references an unknown tool.") from exc

    def workspace(self, project_id: str) -> WorkspaceProject:
        try:
            project = self.projects.get(project_id)
        except KeyError as exc:
            raise ChatError("PROJECT_NOT_FOUND", "Project does not exist.", 404) from exc
        if project.kind != "workspace":
            raise ChatError("PROJECT_CHAT_UNAVAILABLE", "Timeline conversations are not available yet.", 409)
        return project

    def settings(self, session: Session) -> ChatSettings:
        if session.kind == "ordinary":
            return ChatSettings.model_validate(session.model_dump(include=set(ChatSettings.model_fields)))
        project = self.workspace(session.project_id)
        overrides = session.overrides.model_dump(exclude_none=True)
        temperature = overrides.pop("temperature", project.temperature)
        values = dict(model_profile_id=project.model_profile_id, persona_id=project.agent_persona_id,
                      context_policy=project.context_policy, generation={"temperature": temperature},
                      harness_enabled=project.harness_enabled, tools_allowed=project.tools_allowed)
        values.update(overrides)
        if values["model_profile_id"] is None:
            profile = self.model_manager.default_chat_profile()
            values["model_profile_id"] = profile.id if profile else None
        values["tools_allowed"] = [name for name in values["tools_allowed"] if name in project.tools_allowed]
        return ChatSettings.model_validate(values)

    def selected_agent_id(self, session: Session) -> str:
        return session.persona_id if session.kind == "ordinary" else (
            session.overrides.persona_id or self.workspace(session.project_id).agent_persona_id)

    def saved_model_id(self, session: Session) -> str | None:
        return session.model_profile_id if session.kind == "ordinary" else session.overrides.model_profile_id

    def validate_session(self, session: Session) -> None:
        settings = self.settings(session)
        self.agent_persona(settings.persona_id)
        if settings.model_profile_id is not None:
            self.model_manager.profile(settings.model_profile_id, "llm")
        self.validate_tools(settings.tools_allowed)

    def validate_overrides(self, project_id: str, values: dict) -> None:
        project = self.workspace(project_id)
        if values.get("tools_allowed") is not None:
            self.validate_tools(values["tools_allowed"])
            if set(values["tools_allowed"]) - set(project.tools_allowed):
                raise ChatError("TOOL_NOT_ALLOWED", "The Project has disabled one or more selected tools.", 422)

    def create_session(self, values: dict) -> Session:
        if values.get("model_profile_id") is None:
            profile = self.model_manager.default_chat_profile()
            values = {**values, "model_profile_id": profile.id if profile else None}
        if "tools_allowed" not in values:
            values = {**values, "tools_allowed": [tool.name for tool in self.tool_registry.list()] if self.tool_registry else []}
        candidate = OrdinarySession(session_id="new", **values)
        self.validate_session(candidate)
        return self.sessions.create_session(**values)

    def create_workspace_session(self, project_id: str, values: dict) -> Session:
        self.validate_overrides(project_id, values.get("overrides", {}))
        candidate = WorkspaceSession(session_id="new", project_id=project_id, **values)
        self.validate_session(candidate)
        return self.sessions.create_session(kind="workspace", project_id=project_id, **values)

    def update_session(self, session_id: str, values: dict) -> Session:
        current = self.sessions.get_session(session_id)
        if current.kind == "workspace" and "overrides" in values:
            self.validate_overrides(current.project_id, values["overrides"])
            values = {**values, "overrides": {**current.overrides.model_dump(exclude_none=True), **values["overrides"]}}
        candidate = parse_session({**current.model_dump(), **values})
        self.validate_session(candidate)
        return self.sessions.update_session(session_id, values)

    def assert_idle(self, session_id: str) -> None:
        if any(r.status not in TERMINAL_RUNS for r in self.runs.list_runs(session_id)):
            raise ChatError("SESSION_BUSY", "Cancel the active run before changing conversation history.", 409)

    def delete_persona(self, persona_id: str):
        persona = self.persona(persona_id)
        if persona.is_protected:
            raise ChatError("PERSONA_PROTECTED", "This persona can be edited but cannot be deleted.", 409)
        if self.projects.references_persona(persona_id) or any(self.selected_agent_id(s) == persona_id for s in self.sessions.list_sessions()):
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
        agent_ids = self.personas.binding_ids(persona_id or self.selected_agent_id(session), "knowledge")
        project_ids = self.workspace(session.project_id).knowledge_base_ids if session.kind == "workspace" else []
        return list(dict.fromkeys([*user_ids, *agent_ids, *project_ids, *self.session_knowledge_ids(session.session_id)]))

    def knowledge_response(self, session_id: str) -> dict:
        session = self.sessions.get_session(session_id)
        return {"session_id": session_id,
            "knowledge_base_ids": self.session_knowledge_ids(session_id),
            "user_persona_knowledge_base_ids": self.personas.binding_ids(USER_PERSONA_ID, "knowledge"),
            "agent_persona_knowledge_base_ids": self.personas.binding_ids(self.selected_agent_id(session), "knowledge"),
            "project_knowledge_base_ids": self.workspace(session.project_id).knowledge_base_ids if session.kind == "workspace" else [],
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
        settings = self.settings(session)
        selected_id = persona_id or settings.persona_id
        persona = self.agent_persona(selected_id)
        user_persona = self.persona(USER_PERSONA_ID)
        model_id = settings.model_profile_id
        sources = dict(persona="session", context="session", harness="session", tools="session",
                       temperature="session" if settings.generation.temperature is not None else "model")
        model_source = "session"
        project_prompt = ""
        if session.kind == "workspace":
            project = self.workspace(session.project_id)
            project_prompt = project.system_prompt
            overridden = session.overrides.model_dump(exclude_none=True)
            for source, key in (("persona", "persona_id"), ("context", "context_policy"), ("harness", "harness_enabled"), ("tools", "tools_allowed")):
                sources[source] = "session" if key in overridden else "project"
            sources["temperature"] = "session" if "temperature" in overridden else "project" if project.temperature is not None else "model"
            model_source = "session" if session.overrides.model_profile_id is not None else "project" if project.model_profile_id is not None else "global"
        parameters = {}
        if model_id:
            try:
                parameters = self.model_manager.profiles.get(model_id).parameters
            except KeyError:
                pass  # Readable sessions remain editable when a referenced model is unavailable.
        generation = settings.generation
        return ResolvedChatConfig(
            session_kind=session.kind, project_id=session.project_id, project_system_prompt=project_prompt, sources=sources,
            persona_id=persona.id, persona_name=persona.name, avatar_attachment_id=persona.avatar_attachment_id,
            system_prompt=persona.system_prompt, user_persona_id=user_persona.id, user_persona_prompt=user_persona.system_prompt,
            context_policy=settings.context_policy,
            model_profile_id=model_id, model_source=model_source,
            generation=GenerationParameters.model_validate({**parameters, **generation.model_dump(exclude_none=True)}),
            harness_enabled=settings.harness_enabled,
            tools_allowed=settings.tools_allowed,
            knowledge_base_ids=self.effective_knowledge_ids(session, selected_id),
        )

    def tools_for_run(self, config: ResolvedChatConfig) -> list[str]:
        if config.project_id is None:
            return config.tools_allowed
        allowed = self.workspace(config.project_id).tools_allowed
        return [name for name in config.tools_allowed if name in allowed]

    def session_response(self, session: Session) -> dict:
        payload = session.model_dump(mode="json")
        payload["user_persona"] = self.persona(USER_PERSONA_ID).identity().model_dump(mode="json")
        payload["effective"] = self.resolve(session).public_summary()
        return payload
