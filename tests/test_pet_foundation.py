import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlmodel import Session

from ai_workbench.api.main import create_app
from ai_workbench.core.settings import AppSettings
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import AppMetadataRecord, ModelProfileRecord, PersonaRecord, RunRecord
from ai_workbench.db.stores import SqlAppSettingsStore


@pytest.mark.parametrize("use_memory", [True, False])
def test_position_api_is_strict_shared_and_has_no_package_flow(tmp_path, use_memory):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>Workbench</html>")
    legacy = tmp_path / "data/pet/existing"
    legacy.mkdir(parents=True)
    (legacy / "pet.json").write_text('{"name":"Unused"}')
    (legacy / "spritesheet.webp").write_bytes(b"Unused bytes")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in legacy.iterdir()}
    app = create_app(root=tmp_path, use_memory=use_memory,
                     database_url=f"sqlite:///{tmp_path / 'app.db'}", frontend_dist=frontend)
    with TestClient(app) as client:
        initial = client.get("/api/pets/settings").json()
        assert initial == {"settings": {"position": {"mode": "default", "x": None, "y": None}}}
        first = client.patch("/api/pets/settings", json={"values": {"position": {"mode": "custom", "x": 120}}})
        assert first.status_code == 200
        second = client.patch("/api/settings/general", json={"pet": {"position": {"y": 230}}})
        assert second.status_code == 200
        expected = {"settings": {"position": {"mode": "custom", "x": 120, "y": 230}}}
        assert client.get("/api/pets/settings").json() == expected
        assert second.json()["pet"] == expected["settings"]
        assert client.patch("/api/pets/settings", json={"values": {}}).json() == expected
        removed = {
            "pet_enabled": True, "default_pet_id": "existing", "pet_scale": 1,
            "show_status_bubble": True, "bubble_offset_x": 0, "bubble_offset_y": 0,
            "jump_on_hover": True, "running_prefix": "Working", "bubble_texts": {},
        }
        for field, value in removed.items():
            assert client.patch("/api/pets/settings", json={"values": {field: value}}).status_code == 422
            assert client.patch("/api/settings/general", json={"pet": {field: value}}).status_code == 422
        for value in (None, {"mode": None}, {"mode": "unknown"}, {"x": 20001}, {"y": -20001},
                      {"x": "12"}, {"x": True}, {"y": 1.5}, {"z": 1}):
            assert client.patch("/api/pets/settings", json={"values": {"position": value}}).status_code == 422
        assert client.get("/api/pets/settings").json() == expected
        for method, path in (("GET", "/api/pets"), ("POST", "/api/pets/scan"), ("POST", "/api/pets/import"),
                             ("DELETE", "/api/pets/existing"), ("GET", "/api/pets/existing/spritesheet.webp")):
            response = client.request(method, path)
            assert response.status_code == 404, (method, path, response.status_code)
        paths = client.get("/openapi.json").json()["paths"]
        assert [path for path in paths if path.startswith("/api/pets")] == ["/api/pets/settings"]
        assert client.post("/api/pets/settings", json={}).status_code == 405
        assert client.post("/api/unknown").status_code == 404
        assert client.get("/settings?tab=general").status_code == 200
        assert not hasattr(app.state.runtime_state, "pet_service")
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in legacy.iterdir()} == before


def test_pet_revision_resets_settings_only_and_new_position_survives_restart(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.CHAT_CONFIGURATION_REVISION)
    with Session(engine) as db:
        db.add(AppMetadataRecord(key="app_settings", value=json.dumps({"core_memory_content": "Disposable",
            "pet": {"pet_enabled": True, "default_pet_id": "old", "bubble_texts": {"done": "Done"}}})))
        db.add(AppMetadataRecord(key="model_settings", value='{"external_enabled":false}'))
        db.add(ModelProfileRecord(id="model", name="Model", alias="model", kind="llm", model_ref="manual"))
        db.add(PersonaRecord(id="persona", name="Keep", system_prompt="Keep"))
        db.add(RunRecord(run_id="run", kind="chat", session_id="session", persona_id="persona", status="DONE"))
        db.commit()
    def preserved_rows():
        with engine.connect() as db:
            return {name: db.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall()
                    for name in inspect(engine).get_table_names() if name not in {"alembic_version", "appmetadatarecord"}}
    files = [tmp_path / "data" / folder / "keep.bin" for folder in ("models", "runtimes", "attachments", "pet", "knowledge")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"preserved")
    before_files = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
    before_rows = preserved_rows()
    before_schema = migrations.inspect_schema(engine)
    migrations.upgrade(engine)
    assert migrations.current_revision(engine) == migrations.PET_FOUNDATION_REVISION
    assert migrations.inspect_schema(engine) == before_schema
    assert preserved_rows() == before_rows
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files} == before_files
    with Session(engine) as db:
        assert db.get(AppMetadataRecord, "app_settings") is None
        assert db.get(AppMetadataRecord, "model_settings").value == '{"external_enabled":false}'
    store = SqlAppSettingsStore(engine)
    assert store.get() == AppSettings()
    store.patch({"core_memory_content": "New", "pet": {"position": {"mode": "custom", "x": 88, "y": 99}}})
    migrations.upgrade(engine)
    reloaded = SqlAppSettingsStore(engine).get()
    assert reloaded.core_memory_content == "New"
    assert reloaded.pet.position.model_dump() == {"mode": "custom", "x": 88, "y": 99}
    engine.dispose()
