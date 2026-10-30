"""Shared extracted web pages and session-owned query associations."""
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, Text
from sqlmodel import Field, SQLModel

from ai_workbench.core.time import utc_now


class WebPageRecord(SQLModel, table=True):
    __tablename__ = "web_pages"
    __table_args__ = (CheckConstraint("content_src IN ('search', 'extract')", name="ck_web_content_src"),)
    url_key: str = Field(primary_key=True)
    raw_url: str
    title: str
    snippet: str
    content: str = Field(sa_column=Column(Text, nullable=False))
    links_json: str = Field(sa_column=Column(Text, nullable=False))
    content_hash: str
    content_src: str
    fetched_at: datetime = Field(default_factory=utc_now)
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_accessed_at: datetime = Field(default_factory=utc_now, index=True)


class WebSessionPageRecord(SQLModel, table=True):
    __tablename__ = "web_session_pages"
    session_id: str = Field(primary_key=True, foreign_key="sessionrecord.session_id")
    url_key: str = Field(primary_key=True, foreign_key="web_pages.url_key", index=True)
    query: str = Field(default="", primary_key=True)
    accessed_at: datetime = Field(default_factory=utc_now)
