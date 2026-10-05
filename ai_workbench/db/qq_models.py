"""Durable QQ ingress, batching and delivery records."""
from sqlalchemy import UniqueConstraint, ForeignKeyConstraint, Index, false, func
from sqlmodel import SQLModel, Field
from pydantic import PrivateAttr
from ai_workbench.core.schema.qq import QQImageAttachment, QQMediaSource, participant_epochs
from ai_workbench.core.time import utc_now
from datetime import datetime


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
    window_kind: str = Field(default="keyword", sa_column_kwargs={"server_default": "keyword"})
    icebreaker_cooldown_until: float | None = None


class QQParticipant(SQLModel, table=True):
    __tablename__ = "qq_participants"
    session_id: str = Field(primary_key=True)
    sender_id: str = Field(primary_key=True)
    keyword_message_id: int
    expires_at: float
    in_window: bool = Field(default=False, sa_column_kwargs={"server_default": false()})


class QQMessage(SQLModel, table=True):
    __tablename__ = "qq_messages"
    __table_args__ = (UniqueConstraint("session_id", "external_id"),
        Index("ix_qq_message_pending", "session_id", "disposition", "id"),
        Index("ix_qq_message_batch", "batch_id", "deleted", "id"))
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
    deleted: bool = Field(default=False, sa_column_kwargs={"server_default": false()})


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
    trigger_kind: str = Field(default="keyword", sa_column_kwargs={"server_default": "keyword"})
    participants_json: str = Field(default="{}", sa_column_kwargs={"server_default": "{}"})

    @property
    def participants(self) -> dict[str, int]:
        return participant_epochs.validate_json(self.participants_json)


class QQMediaAsset(SQLModel, table=True):
    __tablename__ = "qq_media_assets"
    __table_args__ = (UniqueConstraint("sha256"), {"sqlite_autoincrement": True})
    id: int | None = Field(default=None, primary_key=True)
    sha256: str
    attachment_json: str
    model_attachment_json: str | None = None
    description: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    is_favorite: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    description_manual: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    created_at: datetime = Field(default_factory=utc_now, sa_column_kwargs={"server_default": func.current_timestamp()})

    @property
    def attachment(self) -> QQImageAttachment:
        return QQImageAttachment.model_validate_json(self.attachment_json)

    @property
    def model_attachment(self) -> QQImageAttachment | None:
        return QQImageAttachment.model_validate_json(self.model_attachment_json) if self.model_attachment_json else None


class QQMedia(SQLModel, table=True):
    __tablename__ = "qq_media"
    __table_args__ = (UniqueConstraint("message_id", "segment_index"),
        Index("ix_qq_media_pending", "status", "id"), {"sqlite_autoincrement": True})
    id: int | None = Field(default=None, primary_key=True)
    message_id: int = Field(index=True)
    segment_index: int
    text_start: int
    text_end: int
    kind: str
    source_json: str
    status: str = "pending"
    asset_id: int | None = Field(default=None, foreign_key="qq_media_assets.id", index=True)
    error_code: str | None = None
    _asset: QQMediaAsset | None = PrivateAttr(default=None)

    @property
    def source(self) -> QQMediaSource:
        return QQMediaSource.model_validate_json(self.source_json)

    @property
    def attachment(self) -> QQImageAttachment | None:
        return self._asset.attachment if self._asset else None

    @property
    def model_attachment(self) -> QQImageAttachment | None:
        return self._asset.model_attachment if self._asset else None

    @property
    def description(self) -> str | None:
        return self._asset.description if self._asset else None


class QQDelivery(SQLModel, table=True):
    __tablename__ = "qq_deliveries"
    __table_args__ = (UniqueConstraint("run_id", "tool_call_id"),
        Index("ix_qq_delivery_external", "session_id", "external_id"),
        ForeignKeyConstraint(["asset_id"], ["qq_media_assets.id"], name="fk_qq_delivery_asset"))
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
    deleted: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    kind: str = Field(default="text", sa_column_kwargs={"server_default": "text"})
    prompt: str | None = None
    asset_id: int | None = Field(default=None, index=True)
