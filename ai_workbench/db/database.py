import os
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from ai_workbench.db.models import AppMetadataRecord


DEFAULT_DATABASE_URL = "sqlite:///./data/agent_workbench.db"
SCHEMA_VERSION = "1"


def get_database_url(database_url: Optional[str] = None) -> str:
    return database_url or os.getenv("AGENT_WORKBENCH_DATABASE_URL") or DEFAULT_DATABASE_URL


def get_engine(database_url: Optional[str] = None):
    resolved_url = get_database_url(database_url)
    if resolved_url.startswith("sqlite:///"):
        db_path = resolved_url.replace("sqlite:///", "", 1)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(resolved_url, connect_args={"check_same_thread": False})
    return create_engine(resolved_url)


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    ensure_session_model_columns(engine)
    ensure_agent_config_columns(engine)
    ensure_schema_version(engine)


def ensure_session_model_columns(engine) -> None:
    with engine.begin() as connection:
        dialect = connection.dialect.name
        if dialect != "sqlite":
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(sessionrecord)").fetchall()}
        if "llm_profile_id" not in columns:
            connection.execute(text("ALTER TABLE sessionrecord ADD COLUMN llm_profile_id VARCHAR"))
        if "last_announced_llm_profile_id" not in columns:
            connection.execute(text("ALTER TABLE sessionrecord ADD COLUMN last_announced_llm_profile_id VARCHAR"))


def ensure_agent_config_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(agentconfigrecord)").fetchall()}
        if "display_json" not in columns:
            connection.execute(text("ALTER TABLE agentconfigrecord ADD COLUMN display_json VARCHAR DEFAULT '{}'"))
        if "runtime_json" not in columns:
            connection.execute(text("ALTER TABLE agentconfigrecord ADD COLUMN runtime_json VARCHAR DEFAULT '{}'"))


def ensure_schema_version(engine, expected_version: str = SCHEMA_VERSION) -> None:
    with Session(engine) as session:
        record = session.get(AppMetadataRecord, "schema_version")
        if record is None:
            session.add(AppMetadataRecord(key="schema_version", value=expected_version))
            session.commit()
            return
        if record.value != expected_version:
            raise RuntimeError(
                "SCHEMA_VERSION_MISMATCH: "
                f"expected schema_version {expected_version}, found {record.value}"
            )
