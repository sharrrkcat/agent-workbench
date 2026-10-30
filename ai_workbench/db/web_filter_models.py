"""Persistent web-search rules and subscription download outcomes."""
from datetime import datetime

from sqlalchemy import Column, DateTime, Text, text
from sqlmodel import Field, SQLModel

from ai_workbench.core.time import utc_now


class WebFilterSettingsRecord(SQLModel, table=True):
    __tablename__ = "web_filter_settings"
    id: int = Field(default=1, primary_key=True)
    custom_rules: str = Field(sa_column=Column(Text, nullable=False))
    next_update_at: datetime | None = None


class WebSubscriptionRecord(SQLModel, table=True):
    __tablename__ = "web_filter_subscriptions"
    id: str = Field(primary_key=True)
    name: str
    url: str = Field(unique=True)
    enabled: bool = True
    rules_text: str = Field(default="", sa_column=Column(Text, nullable=False))
    rule_count: int = 0
    created_at: datetime = Field(default_factory=utc_now,
                                 sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_line: int | None = None

