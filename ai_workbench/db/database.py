"""Database engine and Phase 1 schema bootstrap."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlmodel import create_engine

from ai_workbench.db import migrations


DEFAULT_DATABASE_URL = "sqlite:///./data/agent_workbench.db"
SCHEMA_VERSION = "2"


def get_database_url(database_url: Optional[str] = None) -> str:
    return database_url or os.getenv("AGENT_WORKBENCH_DATABASE_URL") or DEFAULT_DATABASE_URL


def get_engine(database_url: Optional[str] = None):
    resolved = get_database_url(database_url)
    if resolved.startswith("sqlite:///"):
        database = resolved.removeprefix("sqlite:///")
        if database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(resolved, connect_args={"check_same_thread": False})
    return create_engine(resolved)


def init_db(engine) -> None:
    """Bring a database to the Phase 1 head.

    An unversioned database is stamped as the known baseline and immediately
    upgraded. The next revision intentionally drops and recreates affected
    tables, so no application-level data migration is attempted.
    """
    if engine.dialect.name != "sqlite":
        from sqlmodel import SQLModel
        import ai_workbench.db.models  # noqa: F401

        SQLModel.metadata.create_all(engine)
        return

    if not migrations.has_alembic_version(engine):
        if not migrations.is_empty_database(engine):
            migrations.stamp(engine, migrations.BASELINE_REVISION)
        migrations.upgrade(engine, "head")
    else:
        revision = migrations.current_revision(engine)
        if not revision:
            if migrations.is_empty_database(engine):
                migrations.upgrade(engine, "head")
            else:
                raise RuntimeError("ALEMBIC_VERSION_INVALID: empty alembic_version")
        elif revision != migrations.HEAD_REVISION:
            migrations.upgrade(engine, "head")

    ensure_knowledge_index_tables(engine)
    ensure_schema_version(engine)


def ensure_knowledge_index_tables(engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunk_fts
                USING fts5(
                  chunk_id UNINDEXED,
                  knowledge_base_id UNINDEXED,
                  source_id UNINDEXED,
                  title,
                  heading_path,
                  content,
                  search_text,
                  tokenize = 'unicode61'
                )
                """
            )
        )


def ensure_schema_version(engine, expected_version: str = SCHEMA_VERSION) -> None:
    from sqlmodel import Session
    from ai_workbench.db.models import AppMetadataRecord

    with Session(engine) as session:
        row = session.get(AppMetadataRecord, "schema_version")
        if row is None:
            session.add(AppMetadataRecord(key="schema_version", value=expected_version))
            session.commit()
        elif row.value != expected_version:
            row.value = expected_version
            session.add(row)
            session.commit()
