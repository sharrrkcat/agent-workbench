"""Project validation and creation; conversation resolution belongs to ChatService."""

from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.schema.project import Project, ProjectCreate, project_adapter
from ai_workbench.core.time import utc_now


class ProjectService:
    def __init__(self, *, projects, chat_service):
        self.projects = projects
        self.chat = chat_service

    def get(self, project_id: str) -> Project:
        try:
            return self.projects.get(project_id)
        except KeyError as exc:
            raise ChatError("PROJECT_NOT_FOUND", "Project does not exist.", 404) from exc

    def validate(self, project: Project) -> None:
        if project.model_profile_id is not None:
            self.chat.model_manager.profile(project.model_profile_id, "llm")
        if project.kind == "workspace":
            self.chat.agent_persona(project.agent_persona_id)
            self.chat.persona(project.cogita_persona_id)
            self.chat.validate_tools(project.tools_allowed)
            self.chat.validate_bindings("knowledge", project.knowledge_base_ids)
        elif project.kind == "qqbot":
            if project.agent_persona_id:
                self.chat.agent_persona(project.agent_persona_id)
            if project.image_description_model_profile_id is not None:
                description_profile = self.chat.model_manager.profile(project.image_description_model_profile_id, "llm")
                if not description_profile.source or description_profile.source.type != "provider":
                    raise ChatError("QQ_EXTERNAL_MODEL_REQUIRED", "Choose an external LLM profile.", 422)
            if project.model_profile_id:
                profile = self.chat.model_manager.profile(project.model_profile_id, "llm")
                if not profile.source or profile.source.type != "provider":
                    raise ChatError("QQ_EXTERNAL_MODEL_REQUIRED", "Choose an external LLM profile.", 422)
            elif project.connection_enabled:
                raise ChatError("MODEL_NOT_CONFIGURED", "Choose an external LLM before connecting.", 422)
            if any(p.kind == "qqbot" and p.id != project.id and p.bot_account == project.bot_account for p in self.projects.list()):
                raise ChatError("QQ_ACCOUNT_IN_USE", "This bot account already has a Project.", 409)
        else:
            for persona_id, collection in ((project.character_persona_id, "character"), (project.user_persona_id, "roleplay_user")):
                if self.chat.persona(persona_id).collection != collection:
                    raise ChatError("PERSONA_COLLECTION_INVALID", "Choose the required Timeline persona collection.", 422)
            self.chat.validate_bindings("worldbook", project.worldbook_ids)

    def create(self, values: ProjectCreate) -> Project:
        project = project_adapter.validate_python(values.model_dump())
        self.validate(project)
        return self.projects.save(project)

    def update(self, project_id: str, values: dict) -> Project:
        current = self.get(project_id)
        if current.kind == "qqbot" and values.get("bot_account", current.bot_account) != current.bot_account and any(
                session.project_id == project_id for session in self.chat.sessions.list_sessions()):
            raise ChatError("QQ_ACCOUNT_BOUND", "Delete the bound Sessions before changing the bot account.", 409)
        if {"id", "kind", "created_at", "updated_at"}.intersection(values):
            raise ChatError("PROJECT_IDENTITY_IMMUTABLE", "Project identity and type cannot be changed.", 422)
        candidate = project_adapter.validate_python({**current.model_dump(), **values, "updated_at": utc_now()})
        self.validate(candidate)
        return self.projects.save(candidate)

    def for_resource(self, project_id: str, kind: str) -> Project:
        project = self.get(project_id)
        if project.kind == "qqbot" or (project.kind == "workspace") != (kind == "knowledge"):
            raise ChatError("PROJECT_RESOURCE_FORBIDDEN", "This resource is not supported by the Project type.", 422)
        return project

    def sessions(self, project_id: str):
        if self.get(project_id).kind != "qqbot":
            self.chat.workspace(project_id)
        return [session for session in self.chat.sessions.list_sessions() if session.project_id == project_id]

    def assert_idle(self, project_id: str) -> None:
        self.get(project_id)
        for session in self.chat.sessions.list_sessions():
            if session.project_id == project_id:
                self.chat.assert_idle(session.session_id)
