"""Alembic bootstrap and SQLite schema safety helpers.

Phase 0 deliberately keeps the legacy schema readable.  The helpers in this
module only add missing compatibility objects; they never drop tables or
rewrite user rows while an unversioned database is being stamped.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.engine import Connection, make_url


BASELINE_REVISION = "0001_current_schema"
ALEMBIC_INI_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"

# These are the indexes emitted by the current model metadata.  Some older
# databases do not have the five provider/origin/sort-order indexes; adding
# them is an additive, data-preserving compatibility step.
BASELINE_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_embedding_model_profiles_alias", "CREATE UNIQUE INDEX IF NOT EXISTS ix_embedding_model_profiles_alias ON embedding_model_profiles (alias)"),
    ("ix_embedding_model_profiles_provider_profile_id", "CREATE INDEX IF NOT EXISTS ix_embedding_model_profiles_provider_profile_id ON embedding_model_profiles (provider_profile_id)"),
    ("ix_image_generation_model_profiles_alias", "CREATE UNIQUE INDEX IF NOT EXISTS ix_image_generation_model_profiles_alias ON image_generation_model_profiles (alias)"),
    ("ix_kb_chunks_content_hash", "CREATE INDEX IF NOT EXISTS ix_kb_chunks_content_hash ON kb_chunks (content_hash)"),
    ("ix_kb_chunks_knowledge_base_id", "CREATE INDEX IF NOT EXISTS ix_kb_chunks_knowledge_base_id ON kb_chunks (knowledge_base_id)"),
    ("ix_kb_chunks_source_id", "CREATE INDEX IF NOT EXISTS ix_kb_chunks_source_id ON kb_chunks (source_id)"),
    ("ix_kb_embeddings_chunk_id", "CREATE INDEX IF NOT EXISTS ix_kb_embeddings_chunk_id ON kb_embeddings (chunk_id)"),
    ("ix_kb_embeddings_embedding_model_profile_id", "CREATE INDEX IF NOT EXISTS ix_kb_embeddings_embedding_model_profile_id ON kb_embeddings (embedding_model_profile_id)"),
    ("ix_kb_embeddings_knowledge_base_id", "CREATE INDEX IF NOT EXISTS ix_kb_embeddings_knowledge_base_id ON kb_embeddings (knowledge_base_id)"),
    ("ix_kb_embeddings_source_id", "CREATE INDEX IF NOT EXISTS ix_kb_embeddings_source_id ON kb_embeddings (source_id)"),
    ("ix_kb_origins_knowledge_base_id", "CREATE INDEX IF NOT EXISTS ix_kb_origins_knowledge_base_id ON kb_origins (knowledge_base_id)"),
    ("ix_kb_origins_slug", "CREATE INDEX IF NOT EXISTS ix_kb_origins_slug ON kb_origins (slug)"),
    ("ix_kb_origins_status", "CREATE INDEX IF NOT EXISTS ix_kb_origins_status ON kb_origins (status)"),
    ("ix_kb_sources_content_hash", "CREATE INDEX IF NOT EXISTS ix_kb_sources_content_hash ON kb_sources (content_hash)"),
    ("ix_kb_sources_file_status", "CREATE INDEX IF NOT EXISTS ix_kb_sources_file_status ON kb_sources (file_status)"),
    ("ix_kb_sources_knowledge_base_id", "CREATE INDEX IF NOT EXISTS ix_kb_sources_knowledge_base_id ON kb_sources (knowledge_base_id)"),
    ("ix_kb_sources_origin_id", "CREATE INDEX IF NOT EXISTS ix_kb_sources_origin_id ON kb_sources (origin_id)"),
    ("ix_kb_sources_source_type", "CREATE INDEX IF NOT EXISTS ix_kb_sources_source_type ON kb_sources (source_type)"),
    ("ix_kb_sources_status", "CREATE INDEX IF NOT EXISTS ix_kb_sources_status ON kb_sources (status)"),
    ("ix_knowledge_bases_embedding_model_profile_id", "CREATE INDEX IF NOT EXISTS ix_knowledge_bases_embedding_model_profile_id ON knowledge_bases (embedding_model_profile_id)"),
    ("ix_llm_profiles_alias", "CREATE INDEX IF NOT EXISTS ix_llm_profiles_alias ON llm_profiles (alias)"),
    ("ix_llm_profiles_provider_profile_id", "CREATE INDEX IF NOT EXISTS ix_llm_profiles_provider_profile_id ON llm_profiles (provider_profile_id)"),
    ("ix_messagerecord_session_id", "CREATE INDEX IF NOT EXISTS ix_messagerecord_session_id ON messagerecord (session_id)"),
    ("ix_multimodal_embedding_model_profiles_alias", "CREATE UNIQUE INDEX IF NOT EXISTS ix_multimodal_embedding_model_profiles_alias ON multimodal_embedding_model_profiles (alias)"),
    ("ix_multimodal_embedding_model_profiles_provider_profile_id", "CREATE INDEX IF NOT EXISTS ix_multimodal_embedding_model_profiles_provider_profile_id ON multimodal_embedding_model_profiles (provider_profile_id)"),
    ("ix_reranker_model_profiles_alias", "CREATE UNIQUE INDEX IF NOT EXISTS ix_reranker_model_profiles_alias ON reranker_model_profiles (alias)"),
    ("ix_reranker_model_profiles_provider_profile_id", "CREATE INDEX IF NOT EXISTS ix_reranker_model_profiles_provider_profile_id ON reranker_model_profiles (provider_profile_id)"),
    ("ix_runeventrecord_run_id", "CREATE INDEX IF NOT EXISTS ix_runeventrecord_run_id ON runeventrecord (run_id)"),
    ("ix_runeventrecord_session_id", "CREATE INDEX IF NOT EXISTS ix_runeventrecord_session_id ON runeventrecord (session_id)"),
    ("ix_runrecord_session_id", "CREATE INDEX IF NOT EXISTS ix_runrecord_session_id ON runrecord (session_id)"),
    ("ix_runsteprecord_order", "CREATE INDEX IF NOT EXISTS ix_runsteprecord_order ON runsteprecord (\"order\")"),
    ("ix_runsteprecord_parent_step_id", "CREATE INDEX IF NOT EXISTS ix_runsteprecord_parent_step_id ON runsteprecord (parent_step_id)"),
    ("ix_runsteprecord_run_id", "CREATE INDEX IF NOT EXISTS ix_runsteprecord_run_id ON runsteprecord (run_id)"),
    ("ix_session_knowledge_bindings_knowledge_base_id", "CREATE INDEX IF NOT EXISTS ix_session_knowledge_bindings_knowledge_base_id ON session_knowledge_bindings (knowledge_base_id)"),
    ("ix_session_knowledge_bindings_session_id", "CREATE INDEX IF NOT EXISTS ix_session_knowledge_bindings_session_id ON session_knowledge_bindings (session_id)"),
    ("ix_session_knowledge_bindings_sort_order", "CREATE INDEX IF NOT EXISTS ix_session_knowledge_bindings_sort_order ON session_knowledge_bindings (sort_order)"),
    ("ix_session_worldbook_bindings_session_id", "CREATE INDEX IF NOT EXISTS ix_session_worldbook_bindings_session_id ON session_worldbook_bindings (session_id)"),
    ("ix_session_worldbook_bindings_sort_order", "CREATE INDEX IF NOT EXISTS ix_session_worldbook_bindings_sort_order ON session_worldbook_bindings (sort_order)"),
    ("ix_session_worldbook_bindings_worldbook_id", "CREATE INDEX IF NOT EXISTS ix_session_worldbook_bindings_worldbook_id ON session_worldbook_bindings (worldbook_id)"),
    ("ix_sessionagentstaterecord_agent_id", "CREATE INDEX IF NOT EXISTS ix_sessionagentstaterecord_agent_id ON sessionagentstaterecord (agent_id)"),
    ("ix_sessionagentstaterecord_key", "CREATE INDEX IF NOT EXISTS ix_sessionagentstaterecord_key ON sessionagentstaterecord (\"key\")"),
    ("ix_sessionagentstaterecord_session_id", "CREATE INDEX IF NOT EXISTS ix_sessionagentstaterecord_session_id ON sessionagentstaterecord (session_id)"),
    ("ix_vision_model_profiles_alias", "CREATE UNIQUE INDEX IF NOT EXISTS ix_vision_model_profiles_alias ON vision_model_profiles (alias)"),
    ("ix_vision_model_profiles_provider_profile_id", "CREATE INDEX IF NOT EXISTS ix_vision_model_profiles_provider_profile_id ON vision_model_profiles (provider_profile_id)"),
    ("ix_worldbook_entries_sort_order", "CREATE INDEX IF NOT EXISTS ix_worldbook_entries_sort_order ON worldbook_entries (sort_order)"),
    ("ix_worldbook_entries_worldbook_id", "CREATE INDEX IF NOT EXISTS ix_worldbook_entries_worldbook_id ON worldbook_entries (worldbook_id)"),
)

CRITICAL_TABLES: tuple[str, ...] = (
    "sessionrecord",
    "messagerecord",
    "runrecord",
    "runsteprecord",
    "runeventrecord",
    "agentconfigrecord",
    "capabilityconfigrecord",
    "sessionagentstaterecord",
    "llm_profiles",
    "knowledge_settings",
    "worldbook_settings",
    "worldbooks",
    "worldbook_entries",
    "session_worldbook_bindings",
    "embedding_model_profiles",
    "reranker_model_profiles",
    "multimodal_embedding_model_profiles",
    "vision_model_profiles",
    "image_generation_model_profiles",
    "knowledge_bases",
    "kb_origins",
    "session_knowledge_bindings",
    "kb_sources",
    "kb_chunks",
    "kb_embeddings",
    "llm_provider_profiles",
    "appmetadatarecord",
)

LEGACY_COLUMNS: dict[str, tuple[str, ...]] = {
    "messagerecord": ("content_json", "output_type"),
}


class SchemaMismatchError(RuntimeError):
    """Raised when an unversioned database cannot be safely stamped."""

    def __init__(self, *, missing_tables: Iterable[str] = (), missing_columns: dict[str, Iterable[str]] | None = None, missing_indexes: Iterable[str] = ()) -> None:
        self.missing_tables = tuple(sorted(missing_tables))
        self.missing_columns = {
            table: tuple(sorted(columns))
            for table, columns in sorted((missing_columns or {}).items())
        }
        self.missing_indexes = tuple(sorted(missing_indexes))
        details: list[str] = []
        if self.missing_tables:
            details.append(f"tables={','.join(self.missing_tables)}")
        if self.missing_columns:
            details.append(
                "columns="
                + ";".join(f"{table}:{','.join(columns)}" for table, columns in self.missing_columns.items())
            )
        if self.missing_indexes:
            details.append(f"indexes={','.join(self.missing_indexes)}")
        suffix = "; ".join(details) or "unknown schema mismatch"
        super().__init__(f"DATABASE_SCHEMA_MISMATCH: {suffix}")


@dataclass(frozen=True)
class SchemaSignature:
    tables: tuple[str, ...]
    columns: dict[str, tuple[str, ...]]
    indexes: tuple[str, ...]
    virtual_tables: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tables": list(self.tables),
            "columns": {key: list(value) for key, value in self.columns.items()},
            "indexes": list(self.indexes),
            "virtual_tables": list(self.virtual_tables),
        }


@dataclass(frozen=True)
class BackupManifest:
    source: str
    backup: str
    created_at: str
    sha256: str
    bytes: int
    integrity_check: str
    critical_row_counts: dict[str, int]
    schema: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sqlite_connection(bind: Engine | Connection) -> tuple[Connection, bool]:
    if isinstance(bind, Connection):
        if bind.dialect.name != "sqlite":
            raise ValueError("SQLite database required")
        return bind, False
    if bind.dialect.name != "sqlite":
        raise ValueError("SQLite database required")
    return bind.connect(), True


def inspect_schema(bind: Engine | Connection) -> SchemaSignature:
    connection, should_close = _sqlite_connection(bind)
    try:
        rows = connection.exec_driver_sql(
            "SELECT type, name FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        tables = tuple(sorted(name for kind, name in rows if kind == "table" and not name.startswith("kb_chunk_fts_")))
        virtual_tables = tuple(sorted(name for kind, name in rows if kind == "table" and name == "kb_chunk_fts"))
        columns: dict[str, tuple[str, ...]] = {}
        for table in tables:
            escaped = table.replace('"', '""')
            columns[table] = tuple(
                row[1] for row in connection.exec_driver_sql(f'PRAGMA table_info("{escaped}")').fetchall()
            )
        indexes = tuple(
            sorted(
                name
                for kind, name in rows
                if kind == "index" and not name.startswith("sqlite_")
            )
        )
        return SchemaSignature(tables=tables, columns=columns, indexes=indexes, virtual_tables=virtual_tables)
    finally:
        if should_close:
            connection.close()


def _expected_columns() -> dict[str, set[str]]:
    # Import lazily to avoid a db.models/database import cycle.
    from sqlmodel import SQLModel

    import ai_workbench.db.models  # noqa: F401 - registers SQLModel metadata

    result = {
        name: set(table.columns.keys())
        for name, table in SQLModel.metadata.tables.items()
    }
    for table, columns in LEGACY_COLUMNS.items():
        result.setdefault(table, set()).update(columns)
    return result


def validate_baseline_compatibility(bind: Engine | Connection) -> SchemaSignature:
    signature = inspect_schema(bind)
    actual_tables = set(signature.tables)
    missing_tables = set(CRITICAL_TABLES) - actual_tables
    expected_columns = _expected_columns()
    missing_columns: dict[str, set[str]] = {}
    for table, columns in expected_columns.items():
        if table not in actual_tables:
            continue
        missing = columns - set(signature.columns.get(table, ()))
        if missing:
            missing_columns[table] = missing
    missing_indexes = set(name for name, _ in BASELINE_INDEXES) - set(signature.indexes)
    if "kb_chunk_fts" not in signature.virtual_tables:
        missing_tables.add("kb_chunk_fts (FTS5)")
    if missing_tables or missing_columns or missing_indexes:
        raise SchemaMismatchError(
            missing_tables=missing_tables,
            missing_columns=missing_columns,
            missing_indexes=missing_indexes,
        )
    return signature


def ensure_additive_compatibility(bind: Engine | Connection) -> None:
    connection, should_close = _sqlite_connection(bind)
    try:
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "messagerecord" in tables:
            columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(messagerecord)").fetchall()
            }
            for column in LEGACY_COLUMNS["messagerecord"]:
                if column not in columns:
                    connection.exec_driver_sql(f"ALTER TABLE messagerecord ADD COLUMN {column} VARCHAR")
        existing_tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for _, ddl in BASELINE_INDEXES:
            # An index can only be created after its table exists.  The legacy
            # bootstrap normally creates every table first, but filtering here
            # keeps this helper safe when called directly on a partial schema.
            table_name = ddl.split(" ON ", 1)[1].split(" ", 1)[0] if " ON " in ddl else ""
            if table_name in existing_tables:
                connection.exec_driver_sql(ddl)
        if should_close:
            connection.commit()
    finally:
        if should_close:
            connection.close()


def is_empty_database(bind: Engine | Connection) -> bool:
    signature = inspect_schema(bind)
    return not (set(signature.tables) & set(CRITICAL_TABLES))


def has_alembic_version(bind: Engine | Connection) -> bool:
    signature = inspect_schema(bind)
    return "alembic_version" in signature.tables


def current_revision(bind: Engine | Connection) -> str | None:
    connection, should_close = _sqlite_connection(bind)
    try:
        try:
            rows = connection.exec_driver_sql("SELECT version_num FROM alembic_version").fetchall()
        except Exception as exc:
            raise RuntimeError("ALEMBIC_VERSION_INVALID: cannot read alembic_version") from exc
        if len(rows) > 1:
            raise RuntimeError("ALEMBIC_VERSION_INVALID: multiple current revisions")
        return str(rows[0][0]) if rows else None
    finally:
        if should_close:
            connection.close()


def _alembic_config(connection: Connection | None = None) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_INI_PATH.parent / "alembic"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def upgrade(bind: Engine | Connection, revision: str = "head") -> None:
    if isinstance(bind, Connection):
        command.upgrade(_alembic_config(bind), revision)
        return
    with bind.begin() as connection:
        command.upgrade(_alembic_config(connection), revision)


def downgrade(bind: Engine | Connection, revision: str = "-1") -> None:
    """Run a downgrade, primarily for disposable migration test databases."""
    if isinstance(bind, Connection):
        command.downgrade(_alembic_config(bind), revision)
        return
    with bind.begin() as connection:
        command.downgrade(_alembic_config(connection), revision)


def stamp(bind: Engine | Connection, revision: str = BASELINE_REVISION) -> None:
    if isinstance(bind, Connection):
        command.stamp(_alembic_config(bind), revision)
        return
    with bind.begin() as connection:
        command.stamp(_alembic_config(connection), revision)


def sqlite_database_path(bind: Engine) -> Path | None:
    """Return the resolved on-disk SQLite path, or ``None`` for memory DBs."""
    return _sqlite_path(bind)


def _sqlite_path(bind: Engine) -> Path | None:
    url = make_url(str(bind.url))
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()


def _critical_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    return {
        table: int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
        for table in CRITICAL_TABLES
        if table in tables
    }


def backup_sqlite_database(bind: Engine, *, reason: str) -> BackupManifest | None:
    source_path = _sqlite_path(bind)
    if source_path is None or not source_path.exists() or source_path.stat().st_size == 0:
        return None
    backup_dir = (source_path.parent / "backups" / "database").resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"{source_path.stem}.pre-{reason}-{timestamp}"
    backup_path = (backup_dir / f"{stem}.db").resolve()
    backup_path.relative_to(source_path.parent)
    suffix = 1
    while backup_path.exists():
        backup_path = (backup_dir / f"{stem}-{suffix}.db").resolve()
        backup_path.relative_to(source_path.parent)
        suffix += 1

    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(str(backup_path))
    copy_error: Exception | None = None
    try:
        try:
            source.backup(destination)
            destination.commit()
        except Exception as exc:
            # Do not leave a misleading partial backup after a failed copy.
            destination.rollback()
            copy_error = exc
    finally:
        destination.close()
        source.close()
    if copy_error is not None:
        backup_path.unlink(missing_ok=True)
        raise copy_error

    check = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = str(check.execute("PRAGMA integrity_check").fetchone()[0])
        counts = _critical_counts(check)
    finally:
        check.close()
    if integrity != "ok":
        raise RuntimeError(f"DATABASE_BACKUP_INVALID: {integrity}")
    digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    manifest = BackupManifest(
        source=str(source_path),
        backup=str(backup_path),
        created_at=datetime.now(timezone.utc).isoformat(),
        sha256=digest,
        bytes=backup_path.stat().st_size,
        integrity_check=integrity,
        critical_row_counts=counts,
        schema=inspect_schema(bind).as_dict(),
    )
    manifest_path = backup_path.with_suffix(".json")
    manifest_path.write_text(
        json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
