"""Identity validation and two-level Character/Session configuration resolution."""

from ai_workbench.core.attachments import attachment_filename_from_id, attachment_mime_type, resolve_attachment_uri
from ai_workbench.core.models.schema import GenerationParameters
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.schema.chat_config import ChatDefaults, ResolvedChatConfig
from ai_workbench.core.schema.character import NormalCharacter
from ai_workbench.core.schema.qq import QQ_TOOLS
from ai_workbench.core.web_tools import WEB_TOOL_NAMES
from ai_workbench.core.session import NormalSession, Session, parse_session


class ChatError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

    def payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


class ChatService:
    def __init__(self, *, personas, characters, sessions, runs, model_manager, knowledge, worldbooks, tool_registry=None):
        self.personas, self.characters = personas, characters
        self.sessions, self.runs = sessions, runs
        self.model_manager = model_manager
        self.knowledge, self.worldbooks = knowledge, worldbooks
        self.tool_registry = tool_registry

    def persona(self, persona_id: str):
        try:
            return self.personas.get(persona_id)
        except KeyError as exc:
            raise ChatError("PERSONA_NOT_FOUND", "Persona does not exist.", 404) from exc

    def character(self, character_id: str):
        try:
            return self.characters.get(character_id)
        except KeyError as exc:
            raise ChatError("CHARACTER_NOT_FOUND", "Character does not exist.", 404) from exc

    def normal_character(self, character_id: str) -> NormalCharacter:
        character = self.character(character_id)
        if character.kind != "normal":
            raise ChatError("CHARACTER_KIND_INVALID", "Choose a normal Character for this conversation.", 422)
        return character

    def validate_avatar(self, attachment_id: str | None) -> None:
        if attachment_id is None:
            return
        try:
            attachment_filename_from_id(attachment_id)
            path = resolve_attachment_uri(attachment_id)
            if not path.is_file() or not attachment_mime_type(attachment_id).startswith("image/"):
                raise ValueError()
        except ValueError as exc:
            raise ChatError("AVATAR_INVALID", "Choose an existing image attachment.") from exc

    def validate_tools(self, tools: list[str]) -> None:
        if set(tools).intersection(QQ_TOOLS):
            raise ChatError("TOOL_NOT_ALLOWED", "QQ tools are available only to QQBot sessions.", 422)
        if self.tool_registry is not None:
            try:
                self.tool_registry.validate_allowlist(tools)
            except ToolExecutionError as exc:
                raise ChatError(exc.code, exc.message, 422) from exc

    def validate_bindings(self, kind: str, ids: list[str]) -> None:
        store = self.knowledge if kind == "knowledge" else self.worldbooks
        get = store.get_knowledge_base if kind == "knowledge" else store.get_worldbook
        for value in ids:
            try:
                get(value)
            except KeyError as exc:
                raise ChatError("BINDING_NOT_FOUND", "A selected resource does not exist.", 404) from exc

    def validate_settings(self, settings: ChatDefaults) -> None:
        self.persona(settings.persona_id)
        if settings.model_profile_id is not None:
            self.model_manager.profile(settings.model_profile_id, "llm")
        self.validate_tools(settings.tools_allowed)
        self.validate_bindings("knowledge", settings.knowledge_base_ids)
        self.validate_bindings("worldbook", settings.worldbook_ids)

    def settings(self, session: NormalSession) -> ChatDefaults:
        character = self.normal_character(session.character_id)
        return ChatDefaults.model_validate({
            **character.model_dump(include=set(ChatDefaults.model_fields)),
            **session.overrides.model_dump(exclude_none=True),
        })

    def saved_model_id(self, session: Session) -> str | None:
        return session.overrides.model_profile_id if session.kind == "normal" else None

    def selected_persona_id(self, session: Session) -> str | None:
        return self.settings(session).persona_id if session.kind == "normal" else None

    def create_session(self, character_id: str, values: dict) -> Session:
        candidate = NormalSession(session_id="new", character_id=character_id, **values)
        self.validate_settings(self.settings(candidate))
        return self.sessions.create_session(kind="normal", character_id=character_id, **values)

    def update_session(self, session_id: str, values: dict) -> Session:
        current = self.sessions.get_session(session_id)
        if current.kind == "normal" and "overrides" in values:
            values = {**values, "overrides": {**current.overrides.model_dump(exclude_none=True), **values["overrides"]}}
        candidate = parse_session({**current.model_dump(), **values})
        if candidate.kind == "normal":
            self.validate_settings(self.settings(candidate))
        return self.sessions.update_session(session_id, values)

    def assert_idle(self, session_id: str) -> None:
        if self.runs.has_unfinished(session_id=session_id):
            raise ChatError("SESSION_BUSY", "Cancel the active run before changing conversation history.", 409)

    def delete_persona(self, persona_id: str):
        persona = self.persona(persona_id)
        if persona.is_protected:
            raise ChatError("PERSONA_PROTECTED", "This Persona can be edited but cannot be deleted.", 409)
        if self.characters.references_persona(persona_id) or any(
                s.kind == "normal" and s.overrides.persona_id == persona_id for s in self.sessions.list_sessions()):
            raise ChatError("PERSONA_IN_USE", "Select another Persona in its Characters and Sessions first.", 409)
        if self.runs.has_unfinished(persona_id=persona_id):
            raise ChatError("PERSONA_IN_USE", "This Persona is used by an unfinished run.", 409)
        return self.personas.delete(persona_id)

    def effective_knowledge_ids(self, session: Session) -> list[str]:
        return self.settings(session).knowledge_base_ids if session.kind == "normal" else []

    def references_resource(self, kind: str, resource_id: str) -> bool:
        field = "knowledge_base_ids" if kind == "knowledge" else "worldbook_ids"
        return self.characters.references_resource(kind, resource_id) or any(
            s.kind == "normal" and resource_id in (getattr(s.overrides, field) or [])
            for s in self.sessions.list_sessions())

    def _model_configuration(self, model_id, temperature):
        from ai_workbench.core.models.context_budget import configured_limits
        from ai_workbench.core.schema.context_budget import ContextLimits
        parameters, limits = {}, ContextLimits()
        if model_id:
            try:
                profile = self.model_manager.profiles.get(model_id)
                parameters, limits = profile.parameters, configured_limits(profile)
            except KeyError:
                pass  # A missing model remains visible without substituting another selection.
        if temperature is not None:
            parameters = {**parameters, "temperature": temperature}
        return GenerationParameters.model_validate(parameters), limits

    def resolve(self, session: Session, *, persona_id: str | None = None) -> ResolvedChatConfig:
        if session.kind == "qqbot":
            return self.resolve_qq(session)
        character = self.normal_character(session.character_id)
        settings = self.settings(session)
        persona = self.persona(persona_id if persona_id is not None else settings.persona_id)
        overridden = session.overrides.model_dump(exclude_none=True)
        sources = {source: "session" if key in overridden else "character" for source, key in (
            ("persona", "persona_id"), ("context", "context_policy"), ("reasoning", "reasoning"),
            ("harness", "harness_enabled"), ("tools", "tools_allowed"),
            ("knowledge", "knowledge_base_ids"), ("worldbook", "worldbook_ids"))}
        sources["temperature"] = "session" if "temperature" in overridden else "character" if character.temperature is not None else "model"
        generation, limits = self._model_configuration(settings.model_profile_id, settings.temperature)
        return ResolvedChatConfig(
            session_kind="normal", character_id=character.id, character_name=character.name,
            character_avatar_attachment_id=character.avatar_attachment_id, system_prompt=character.system_prompt,
            persona_id=persona.id, persona_name=persona.name, persona_background=persona.background,
            sources=sources, context_policy=settings.context_policy, context_limits=limits,
            model_profile_id=settings.model_profile_id,
            model_source="session" if "model_profile_id" in overridden else "character",
            generation=generation, reasoning=settings.reasoning, harness_enabled=settings.harness_enabled,
            tools_allowed=settings.tools_allowed, knowledge_base_ids=settings.knowledge_base_ids,
            worldbook_ids=settings.worldbook_ids,
        )

    def tools_for_run(self, config: ResolvedChatConfig) -> list[str]:
        from ai_workbench.core.schema.retrieval import CONTEXT_TOOL_NAMES
        allowed = list(config.tools_allowed)
        if config.session_kind == "qqbot":
            allowed = [name for name in allowed
                if (name != "qq_skip_reply" or config.qq_target_kind == "group")
                and (name != "qq_send_image" or config.qq_image_candidates)
                and (name != "qq_generate_image" or config.qq_image_generation_allowed)]
        if config.context_policy.strategy == "history_retrieval" and config.harness_enabled:
            allowed.extend(sorted(CONTEXT_TOOL_NAMES))
        return allowed

    def session_response(self, session: Session) -> dict:
        config = self.resolve(session)
        return {**session.model_dump(mode="json"),
            "persona": self.persona(config.persona_id).identity().model_dump(mode="json") if config.persona_id else None,
            "effective": config.public_summary()}

    def resolve_qq(self, session) -> ResolvedChatConfig:
        character = self.character(session.character_id)
        generation, limits = self._model_configuration(character.model_profile_id, character.temperature)
        return ResolvedChatConfig(
            session_kind="qqbot", character_id=character.id, character_name=character.name,
            character_avatar_attachment_id=character.avatar_attachment_id, system_prompt=character.system_prompt,
            persona_id=None, persona_name=None,
            sources=dict(persona="character", context="character", reasoning="character", harness="character",
                tools="character", knowledge="character", worldbook="character",
                temperature="character" if character.temperature is not None else "model"),
            context_policy=character.context_policy.model_copy(update={
                "include_attachments": "explicit" if character.image_input_enabled else "none"}),
            context_limits=limits, model_profile_id=character.model_profile_id, model_source="character",
            generation=generation, reasoning=character.reasoning, harness_enabled=True,
            tools_allowed=[name for name in (*QQ_TOOLS, *sorted(WEB_TOOL_NAMES))
                if (name != "qq_skip_reply" or session.target_kind == "group")
                and name != "qq_send_image"
                and (name != "qq_generate_image" or character.image_generation_model_profile_id is not None)],
            knowledge_base_ids=[], worldbook_ids=[], qq_reply_message_limit=character.reply_message_limit,
            qq_bot_account=character.bot_account, qq_target_kind=session.target_kind, qq_target_id=session.target_id,
            qq_image_description_model_profile_id=character.image_description_model_profile_id,
            qq_image_generation_model_profile_id=character.image_generation_model_profile_id,
            qq_image_generation_options=character.image_generation_options,
        )
