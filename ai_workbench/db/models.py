from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SessionRecord(SQLModel, table=True):
    session_id: str = Field(primary_key=True)
    title: str = ""
    default_agent_id: str = "chat"
    waiting_run_id: Optional[str] = None
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


class AppMetadataRecord(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)
