from tests.migration_fixtures import insert_historical_row, historical_row
"""Historical identity schema transitions, queried at their pinned revisions."""
import json
import hashlib
from pathlib import Path
import pytest
from sqlalchemy.exc import IntegrityError
from ai_workbench.db.stores import SqlAppSettingsStore
from ai_workbench.core.settings import AppSettings
from sqlalchemy import inspect, text
from sqlmodel import Session as DbSession
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import *
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.schema.character import COGITA_CHARACTER_ID
from ai_workbench.core.schema.persona import USER_PERSONA_ID
from tests.migration_fixtures import insert_pre_request_options_model

def test_project_migration_preserves_resources_and_files_and_is_repeatable(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    migrations.upgrade(engine, migrations.PERSONA_COLLECTIONS_REVISION)
    profile = insert_pre_request_options_model(engine, ModelProfile(name="Keep", alias="keep", kind="embedding", model_ref="manual"))
    with DbSession(engine) as db:
        db.add(AppMetadataRecord(key="sentinel", value="preserved"))
        db.add(KnowledgeBaseRecord(id="base", name="Keep", embedding_model_profile_id=profile.id))
        db.add(WorldbookRecord(id="book", name="Keep"))
        db.add(RuntimeInstallationRecord(id="local", version="1.0.0", state="installed"))
        db.commit()
    with engine.begin() as db:
        db.execute(text("""INSERT INTO sessionrecord (session_id, title, persona_id, context_policy_json, generation_json,
            harness_enabled, tools_allowed_json, title_generation_state, title_generation_metadata_json, created_at, updated_at)
            VALUES ('old', 'Old', :persona, '{"mode":"session"}', '{}', 0, '[]', 'pending', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""),
            {"persona": COGITA_CHARACTER_ID})
    tables = ("personas", "model_profiles", "provider_profiles", "knowledge_bases", "worldbooks", "runtime_installations", "appmetadatarecord")
    def rows():
        with engine.connect() as db:
            return {name: db.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall() for name in tables}
    before = rows()
    files = [tmp_path / "data" / folder / "keep.bin" for folder in ("models", "attachments", "runtimes", "knowledge", "logs")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"owned file")
    migrations.upgrade(engine, migrations.PROJECTS_REVISION)
    assert rows() == before and all(path.read_bytes() == b"owned file" for path in files)
    schema = migrations.inspect_schema(engine)
    assert {"projects", "project_knowledge_bindings", "project_worldbook_bindings"} <= set(schema.tables)
    with engine.connect() as db:
        assert db.exec_driver_sql("SELECT count(*) FROM sessionrecord").scalar() == 0
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    migrations.upgrade(engine, migrations.PROJECTS_REVISION)
    assert migrations.inspect_schema(engine) == schema and rows() == before
    engine.dispose()

def test_persona_revision_resets_only_affected_state_and_keeps_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    migrations.upgrade(engine, migrations.DIRECTORY_MODELS_REVISION)
    profile = insert_pre_request_options_model(engine, ModelProfile(name="Keep model", alias="keep", kind="embedding", model_ref="manual"))
    old_persona = "00000000-0000-4000-8000-000000000001"
    with engine.begin() as db:
        db.execute(text("""INSERT INTO sessionrecord
            (session_id, title, context_mode, current_persona_id, context_policy_json, generation_json,
             harness_enabled, tools_allowed_json, title_generation_state, title_generation_metadata_json, created_at, updated_at)
            VALUES ('old', 'Old', 'group_transcript', :persona, '{}', :generation, 0, '[]', 'pending', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""), {"persona": old_persona, "generation": '{"seed":5}'})
        db.execute(text("INSERT INTO session_personas VALUES ('old', :persona, 0, 1)"), {"persona": old_persona})
    with DbSession(engine) as db:
        db.add(AppMetadataRecord(key="app_settings", value='{"core_memory_content":"Discard","core_memory_enabled":false}'))
        db.add(AppMetadataRecord(key="sentinel", value="preserved"))
        db.add(KnowledgeBaseRecord(id="base", name="Keep", embedding_model_profile_id=profile.id))
        db.add(WorldbookRecord(id="book", name="Keep"))
        db.add(RuntimeInstallationRecord(id="local", version="1.0.0", state="installed", manifest_sha256="a" * 64))
        db.add(MessageRecord(message_id="message", session_id="old", role="user"))
        insert_historical_row(db, "runrecord", run_id="run", session_id="old", persona_id=old_persona, kind="chat", status="WAITING_FOR_USER",
                         config_snapshot_json='{"old":true}', harness_state_json='{"old":true}')
        db.commit()
    affected = {"personas", "sessionrecord", "session_personas", "session_worldbook_bindings", "persona_knowledge_bindings",
                "persona_worldbook_bindings", "session_knowledge_bindings", "messagerecord", "runrecord", "runsteprecord", "runeventrecord", "appmetadatarecord", "alembic_version"}
    def preserved_rows():
        with engine.connect() as db:
            return {name: db.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall()
                    for name in migrations.inspect_schema(engine).tables if name not in affected}
    before = preserved_rows()
    files = [tmp_path / "data" / folder / "keep.bin" for folder in ("models", "attachments", "runtimes", "knowledge", "logs", "pet")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"owned file")
    before_files = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
    migrations.upgrade(engine, migrations.PERSONA_COLLECTIONS_REVISION)
    schema = migrations.inspect_schema(engine)
    assert not {"session_personas", "session_worldbook_bindings"}.intersection(schema.tables)
    assert not {"context_mode", "current_persona_id"}.intersection(schema.columns["sessionrecord"])
    assert "persona_id" in schema.columns["sessionrecord"]
    assert preserved_rows() == before
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files} == before_files
    assert SqlAppSettingsStore(engine).get() == AppSettings()
    with engine.connect() as db:
        assert db.execute(text("SELECT name, collection FROM personas ORDER BY name")).all() == [("Cogita", "agent"), ("User", "user")]
        assert db.execute(text("SELECT system_prompt FROM personas WHERE id=:id"), {"id": USER_PERSONA_ID}).scalar() == ""
    with engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert db.exec_driver_sql("SELECT value FROM appmetadatarecord WHERE key='sentinel'").scalar() == "preserved"
        for table in ("sessionrecord", "messagerecord", "runrecord"):
            assert db.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar() == 0
    with pytest.raises(IntegrityError), engine.begin() as db:
        db.execute(text("""INSERT INTO personas VALUES ('extra', 'user', 'Extra', NULL, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""))
    with engine.begin() as db:
        db.execute(text("UPDATE personas SET name='Edited' WHERE id=:id"), {"id": COGITA_CHARACTER_ID})
    migrations.upgrade(engine, migrations.PERSONA_COLLECTIONS_REVISION)
    assert migrations.inspect_schema(engine) == schema
    with engine.connect() as db:
        assert db.execute(text("SELECT name FROM personas WHERE id=:id"), {"id": COGITA_CHARACTER_ID}).scalar() == "Edited"
    engine.dispose()

def test_configuration_revision_discards_chat_only_and_preserves_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.PHASE5_REVISION)
    with engine.begin() as db:
        db.execute(text("""INSERT INTO sessionrecord
            (session_id, title, context_mode, current_persona_id, knowledge_binding_mode,
             worldbook_binding_mode, title_generation_state, title_generation_metadata_json, created_at, updated_at)
            VALUES ('old', '', 'single_assistant', :persona, 'inherit', 'override', 'pending', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""),
            {"persona": "00000000-0000-4000-8000-000000000001"})
        db.execute(text("INSERT INTO session_personas VALUES ('old', :persona, 0, 1)"), {"persona": "00000000-0000-4000-8000-000000000001"})
        db.exec_driver_sql("""INSERT INTO model_profiles
            (id,alias,name,kind,model_ref,capabilities_json,parameters_json,lifecycle_json,
             enabled,external_enabled,created_at,updated_at)
            VALUES ('model','model','Model','embedding','manual','{}','{}','{}',1,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""")
    with DbSession(engine) as db:
        db.add(AppMetadataRecord(key="app_settings", value='{"core_memory_content":"Keep"}'))
        db.add(KnowledgeBaseRecord(id="base", name="Keep", embedding_model_profile_id="model"))
        db.add(WorldbookRecord(id="book", name="Keep"))
        insert_historical_row(db, "runrecord", run_id="run", session_id="old", persona_id="00000000-0000-4000-8000-000000000001", kind="chat", status="WAITING_FOR_USER",
                         config_snapshot_json='{"model_source":"persona"}', harness_state_json='{"old":true}')
        db.add(MessageRecord(message_id="message", session_id="old", role="user"))
        db.execute(RunStepRecord.__table__.insert(), RunStepRecord(
            step_id="step", run_id="run", kind="approval", status="running").model_dump(exclude={"context_snapshot_json"}))
        db.add(RunEventRecord(event_id="event", run_id="run", session_id="old", type="approval_requested"))
        db.commit()
    affected = {"personas", "sessionrecord", "session_personas", "persona_knowledge_bindings", "persona_worldbook_bindings",
                "session_knowledge_bindings", "session_worldbook_bindings", "messagerecord", "runrecord", "runsteprecord", "runeventrecord"}
    def unrelated_rows():
        with engine.connect() as db:
            return {name: db.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall()
                    for name in inspect(engine).get_table_names() if name not in affected | {"alembic_version"}}
    before_rows = unrelated_rows()
    files = [tmp_path / "data" / folder / "keep.bin" for folder in ("models", "runtimes", "attachments", "knowledge", "pet", "logs")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"owned file")
    before_files = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
    migrations.upgrade(engine, migrations.CHAT_CONFIGURATION_REVISION)
    assert unrelated_rows() == before_rows
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files} == before_files
    schema = migrations.inspect_schema(engine)
    assert set(schema.columns["personas"]) == {"id", "name", "avatar_attachment_id", "system_prompt", "created_at", "updated_at"}
    assert not {"knowledge_binding_mode", "worldbook_binding_mode"}.intersection(schema.columns["sessionrecord"])
    with engine.connect() as db:
        assert db.exec_driver_sql("SELECT name FROM personas ORDER BY name").scalars().all() == ["Chat", "Translate"]
        assert all(db.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar() == 0 for name in affected - {"personas"})
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    migrations.upgrade(engine, migrations.CHAT_CONFIGURATION_REVISION)
    assert migrations.inspect_schema(engine) == schema and unrelated_rows() == before_rows
    engine.dispose()

def test_migration_seeds_and_discards_only_chat_rows(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.PHASE2B_REVISION)
    with engine.begin() as db:
        db.execute(text("INSERT INTO sessionrecord (session_id,title,context_mode,title_generation_state,title_generation_metadata_json,created_at,updated_at) VALUES ('old','old','single_assistant','pending','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO appmetadatarecord (key,value,updated_at) VALUES ('sentinel','preserved',CURRENT_TIMESTAMP)"))
    with DbSession(engine) as db:
        db.add(MessageRecord(message_id="old-message", session_id="old", role="user"))
        db.commit()
    files = [tmp_path / f"data/{kind}/keep.bin" for kind in ("models", "attachments", "runtimes")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(path.name.encode())
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    migrations.upgrade(engine, migrations.PHASE3_REVISION)
    with engine.connect() as db:
        seeds = db.execute(text("SELECT id,name,context_policy_json FROM personas ORDER BY name")).all()
        assert [row.name for row in seeds] == ["Chat", "Translate"]
        assert [row.id for row in seeds] == ["00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"]
        assert json.loads(seeds[1].context_policy_json)["mode"] == "current_message"
        assert db.execute(text("SELECT count(*) FROM sessionrecord")).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM messagerecord")).scalar() == 0
        assert db.execute(text("SELECT value FROM appmetadatarecord WHERE key='sentinel'")).scalar() == "preserved"
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files} == before
    schema = migrations.inspect_schema(engine).as_dict()
    migrations.upgrade(engine, migrations.PHASE3_REVISION)
    assert migrations.inspect_schema(engine).as_dict() == schema
    assert "target" not in schema["columns"]["runrecord"]
    assert "config_snapshot_json" in schema["columns"]["runrecord"]
    assert len(inspect(engine).get_foreign_keys("session_personas")) == 2
    source = Path("alembic/versions/0005_phase3_personas.py").read_text()
    assert "import ai_workbench" not in source and "SQLModel.metadata" not in source
    with pytest.raises(RuntimeError, match="unsupported"):
        migrations.downgrade(engine, migrations.PHASE2B_REVISION)
    engine.dispose()

