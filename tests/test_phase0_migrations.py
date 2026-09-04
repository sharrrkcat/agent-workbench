from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlmodel import Session as DbSession

from ai_workbench.db import migrations
from ai_workbench.db import database
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.db.models import AppMetadataRecord, MessageRecord, SessionRecord


def _engine(path: Path):
    return get_engine(f"sqlite:///{path}")


def _dispose(engine) -> None:
    engine.dispose()


def _drop_objects(path: Path, *objects: str) -> None:
    connection = sqlite3.connect(path)
    try:
        for name in objects:
            if name.startswith("ix_"):
                connection.execute(f'DROP INDEX IF EXISTS "{name}"')
            elif name in {"content_json", "output_type", "kind"}:
                table = "messagerecord" if name in {"content_json", "output_type"} else "runrecord"
                connection.execute(f'ALTER TABLE "{table}" DROP COLUMN "{name}"')
            else:
                connection.execute(f'DROP TABLE IF EXISTS "{name}"')
        connection.commit()
    finally:
        connection.close()


def test_empty_database_uses_static_baseline_and_is_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "empty.db")
    try:
        init_db(engine)
        signature = migrations.inspect_schema(engine)
        assert set(migrations.CRITICAL_TABLES) <= set(signature.tables)
        assert len(migrations.BASELINE_INDEXES) == 46
        assert set(name for name, _ in migrations.BASELINE_INDEXES) <= set(signature.indexes)
        assert "kb_chunk_fts" in signature.virtual_tables
        assert {"content_json", "output_type"} <= set(signature.columns["messagerecord"])
        assert migrations.current_revision(engine) == migrations.BASELINE_REVISION
        with DbSession(engine) as session:
            assert session.get(AppMetadataRecord, "schema_version").value == "1"

        before = signature
        init_db(engine)
        assert migrations.inspect_schema(engine) == before
        assert migrations.current_revision(engine) == migrations.BASELINE_REVISION
    finally:
        _dispose(engine)


def test_baseline_does_not_call_sqlmodel_create_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path / "static.db")
    try:
        monkeypatch.setattr(
            "sqlmodel.SQLModel.metadata.create_all",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("create_all used")),
        )
        # Calling the migration helper directly exercises the static revision,
        # independent of the legacy compatibility path in init_db.
        migrations.upgrade(engine)
        assert migrations.current_revision(engine) == migrations.BASELINE_REVISION
        migrations.validate_baseline_compatibility(engine)
    finally:
        _dispose(engine)


def test_versioned_database_does_not_fall_back_to_create_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path / "versioned.db")
    try:
        init_db(engine)
        monkeypatch.setattr(
            "sqlmodel.SQLModel.metadata.create_all",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("create_all used")),
        )
        init_db(engine)
        assert migrations.current_revision(engine) == migrations.BASELINE_REVISION
    finally:
        _dispose(engine)


def test_future_revision_is_not_rejected_for_removing_legacy_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path / "future.db")
    try:
        init_db(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE capabilityconfigrecord")
            connection.exec_driver_sql(
                "UPDATE alembic_version SET version_num = '0002_future'"
            )
        monkeypatch.setattr(database.migrations, "upgrade", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            database.migrations,
            "validate_baseline_compatibility",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("baseline validation used for future revision")
            ),
        )
        init_db(engine)
        assert migrations.current_revision(engine) == "0002_future"
    finally:
        _dispose(engine)


def test_legacy_database_is_backed_up_bootstrapped_and_stamped_without_row_loss(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    engine = _engine(path)
    try:
        # Seed a complete schema, then make it resemble the deployed,
        # unversioned schema: remove the revision marker, five newer indexes,
        # and the two historical message columns.
        migrations.upgrade(engine)
        with DbSession(engine) as session:
            session.add(SessionRecord(session_id="session-1"))
            session.add(
                MessageRecord(
                    message_id="message-1",
                    session_id="session-1",
                    role="user",
                    content_json='"hello"',
                    output_type="text",
                )
            )
            session.commit()
        _dispose(engine)
        _drop_objects(
            path,
            "alembic_version",
            "ix_embedding_model_profiles_provider_profile_id",
            "ix_llm_profiles_provider_profile_id",
            "ix_kb_sources_origin_id",
            "ix_kb_sources_file_status",
            "ix_session_knowledge_bindings_sort_order",
            "content_json",
            "output_type",
        )

        engine = _engine(path)
        init_db(engine)
        assert migrations.current_revision(engine) == migrations.BASELINE_REVISION
        migrations.validate_baseline_compatibility(engine)
        with DbSession(engine) as session:
            assert session.exec(select(func.count()).select_from(SessionRecord)).one()[0] == 1
            assert session.exec(select(func.count()).select_from(MessageRecord)).one()[0] == 1
            row = session.get(MessageRecord, "message-1")
            assert row is not None
            assert row.content_json is None or row.content_json == ""
        backups = sorted((tmp_path / "backups" / "database").glob("legacy.pre-baseline-*.db"))
        manifests = sorted((tmp_path / "backups" / "database").glob("legacy.pre-baseline-*.json"))
        assert len(backups) == 1
        assert len(manifests) == 1
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        assert manifest["integrity_check"] == "ok"
        assert manifest["critical_row_counts"]["sessionrecord"] == 1
        assert manifest["critical_row_counts"]["messagerecord"] == 1
    finally:
        _dispose(engine)


def test_schema_mismatch_is_not_stamped(tmp_path: Path) -> None:
    path = tmp_path / "mismatch.db"
    engine = _engine(path)
    try:
        migrations.upgrade(engine)
        _dispose(engine)
        _drop_objects(path, "alembic_version", "kind")
        engine = _engine(path)
        with pytest.raises(migrations.SchemaMismatchError) as error:
            init_db(engine)
        assert "runrecord:kind" in str(error.value)
        assert not migrations.has_alembic_version(engine)
        assert list((tmp_path / "backups" / "database").glob("*.db"))
    finally:
        _dispose(engine)


def test_backup_failure_prevents_legacy_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "backup-failure.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE appmetadatarecord (\"key\" VARCHAR PRIMARY KEY, value VARCHAR NOT NULL, updated_at DATETIME NOT NULL)")
        connection.commit()
    finally:
        connection.close()
    engine = _engine(path)
    try:
        monkeypatch.setattr(database.migrations, "backup_sqlite_database", lambda *args, **kwargs: None)
        with pytest.raises(RuntimeError, match="DATABASE_BACKUP_REQUIRED"):
            init_db(engine)
        assert not migrations.has_alembic_version(engine)
        assert "sessionrecord" not in migrations.inspect_schema(engine).tables
    finally:
        _dispose(engine)


def test_upgrade_downgrade_upgrade_for_disposable_database(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "roundtrip.db")
    try:
        migrations.upgrade(engine)
        assert migrations.current_revision(engine) == migrations.BASELINE_REVISION
        migrations.downgrade(engine, "base")
        assert migrations.is_empty_database(engine)
        migrations.upgrade(engine)
        assert migrations.current_revision(engine) == migrations.BASELINE_REVISION
        migrations.validate_baseline_compatibility(engine)
    finally:
        _dispose(engine)
