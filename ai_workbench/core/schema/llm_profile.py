import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


LLM_PROFILE_ALIAS_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
LLM_PROFILE_PROVIDERS = ("openai_compatible", "lm_studio", "llama_cpp", "custom")


class LLMProfileSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    alias: str
    name: str
    provider: Literal["openai_compatible", "lm_studio", "llama_cpp", "custom"] = "openai_compatible"
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
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

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
