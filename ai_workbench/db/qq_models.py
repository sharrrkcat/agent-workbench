"""Durable QQ ingress, batching and delivery records."""
from sqlalchemy import UniqueConstraint, Index, false
from sqlmodel import SQLModel, Field


class QQBinding(SQLModel, table=True):
    __tablename__ = "qq_bindings"
    __table_args__ = (UniqueConstraint("project_id", "target_kind", "target_id"),)
    session_id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    target_kind: str
    target_id: str
    paused: bool = False
    pause_reason: str = ""
    deadline: float | None = None


class QQMessage(SQLModel, table=True):
    __tablename__ = "qq_messages"
    __table_args__ = (UniqueConstraint("session_id", "external_id"),
        Index("ix_qq_message_pending", "session_id", "disposition", "id"))
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    external_id: str
    sender_id: str
    sender_name: str
    timestamp: str
    text: str
    references_json: str = "[]"
    disposition: str = "pending"
    batch_id: int | None = None


class QQBatch(SQLModel, table=True):
    __tablename__ = "qq_batches"
    __table_args__ = (Index("ix_qq_batch_queue", "project_id", "status", "id"),)
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    project_id: str
    status: str = "queued"
    text: str
    created_at: float
    input_message_id: str | None = None
    run_id: str | None = None
    error_code: str | None = None


class QQDelivery(SQLModel, table=True):
    __tablename__ = "qq_deliveries"
    __table_args__ = (UniqueConstraint("run_id", "tool_call_id"),
        Index("ix_qq_delivery_external", "session_id", "external_id"))
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    run_id: str = Field(index=True)
    tool_call_id: str
    text: str
    status: str = "pending"
    external_id: str | None = None
    error_code: str | None = None
    created_at: float
    echoed: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
