"""Database engine and Alembic schema bootstrap."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Optional

from sqlalchemy.engine import make_url
from sqlmodel import create_engine


DEFAULT_DATABASE_URL = "sqlite:///./data/cogita.db"


def get_database_url(database_url: Optional[str] = None) -> str:
    return database_url or os.getenv("COGITA_DATABASE_URL") or DEFAULT_DATABASE_URL


def get_engine(database_url: Optional[str] = None):
    resolved = make_url(get_database_url(database_url))
    if resolved.get_backend_name() == "sqlite":
        if resolved.database and resolved.database != ":memory:" and resolved.query.get("mode") != "memory":
            Path(resolved.database).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(resolved, connect_args={"check_same_thread": False})
    return create_engine(resolved)


def get_initialized_engine(database_url: Optional[str] = None):
    """Migrate persistent databases before opening the application's connections."""
    url = make_url(get_database_url(database_url))
    if url.get_backend_name() != "sqlite":
        raise RuntimeError("Only SQLite is supported")
    if not url.database or url.database == ":memory:" or url.query.get("mode") == "memory":
        engine = get_engine(url.render_as_string(hide_password=False))
        init_db(engine)
        return engine
    url = url.set(database=str(Path(url.database).resolve()))
    resolved = url.render_as_string(hide_password=False)
    subprocess.run([sys.executable, "-B", "-m", "ai_workbench.db.bootstrap", "--database-url", resolved],
                   cwd=Path(__file__).resolve().parents[2], check=True)
    return get_engine(resolved)


def init_db(engine) -> None:
    """Alembic is the only schema authority; unversioned nonempty DBs are invalid."""
    from ai_workbench.db import migrations

    if engine.dialect.name != "sqlite":
        raise RuntimeError("Only SQLite is supported")
    revision = migrations.current_revision(engine)
    if revision is None and not migrations.is_empty_database(engine):
        raise RuntimeError("ALEMBIC_VERSION_REQUIRED: recreate the unversioned test database")
    migrations.upgrade(engine, "head")
