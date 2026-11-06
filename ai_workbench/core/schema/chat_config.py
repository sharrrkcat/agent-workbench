"""Character defaults, sparse Session overrides and immutable run configuration."""

from typing import Literal

from pydantic import Field, StrictBool, field_validator

from ai_workbench.core.models.schema import GenerationParameters, ImageGenerationControls, StrictModel
from ai_workbench.core.schema.context_budget import ContextLimits
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.persona import USER_PERSONA_ID
from ai_workbench.core.schema.qq import QQImageCandidate


def unique_list(value: list[str] | None) -> list[str] | None:
    if value is not None and len(value) != len(set(value)):
        raise ValueError("Values must be unique")
    return value


class ChatDefaults(StrictModel):
    persona_id: str = USER_PERSONA_ID
    model_profile_id: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    reasoning: StrictBool = True
    context_policy: ContextPolicy = Field(default_factory=ContextPolicy)
    harness_enabled: StrictBool = False
    memory_enabled: StrictBool = True
    memory_learning: Literal["manual", "automatic"] = "manual"
    tools_allowed: list[str] = Field(default_factory=list, max_length=128)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=128)
    worldbook_ids: list[str] = Field(default_factory=list, max_length=128)

    _unique_lists = field_validator("tools_allowed", "knowledge_base_ids", "worldbook_ids")(unique_list)


class SessionOverrides(StrictModel):
    """Null restores inheritance; false, zero and empty lists are explicit overrides."""

    persona_id: str | None = None
    model_profile_id: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    reasoning: StrictBool | None = None
    context_policy: ContextPolicy | None = None
    harness_enabled: StrictBool | None = None
    memory_enabled: StrictBool | None = None
    memory_learning: Literal["manual", "automatic"] | None = None
    tools_allowed: list[str] | None = Field(default=None, max_length=128)
    knowledge_base_ids: list[str] | None = Field(default=None, max_length=128)
    worldbook_ids: list[str] | None = Field(default=None, max_length=128)

    _unique_lists = field_validator("tools_allowed", "knowledge_base_ids", "worldbook_ids")(unique_list)


class ConfigurationSources(StrictModel):
    persona: Literal["session", "character", "binding"]
    memory: Literal["session", "character"] = "character"
    memory_learning: Literal["session", "character"] = "character"
    context: Literal["session", "character"]
    temperature: Literal["session", "character", "model"]
    reasoning: Literal["session", "character"]
    harness: Literal["session", "character"]
    tools: Literal["session", "character"]
    knowledge: Literal["session", "character"]
    worldbook: Literal["session", "character"]


class ResolvedChatConfig(StrictModel):
    session_kind: Literal["normal", "qqbot"]
    character_id: str
    character_name: str
    character_avatar_attachment_id: str | None = None
    system_prompt: str
    persona_id: str | None
    persona_name: str | None
    persona_background: str = ""
    sources: ConfigurationSources
    context_policy: ContextPolicy
    context_limits: ContextLimits = Field(default_factory=ContextLimits)
    model_profile_id: str | None
    model_source: Literal["session", "character"]
    generation: GenerationParameters
    reasoning: bool = True
    harness_enabled: bool
    memory_enabled: bool = False
    memory_learning: Literal["manual", "automatic"] = "manual"
    tools_allowed: list[str]
    knowledge_base_ids: list[str]
    worldbook_ids: list[str]
    qq_reply_message_limit: int | None = Field(default=None, ge=1, le=20, strict=True)
    qq_bot_account: str | None = None
    qq_target_kind: Literal["group", "friend"] | None = None
    qq_target_id: str | None = None
    qq_image_description_model_profile_id: str | None = None
    qq_image_generation_model_profile_id: str | None = None
    qq_image_generation_options: ImageGenerationControls = Field(default_factory=ImageGenerationControls)
    qq_image_generation_allowed: bool = False
    qq_image_candidates: list[QQImageCandidate] = Field(default_factory=list)

    def public_summary(self) -> dict:
        return self.model_dump(mode="json", exclude={"system_prompt", "persona_background",
            "qq_bot_account", "qq_target_kind", "qq_target_id", "qq_image_generation_allowed", "qq_image_candidates"})
