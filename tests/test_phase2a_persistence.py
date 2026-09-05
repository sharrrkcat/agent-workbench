from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine

from ai_workbench.api.main import create_app
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine, init_db
from tests.model_fixtures import MockOpenAI, configure_model


def test_phase2a_recreates_all_test_data_and_matches_orm(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    migrations.upgrade(engine, migrations.PHASE1_REVISION)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO appmetadatarecord (key, value, updated_at) VALUES ('test', 'discard', CURRENT_TIMESTAMP)"))
    files = tmp_path / "data/models/llms/keep.gguf"
    files.parent.mkdir(parents=True)
    files.write_bytes(b"model")
    init_db(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM appmetadatarecord")).scalar() == 0
    assert files.read_bytes() == b"model"
    signature = migrations.inspect_schema(engine)
    assert migrations.current_revision(engine) == migrations.PHASE2A_REVISION
    assert "model_profiles" in signature.tables and "provider_profiles" in signature.tables
    assert not {"llm_profiles", "embedding_model_profiles", "vision_model_profiles", "multimodal_embedding_model_profiles"} & set(signature.tables)
    assert "model_profile_id" in signature.columns["sessionrecord"]
    assert "llm_profile_id" not in signature.columns["sessionrecord"]
    assert not any("last_announced" in c for c in signature.columns["sessionrecord"])
    expected = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(expected)
    for table in SQLModel.metadata.tables:
        columns = lambda bind: [{**column, "type": str(column["type"])} for column in inspect(bind).get_columns(table)]
        assert columns(engine) == columns(expected)
        assert inspect(engine).get_indexes(table) == inspect(expected).get_indexes(table)
        assert inspect(engine).get_foreign_keys(table) == inspect(expected).get_foreign_keys(table)
    before = signature.as_dict()
    init_db(engine)
    assert migrations.inspect_schema(engine).as_dict() == before
    with pytest.raises(RuntimeError, match="unsupported"):
        migrations.downgrade(engine, migrations.PHASE1_REVISION)
    engine.dispose()
    expected.dispose()


def test_unversioned_database_is_not_auto_stamped(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'unknown.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE arbitrary (id TEXT)"))
    with pytest.raises(RuntimeError, match="ALEMBIC_VERSION_REQUIRED"):
        init_db(engine)
    assert migrations.current_revision(engine) is None


def test_historical_phase1_ddl_does_not_import_current_orm():
    root = Path(__file__).resolve().parents[1]
    source = (root / "alembic/versions/0002_phase1_prune.py").read_text()
    assert "import ai_workbench.db.models" not in source
    assert "SQLModel.metadata" not in source


@pytest.mark.parametrize("memory", [False, True])
def test_unified_store_crud_references_and_secret_redaction(tmp_path, memory):
    upstream = MockOpenAI()
    app = create_app(use_memory=memory, database_url=f"sqlite:///{tmp_path / 'app.db'}", root=tmp_path, adapter_factory=upstream.factory)
    with TestClient(app) as client:
        profile = configure_model(client)
        provider_id = profile["provider_profile_id"]
        assert "provider-private-key" not in client.get("/api/models/providers").text
        assert client.get(f"/api/models/providers/{provider_id}").json()["has_api_key"]
        assert client.patch(f"/api/models/providers/{provider_id}", json={"name": "Renamed"}).status_code == 200
        assert app.state.runtime_state.provider_profiles.get(provider_id).api_key == "provider-private-key"
        assert client.post("/api/models/profiles", json={"kind": "embedding", "name": "dup", "alias": "local", "model_ref": "x"}).status_code == 409
        assert client.patch(f"/api/models/profiles/{profile['id']}", json={"kind": "vision"}).status_code == 409
        assert client.delete(f"/api/models/providers/{provider_id}").status_code == 409
        assert client.delete(f"/api/models/profiles/{profile['id']}").status_code == 409
        session = client.post("/api/sessions", json={"model_profile_id": profile["id"]}).json()
        client.patch("/api/models/settings", json={"default_model_profile_id": None})
        assert client.delete(f"/api/models/profiles/{profile['id']}").status_code == 409
        client.patch(f"/api/sessions/{session['session_id']}", json={"model_profile_id": None})
        assert client.delete(f"/api/models/profiles/{profile['id']}").status_code == 200
        assert client.delete(f"/api/models/providers/{provider_id}").status_code == 200


def test_sql_restart_preserves_only_current_configuration(tmp_path):
    url = f"sqlite:///{tmp_path / 'restart.db'}"
    upstream = MockOpenAI()
    with TestClient(create_app(database_url=url, root=tmp_path, adapter_factory=upstream.factory)) as client:
        profile = configure_model(client, kind="embedding", alias="embed")
        assert client.patch("/api/models/settings", json={"external_api_key": "test-key"}).status_code == 200
    with TestClient(create_app(database_url=url, root=tmp_path, adapter_factory=upstream.factory)) as client:
        assert client.get("/api/models/profiles").json()[0]["id"] == profile["id"]
        assert client.get("/api/models/settings").json()["has_external_api_key"]
        assert "test-key" not in client.get("/api/models/settings").text


@pytest.mark.parametrize("kind", ["reranker", "image_embedding", "vision"])
def test_pending_kinds_are_first_class_but_require_an_executable_backend(tmp_path, kind):
    with TestClient(create_app(use_memory=True, root=tmp_path)) as client:
        response = client.post("/api/models/profiles", json={"name": kind, "alias": kind, "kind": kind, "model_ref": "local/file"})
        assert response.status_code == 200, response.text
        profile = response.json()
        assert profile["lifecycle"]["unload"] == "manual"
        assert client.get(f"/api/models/profiles?kind={kind}").json()[0]["id"] == profile["id"]
        unavailable = client.post(f"/api/models/profiles/{profile['id']}/load")
        assert unavailable.status_code == 503
        assert unavailable.json()["error"]["code"] == "MODEL_UNAVAILABLE"
