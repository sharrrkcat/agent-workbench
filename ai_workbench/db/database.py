"""Database engine and Alembic schema bootstrap."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sqlmodel import create_engine

from ai_workbench.db import migrations


DEFAULT_DATABASE_URL = "sqlite:///./data/agent_workbench.db"


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
    """Alembic is the only schema authority; unversioned nonempty DBs are invalid."""
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Only SQLite is supported")
    revision = migrations.current_revision(engine)
    if revision is None and not migrations.is_empty_database(engine):
        raise RuntimeError("ALEMBIC_VERSION_REQUIRED: recreate the unversioned test database")
    migrations.upgrade(engine, "head")
