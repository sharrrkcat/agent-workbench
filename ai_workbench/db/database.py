import os
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from ai_workbench.core.time import utc_now
from ai_workbench.db.models import AppMetadataRecord, LLMProfileRecord, ProviderProfileRecord


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
    ensure_knowledge_index_tables(engine)
    ensure_knowledge_origin_columns(engine)
    ensure_knowledge_source_origin_columns(engine)
    ensure_session_model_columns(engine)
    ensure_message_speaker_columns(engine)
    ensure_agent_config_columns(engine)
    ensure_llm_profile_columns(engine)
    ensure_knowledge_settings_columns(engine)
    ensure_knowledge_base_columns(engine)
    ensure_worldbook_settings_columns(engine)
    ensure_session_knowledge_binding_columns(engine)
    ensure_run_lifecycle_columns(engine)
    migrate_llm_provider_profiles(engine)
    ensure_schema_version(engine)


def ensure_knowledge_index_tables(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
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


def ensure_knowledge_origin_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "kb_origins" not in tables:
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(kb_origins)").fetchall()}
        additions = {
            "include_globs": "VARCHAR DEFAULT '**/*'",
            "exclude_globs": "VARCHAR DEFAULT ''",
            "default_chunk_profile": "VARCHAR",
            "last_scan_at": "DATETIME",
            "last_import_at": "DATETIME",
            "status": "VARCHAR DEFAULT 'ready'",
            "error": "VARCHAR",
            "metadata_json": "VARCHAR DEFAULT '{}'",
            "created_at": "DATETIME",
            "updated_at": "DATETIME",
        }
        for column, ddl in additions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE kb_origins ADD COLUMN {column} {ddl}"))


def ensure_knowledge_source_origin_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "kb_sources" not in tables:
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(kb_sources)").fetchall()}
        additions = {
            "origin_id": "VARCHAR",
            "relative_path": "VARCHAR DEFAULT ''",
            "virtual_path": "VARCHAR DEFAULT ''",
            "folder_path": "VARCHAR DEFAULT ''",
            "file_name": "VARCHAR DEFAULT ''",
            "extension": "VARCHAR DEFAULT ''",
            "path_depth": "INTEGER DEFAULT 0",
            "file_status": "VARCHAR DEFAULT 'ready'",
            "source_mtime": "DATETIME",
            "source_size_bytes": "INTEGER DEFAULT 0",
        }
        for column, ddl in additions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE kb_sources ADD COLUMN {column} {ddl}"))


def ensure_session_model_columns(engine) -> None:
    with engine.begin() as connection:
        dialect = connection.dialect.name
        if dialect != "sqlite":
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(sessionrecord)").fetchall()}
        if "context_mode" not in columns:
            connection.execute(text("ALTER TABLE sessionrecord ADD COLUMN context_mode VARCHAR DEFAULT 'single_assistant'"))
        if "llm_profile_id" not in columns:
            connection.execute(text("ALTER TABLE sessionrecord ADD COLUMN llm_profile_id VARCHAR"))
        if "last_announced_llm_profile_id" not in columns:
            connection.execute(text("ALTER TABLE sessionrecord ADD COLUMN last_announced_llm_profile_id VARCHAR"))
        if "title_generation_state" not in columns:
            connection.execute(text("ALTER TABLE sessionrecord ADD COLUMN title_generation_state VARCHAR DEFAULT 'pending'"))
        if "title_generation_metadata_json" not in columns:
            connection.execute(text("ALTER TABLE sessionrecord ADD COLUMN title_generation_metadata_json VARCHAR DEFAULT '{}'"))


def ensure_session_knowledge_binding_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "session_knowledge_bindings" not in tables:
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(session_knowledge_bindings)").fetchall()}
        if "sort_order" not in columns:
            connection.execute(text("ALTER TABLE session_knowledge_bindings ADD COLUMN sort_order INTEGER DEFAULT 0"))


def ensure_message_speaker_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "messagerecord" not in tables:
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(messagerecord)").fetchall()}
        for column in ("speaker_type", "speaker_id", "speaker_name", "origin"):
            if column not in columns:
                connection.execute(text(f"ALTER TABLE messagerecord ADD COLUMN {column} VARCHAR"))


def ensure_agent_config_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(agentconfigrecord)").fetchall()}
        if "display_json" not in columns:
            connection.execute(text("ALTER TABLE agentconfigrecord ADD COLUMN display_json VARCHAR DEFAULT '{}'"))
        if "runtime_json" not in columns:
            connection.execute(text("ALTER TABLE agentconfigrecord ADD COLUMN runtime_json VARCHAR DEFAULT '{}'"))


def ensure_llm_profile_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "llm_profiles" not in tables:
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(llm_profiles)").fetchall()}
        if "provider_profile_id" not in columns:
            connection.execute(text("ALTER TABLE llm_profiles ADD COLUMN provider_profile_id VARCHAR"))


def ensure_knowledge_settings_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "knowledge_settings" not in tables:
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(knowledge_settings)").fetchall()}
        additions = {
            "min_score_threshold": "FLOAT",
            "retrieval_max_chunks_per_source": "INTEGER",
            "retrieval_max_chunks_per_knowledge_base": "INTEGER",
            "query_expansion_enabled": "BOOLEAN DEFAULT 0",
            "query_expansion_max_variants": "INTEGER DEFAULT 3",
            "query_expansion_prompt": (
                "VARCHAR DEFAULT 'Generate up to {max_variants} short search query variants for the user''s query.\n"
                "Use the same language when useful.\n"
                "Return only a JSON array of strings.\n\n"
                "User query:\n"
                "{query}'"
            ),
            "unload_embedding_model_after_use": "BOOLEAN DEFAULT 0",
            "unload_reranker_model_after_use": "BOOLEAN DEFAULT 0",
            "default_chunk_profile": "VARCHAR",
        }
        for column, ddl in additions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE knowledge_settings ADD COLUMN {column} {ddl}"))


def ensure_knowledge_base_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "knowledge_bases" not in tables:
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(knowledge_bases)").fetchall()}
        if "aliases_text" not in columns:
            connection.execute(text("ALTER TABLE knowledge_bases ADD COLUMN aliases_text VARCHAR DEFAULT ''"))
        if "default_chunk_profile" not in columns:
            connection.execute(text("ALTER TABLE knowledge_bases ADD COLUMN default_chunk_profile VARCHAR"))


def ensure_worldbook_settings_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "worldbook_settings" not in tables:
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(worldbook_settings)").fetchall()}
        additions = {
            "worldbook_recursion_depth": "INTEGER DEFAULT 0",
            "worldbook_case_sensitive": "BOOLEAN DEFAULT 0",
            "worldbook_whole_words": "BOOLEAN DEFAULT 1",
        }
        for column, ddl in additions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE worldbook_settings ADD COLUMN {column} {ddl}"))


def ensure_run_lifecycle_columns(engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "runrecord" not in tables:
            return
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runrecord)").fetchall()}
        additions = {
            "stage": "VARCHAR DEFAULT ''",
            "progress_message": "VARCHAR DEFAULT ''",
            "progress_current": "INTEGER",
            "progress_total": "INTEGER",
            "cancel_requested": "BOOLEAN DEFAULT 0",
            "started_at": "DATETIME",
            "finished_at": "DATETIME",
            "error_code": "VARCHAR",
            "error_message": "VARCHAR",
        }
        for column, ddl in additions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE runrecord ADD COLUMN {column} {ddl}"))
        if "runsteprecord" not in tables:
            return
        step_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runsteprecord)").fetchall()}
        if "parent_step_id" not in step_columns:
            connection.execute(text("ALTER TABLE runsteprecord ADD COLUMN parent_step_id VARCHAR"))


def migrate_llm_provider_profiles(engine) -> None:
    with Session(engine) as session:
        profiles = session.exec(select(LLMProfileRecord)).all()
        changed = False
        for profile in profiles:
            if profile.provider_profile_id:
                continue
            if not (profile.provider or profile.base_url or profile.api_key or profile.timeout):
                continue
            provider = _find_or_create_provider_profile(session, profile)
            profile.provider_profile_id = provider.id
            profile.updated_at = utc_now()
            session.add(profile)
            changed = True
        if changed:
            session.commit()


def _find_or_create_provider_profile(session: Session, profile: LLMProfileRecord) -> ProviderProfileRecord:
    fingerprint = _api_key_fingerprint(profile.api_key)
    timeout = profile.timeout if profile.timeout is not None else 60
    providers = session.exec(select(ProviderProfileRecord)).all()
    for provider in providers:
        if (
            provider.provider == profile.provider
            and provider.base_url == profile.base_url
            and provider.timeout_seconds == timeout
            and _api_key_fingerprint(provider.api_key) == fingerprint
        ):
            return provider
    provider = ProviderProfileRecord(
        id=str(uuid4()),
        name=_provider_profile_name(profile.provider, profile.base_url),
        provider=profile.provider or "openai_compatible",
        base_url=profile.base_url or "",
        api_key=profile.api_key or "",
        timeout_seconds=timeout,
        enabled=True,
        metadata_json=json.dumps({"migrated_from": "llm_profiles"}),
    )
    session.add(provider)
    session.flush()
    return provider


def _api_key_fingerprint(api_key: str) -> str:
    if not api_key:
        return ""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _provider_profile_name(provider: str, base_url: str) -> str:
    if provider == "lm_studio":
        return "LM Studio local"
    if provider == "llama_cpp":
        return "llama.cpp local"
    if provider == "openai_compatible":
        return "OpenAI compatible"
    return provider.replace("_", " ").title() if provider else (base_url or "Provider profile")


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
