"""Small Alembic helpers for the destructive Phase 1 schema.

The application is still in a disposable test phase. The only supported
upgrade path is the normal Alembic path; no row copying, backups, or
compatibility inspection happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.engine import Connection, make_url


BASELINE_REVISION = "0001_current_schema"
PHASE1_REVISION = "0002_phase1_prune"
HEAD_REVISION = PHASE1_REVISION
ALEMBIC_INI_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"


@dataclass(frozen=True)
class SchemaSignature:
    tables: tuple[str, ...]
    columns: dict[str, tuple[str, ...]]
    indexes: tuple[str, ...]
    virtual_tables: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tables": list(self.tables),
            "columns": {name: list(columns) for name, columns in self.columns.items()},
            "indexes": list(self.indexes),
            "virtual_tables": list(self.virtual_tables),
        }


def _connection(bind: Engine | Connection) -> tuple[Connection, bool]:
    if isinstance(bind, Connection):
        return bind, False
    return bind.connect(), True


def inspect_schema(bind: Engine | Connection) -> SchemaSignature:
    connection, close = _connection(bind)
    try:
        rows = connection.exec_driver_sql(
            "SELECT type, name FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        tables = tuple(
            sorted(
                name
                for kind, name in rows
                if kind == "table" and not name.startswith("kb_chunk_fts_")
            )
        )
        virtual_tables = tuple(
            sorted(name for kind, name in rows if kind == "table" and name == "kb_chunk_fts")
        )
        columns: dict[str, tuple[str, ...]] = {}
        for table in tables:
            escaped = table.replace('"', '""')
            columns[table] = tuple(
                row[1]
                for row in connection.exec_driver_sql(f'PRAGMA table_info("{escaped}")').fetchall()
            )
        indexes = tuple(
            sorted(name for kind, name in rows if kind == "index" and not name.startswith("sqlite_"))
        )
        return SchemaSignature(tables, columns, indexes, virtual_tables)
    finally:
        if close:
            connection.close()


def has_alembic_version(bind: Engine | Connection) -> bool:
    return "alembic_version" in inspect_schema(bind).tables


def current_revision(bind: Engine | Connection) -> str | None:
    connection, close = _connection(bind)
    try:
        if "alembic_version" not in inspect_schema(connection).tables:
            return None
        rows = connection.exec_driver_sql("SELECT version_num FROM alembic_version").fetchall()
        if len(rows) > 1:
            raise RuntimeError("ALEMBIC_VERSION_INVALID: multiple current revisions")
        return str(rows[0][0]) if rows else None
    finally:
        if close:
            connection.close()


def _config(connection: Connection | None = None) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_INI_PATH.parent / "alembic"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def upgrade(bind: Engine | Connection, revision: str = "head") -> None:
    if isinstance(bind, Connection):
        command.upgrade(_config(bind), revision)
        return
    with bind.begin() as connection:
        command.upgrade(_config(connection), revision)


def downgrade(bind: Engine | Connection, revision: str = "-1") -> None:
    if revision in {"base", BASELINE_REVISION, "-1"}:
        raise RuntimeError("destructive Phase 1 migration downgrade is unsupported")
    if isinstance(bind, Connection):
        command.downgrade(_config(bind), revision)
        return
    with bind.begin() as connection:
        command.downgrade(_config(connection), revision)


def stamp(bind: Engine | Connection, revision: str = BASELINE_REVISION) -> None:
    if isinstance(bind, Connection):
        command.stamp(_config(bind), revision)
        return
    with bind.begin() as connection:
        command.stamp(_config(connection), revision)


def is_empty_database(bind: Engine | Connection) -> bool:
    signature = inspect_schema(bind)
    return not any(name != "alembic_version" for name in signature.tables)


def sqlite_database_path(bind: Engine) -> Path | None:
    url = make_url(str(bind.url))
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()
