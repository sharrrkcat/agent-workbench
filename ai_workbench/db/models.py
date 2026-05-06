from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SessionRecord(SQLModel, table=True):
    session_id: str = Field(primary_key=True)
    title: str = ""
    default_agent_id: str = "chat"
    waiting_run_id: Optional[str] = None
    llm_profile_id: Optional[str] = None
    last_announced_llm_profile_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MessageRecord(SQLModel, table=True):
    message_id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    role: str
    content_json: str
    output_type: str = "text"
    agent_id: Optional[str] = None
    command_name: Optional[str] = None
    action_id: Optional[str] = None
    run_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    available_actions_json: str = "[]"
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RunRecord(SQLModel, table=True):
    run_id: str = Field(primary_key=True)
    kind: str
    target_id: str
    action_id: Optional[str] = None
    session_id: str = Field(index=True)
    status: str
    current_step: str = ""
    error: Optional[str] = None
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RunEventRecord(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    session_id: str = Field(index=True)
    type: str
    message: str = ""
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentConfigRecord(SQLModel, table=True):
    agent_id: str = Field(primary_key=True)
    enabled: bool = True
    user_config_json: str = "{}"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CapabilityConfigRecord(SQLModel, table=True):
    capability_id: str = Field(primary_key=True)
    enabled: bool = True
    user_config_json: str = "{}"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LLMProfileRecord(SQLModel, table=True):
    __tablename__ = "llm_profiles"

    id: str = Field(primary_key=True)
    alias: str = Field(index=True)
    name: str
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AppMetadataRecord(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)
