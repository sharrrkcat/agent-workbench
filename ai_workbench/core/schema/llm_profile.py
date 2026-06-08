import re
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from ai_workbench.core.time import isoformat_utc, utc_now


LLM_PROFILE_ALIAS_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
LLM_PROFILE_PROVIDERS = (
    "openai_compatible",
    "lm_studio",
    "llama_cpp",
    "custom",
    "ollama",
    "internal_transformers",
    "internal_llama_cpp",
)
PROVIDER_PROFILE_PROVIDERS = (
    "openai_compatible",
    "lm_studio",
    "llama_cpp",
    "custom",
    "ollama",
    "internal_transformers",
    "internal_llama_cpp",
)
ProviderProfileProvider = Literal[
    "openai_compatible",
    "lm_studio",
    "llama_cpp",
    "custom",
    "ollama",
    "internal_transformers",
    "internal_llama_cpp",
]


class LLMProfileSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    alias: str
    name: str
    provider_profile_id: Optional[str] = None
    provider: ProviderProfileProvider = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model_id: str = ""
    enabled: bool = True
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None
    supports_vision: bool = False
    supports_tools: bool = False
    supports_reasoning: bool = False
    supports_streaming: bool = True
    supports_json_mode: bool = False
    external_inference_enabled: bool = False
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, value: str) -> str:
        if not value or not LLM_PROFILE_ALIAS_RE.match(value):
            raise ValueError("alias must contain only letters, numbers, underscores, or hyphens")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be empty")
        return value


class ProviderProfileSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    provider: ProviderProfileProvider = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: Optional[int] = 60
    enabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""

    @field_validator("name")
    @classmethod
    def validate_provider_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be empty")
        return value
