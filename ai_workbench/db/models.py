from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from ai_workbench.core.time import utc_now


class SessionRecord(SQLModel, table=True):
    session_id: str = Field(primary_key=True)
    title: str = ""
    default_agent_id: str = "chat"
    context_mode: str = "single_assistant"
    waiting_run_id: Optional[str] = None
    llm_profile_id: Optional[str] = None
    last_announced_llm_profile_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MessageRecord(SQLModel, table=True):
    message_id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    role: str
    content_json: str
    speaker_type: Optional[str] = None
    speaker_id: Optional[str] = None
    speaker_name: Optional[str] = None
    origin: Optional[str] = None
    output_type: str = "text"
    agent_id: Optional[str] = None
    command_name: Optional[str] = None
    action_id: Optional[str] = None
    run_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    available_actions_json: str = "[]"
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)


class RunRecord(SQLModel, table=True):
    run_id: str = Field(primary_key=True)
    kind: str
    target_id: str
    action_id: Optional[str] = None
    session_id: str = Field(index=True)
    status: str
    current_step: str = ""
    stage: str = ""
    progress_message: str = ""
    progress_current: Optional[int] = None
    progress_total: Optional[int] = None
    cancel_requested: bool = False
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error: Optional[str] = None
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RunStepRecord(SQLModel, table=True):
    step_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    parent_step_id: Optional[str] = Field(default=None, index=True)
    label: str
    status: str
    message: str = ""
    order: int = Field(default=0, index=True)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RunEventRecord(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    session_id: str = Field(index=True)
    type: str
    message: str = ""
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)


class AgentConfigRecord(SQLModel, table=True):
    agent_id: str = Field(primary_key=True)
    enabled: bool = True
    display_json: str = "{}"
    runtime_json: str = "{}"
    user_config_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CapabilityConfigRecord(SQLModel, table=True):
    capability_id: str = Field(primary_key=True)
    enabled: bool = True
    user_config_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class LLMProfileRecord(SQLModel, table=True):
    __tablename__ = "llm_profiles"

    id: str = Field(primary_key=True)
    alias: str = Field(index=True)
    name: str
    provider_profile_id: Optional[str] = Field(default=None, index=True)
    provider: str = "openai_compatible"
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
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ProviderProfileRecord(SQLModel, table=True):
    __tablename__ = "llm_provider_profiles"

    id: str = Field(primary_key=True)
    name: str
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: Optional[int] = 60
    enabled: bool = True
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AppMetadataRecord(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=utc_now)
