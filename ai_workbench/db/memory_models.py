"""Current durable content and its disposable lexical index."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, Text, Index
from sqlmodel import Field, SQLModel


class DurableMemoryRecord(SQLModel, table=True):
    __tablename__ = "durable_memories"
    __table_args__ = (
        CheckConstraint("pool IN ('character', 'general')", name="ck_memory_pool"),
        CheckConstraint("pool != 'general' OR session_id IS NULL", name="ck_general_memory_session"),
        CheckConstraint("status IN ('active', 'needs_review', 'deleted')", name="ck_memory_status"),
        Index("ix_memory_audience", "persona_id", "pool", "character_id", "status"),
    )
    id: str = Field(primary_key=True)
    revision: int
    pool: str
    character_id: str
    persona_id: str = Field(index=True)
    session_id: str | None = Field(default=None, index=True)
    status: str
    managed_by: str
    pinned: bool
    observed_at: datetime
    updated_at: datetime
    origin_run_id: str | None = Field(default=None, index=True)
    origin_session_id: str | None = Field(default=None, index=True)
    record_json: str = Field(sa_column=Column(Text, nullable=False))


class DurableMemoryTerm(SQLModel, table=True):
    __tablename__ = "durable_memory_terms"
    memory_id: str = Field(primary_key=True)
    term: str = Field(primary_key=True, index=True)
    weight: int


class DurableMemoryDependency(SQLModel, table=True):
    __tablename__ = "durable_memory_dependencies"
    memory_id: str = Field(primary_key=True)
    session_id: str = Field(primary_key=True, index=True)


class DurableMemoryEvidence(SQLModel, table=True):
    __tablename__ = "durable_memory_evidence"
    memory_id: str = Field(primary_key=True)
    message_id: str = Field(primary_key=True, index=True)
