"""Character creation, reference validation and immutable ownership."""

from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.schema.character import Character, CharacterCreate, NormalCharacterInput, COGITA_CHARACTER_ID, character_adapter
from ai_workbench.core.schema.chat_config import ChatDefaults
from ai_workbench.core.time import utc_now


class CharacterService:
    def __init__(self, *, characters, chat_service):
        self.characters = characters
        self.chat = chat_service

    def get(self, character_id: str) -> Character:
        return self.chat.character(character_id)

    def ensure_default(self) -> None:
        try:
            self.characters.get(COGITA_CHARACTER_ID)
        except KeyError:
            self.create(NormalCharacterInput(kind="normal", name="Cogita"), character_id=COGITA_CHARACTER_ID)

    def validate(self, character: Character) -> None:
        self.chat.validate_avatar(character.avatar_attachment_id)
        if character.kind == "normal":
            self.chat.validate_settings(ChatDefaults.model_validate(
                character.model_dump(include=set(ChatDefaults.model_fields))))
            return
        if character.admin_qq == character.bot_account:
            raise ChatError("QQ_ADMIN_IS_BOT", "The administrator must be a different QQ account.", 422)
        if character.image_generation_model_profile_id is not None:
            self.chat.model_manager.profile(character.image_generation_model_profile_id, "image_generation")
        for model_id in (character.model_profile_id, character.image_description_model_profile_id):
            if model_id:
                profile = self.chat.model_manager.profile(model_id, "llm")
                if not profile.source or profile.source.type != "provider":
                    raise ChatError("QQ_EXTERNAL_MODEL_REQUIRED", "Choose an external LLM profile.", 422)
        if character.connection_enabled and not character.model_profile_id:
            raise ChatError("MODEL_NOT_CONFIGURED", "Choose an external LLM before connecting.", 422)
        if any(p.kind == "qqbot" and p.id != character.id and p.bot_account == character.bot_account for p in self.characters.list()):
            raise ChatError("QQ_ACCOUNT_IN_USE", "This bot account already has a Character.", 409)

    def create(self, values: CharacterCreate, *, character_id: str | None = None) -> Character:
        data = values.model_dump()
        if values.kind == "normal":
            if "model_profile_id" not in values.model_fields_set:
                profile = self.chat.model_manager.default_chat_profile()
                data["model_profile_id"] = profile.id if profile else None
            if "tools_allowed" not in values.model_fields_set:
                data["tools_allowed"] = [tool.name for tool in self.chat.tool_registry.list()
                    if tool.scope == "general"] if self.chat.tool_registry else []
        if character_id is not None:
            data["id"] = character_id
        character = character_adapter.validate_python(data)
        self.validate(character)
        return self.characters.save(character)

    def update(self, character_id: str, values: dict) -> Character:
        with self.chat.mutation_lock:
            return self._update(character_id, values)

    def _update(self, character_id: str, values: dict) -> Character:
        current = self.get(character_id)
        memory_changed = current.kind == "normal" and any(
            key in values and values[key] != getattr(current, key)
            for key in ("memory_external_isolation", "memory_enabled"))
        if memory_changed and self.chat.memory:
            self.chat.memory.assert_character_idle(character_id)
        if current.kind == "qqbot" and values.get("bot_account", current.bot_account) != current.bot_account and any(
                session.character_id == character_id for session in self.chat.sessions.list_sessions()):
            raise ChatError("QQ_ACCOUNT_BOUND", "Delete the bound Sessions before changing the bot account.", 409)
        if {"id", "kind", "created_at", "updated_at"}.intersection(values):
            raise ChatError("CHARACTER_IDENTITY_IMMUTABLE", "Character identity and type cannot be changed.", 422)
        if current.kind == "qqbot" and isinstance(values.get("image_generation_options"), dict):
            values = {**values, "image_generation_options": {
                **current.image_generation_options.model_dump(), **values["image_generation_options"]}}
        candidate = character_adapter.validate_python({**current.model_dump(), **values, "updated_at": utc_now()})
        self.validate(candidate)
        saved = self.characters.save(candidate)
        if memory_changed and self.chat.memory:
            self.chat.memory.policy_changed(character_id)
        return saved

    def sessions(self, character_id: str):
        self.get(character_id)
        return [session for session in self.chat.sessions.list_sessions() if session.character_id == character_id]

    def assert_deletable(self, character_id: str) -> None:
        character = self.get(character_id)
        if character.is_protected:
            raise ChatError("CHARACTER_PROTECTED", "This Character can be edited but cannot be deleted.", 409)
        for session in self.sessions(character_id):
            self.chat.assert_idle(session.session_id)
