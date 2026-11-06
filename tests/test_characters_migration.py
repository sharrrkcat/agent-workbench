"""The identity reset keeps independent catalogs and files intact."""

import json

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import Session

from ai_workbench.api.main import create_app
from ai_workbench.core.models.schema import ModelProfile, ProviderProfile
from ai_workbench.core.models.store import ModelProfileStore, ProviderProfileStore
from ai_workbench.core.schema.character import COGITA_CHARACTER_ID
from ai_workbench.core.schema.persona import USER_PERSONA_ID
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import AppMetadataRecord, KnowledgeBaseRecord, WorldbookRecord, ContextCheckpointRecord, ContextRetrievalRecord
from ai_workbench.db.qq_models import QQMediaAsset
from tests.migration_fixtures import insert_historical_row


def test_identity_reset_preserves_catalogs_assets_files_and_repeat_startup(tmp_path):
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    engine = get_engine(url)
    migrations.upgrade(engine, migrations.QQ_TIMELINE_REVISION)
    provider = ProviderProfileStore(engine).create(ProviderProfile(name="Keep provider", connection={"base_url": "http://provider.test/v1"}))
    model = ModelProfileStore(engine).create(ModelProfile(name="Keep model", alias="keep", kind="llm",
        model_ref="manual", source={"type": "provider", "provider_profile_id": provider.id}))
    with Session(engine) as db:
        db.add(AppMetadataRecord(key="sentinel", value="preserved"))
        db.add(AppMetadataRecord(key="model_settings", value=json.dumps({"default_model_profile_id": model.id})))
        db.add(KnowledgeBaseRecord(id="base", name="Keep", embedding_model_profile_id=model.id))
        db.add(WorldbookRecord(id="book", name="Keep"))
        db.add(QQMediaAsset(sha256="a" * 64, attachment_json="{}", description="Keep shared asset", is_favorite=True))
        insert_historical_row(db, "projects", id="qq", name="Old bot", kind="qqbot")
        insert_historical_row(db, "sessionrecord", session_id="old", kind="qqbot", project_id="qq")
        insert_historical_row(db, "runrecord", run_id="old", session_id="old", kind="chat", persona_id="", status="DONE")
        insert_historical_row(db, "qq_bindings", session_id="old", project_id="qq", target_kind="group", target_id="123")
        insert_historical_row(db, "qq_batches", id=1, session_id="old", project_id="qq", status="done", text="old", created_at=1)
        insert_historical_row(db, "qq_notifications", project_id="qq", source_session_id="old", event_key="old",
            kind="test", error_code="test", created_at=1, last_at=1, occurrences=1, cancelled=False)
        db.add(ContextCheckpointRecord(session_id="old", checkpoint_json="{}"))
        db.add(ContextRetrievalRecord(session_id="old", state_json="{}"))
        db.commit()
    kept = ("model_profiles", "provider_profiles", "appmetadatarecord", "knowledge_bases", "worldbooks", "qq_media_assets")
    def rows():
        with engine.connect() as db:
            return {table: db.exec_driver_sql(f'SELECT * FROM "{table}"').all() for table in kept}
    before = rows()
    files = [tmp_path / "data" / folder / "keep.bin" for folder in ("models", "attachments", "runtimes", "knowledge", "logs")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"user owned")
    stamps = {path: path.stat().st_mtime_ns for path in files}
    migrations.upgrade(engine)
    signature = migrations.inspect_schema(engine)
    migrations.upgrade(engine)
    assert migrations.inspect_schema(engine) == signature and rows() == before
    assert not {"projects", "project_knowledge_bindings", "persona_knowledge_bindings", "session_knowledge_bindings"}.intersection(signature.tables)
    assert "character_id" in signature.columns["sessionrecord"] and "project_id" not in signature.columns["qq_bindings"]
    assert next(c for c in inspect(engine).get_columns("sessionrecord") if c["name"] == "character_id")["nullable"] is False
    with engine.connect() as db:
        for table in ("sessionrecord", "runrecord", "messagerecord", "context_checkpoints", "context_retrieval",
                      "qq_bindings", "qq_batches", "qq_notifications", "qq_deliveries"):
            assert db.exec_driver_sql(f'SELECT count(*) FROM "{table}"').scalar() == 0
        assert db.exec_driver_sql("SELECT id, name, background FROM personas").all() == [(USER_PERSONA_ID, "User", "")]
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()
    for attempt in range(2):
        with TestClient(create_app(root=tmp_path, database_url=url)) as client:
            owner, = client.get("/api/characters").json()
            assert owner["id"] == COGITA_CHARACTER_ID and owner["model_profile_id"] == model.id
            assert owner["system_prompt"] == ""
            assert owner["name"] == ("Cogita" if attempt == 0 else "Edited")
            assert client.patch(f"/api/characters/{owner['id']}", json={"name": "Edited"}).status_code == 200
    assert all(path.read_bytes() == b"user owned" and path.stat().st_mtime_ns == stamps[path] for path in files)
