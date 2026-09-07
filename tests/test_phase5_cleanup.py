from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlmodel import Session

from ai_workbench.api.main import create_app
from ai_workbench.core.settings import AppSettings
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import AppMetadataRecord, ModelProfileRecord, ProviderProfileRecord
from ai_workbench.db.stores import SqlAppSettingsStore
from scripts import build_portable


def business_rows(engine):
    with engine.connect() as connection:
        return {
            name: connection.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall()
            for name in inspect(engine).get_table_names()
            if name not in {"alembic_version", "appmetadatarecord"}
        }


def test_settings_revision_resets_only_application_json_and_preserves_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    migrations.upgrade(engine, migrations.PHASE4_REVISION)
    with Session(engine) as db:
        db.add(AppMetadataRecord(key="app_settings", value=json.dumps({
            "appearance_font_ui_family": "Retired", "resource_status_panel_enabled": True,
            "core_memory_content": "Disposable", "pet": {"pet_scale": 2},
        })))
        db.add(AppMetadataRecord(key="models", value='{"external_enabled":false}'))
        db.add(ProviderProfileRecord(id="p", name="Connection", base_url="http://localhost:1234/v1"))
        db.add(ModelProfileRecord(id="m", alias="local", name="Model", kind="llm", model_ref="manual"))
        db.commit()
    protected = [tmp_path / "data" / directory / "keep.bin" for directory in
                 ("models", "runtimes", "attachments", "knowledge", "assets/fonts", "logs")]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"owned file")
    before_files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in protected}
    before_schema = migrations.inspect_schema(engine)
    before_rows = business_rows(engine)

    migrations.upgrade(engine)

    assert migrations.current_revision(engine) == migrations.PHASE5_REVISION
    assert migrations.inspect_schema(engine) == before_schema
    assert business_rows(engine) == before_rows
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in protected} == before_files
    with Session(engine) as db:
        assert db.get(AppMetadataRecord, "app_settings") is None
        assert db.get(AppMetadataRecord, "models").value == '{"external_enabled":false}'
    store = SqlAppSettingsStore(engine)
    assert store.get() == AppSettings()
    store.patch({"core_memory_content": "New setting"})
    migrations.upgrade(engine)
    assert store.get().core_memory_content == "New setting"
    engine.dispose()


@pytest.mark.parametrize("use_memory", [True, False])
def test_removed_display_fields_and_fonts_leave_current_settings_and_resources(tmp_path, use_memory):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>Workbench</html>", encoding="utf-8")
    app = create_app(root=tmp_path, use_memory=use_memory,
                     database_url=f"sqlite:///{tmp_path / 'app.db'}", frontend_dist=frontend)
    with TestClient(app) as client:
        settings = client.get("/api/settings/general").json()
        assert not any(key.startswith(("appearance_font_", "resource_status_")) for key in settings)
        removed = [f"appearance_font_{target}_{field}" for target in ("ui", "message", "code")
                   for field in ("family", "source", "system_name", "custom_id", "custom_family_id")]
        removed += [f"resource_status_{field}" for field in (
            "panel_enabled", "show_cpu", "show_ram", "show_gpu", "show_vram",
            "ram_display_mode", "vram_display_mode", "show_tokens",
        )]
        for field in removed:
            response = client.patch("/api/settings/general", json={field: "retired"})
            assert response.status_code == 422, field
        for path in ("/api/assets/fonts", "/api/assets/fonts/example", "/api/assets/font-families/example/font.woff2"):
            assert client.get(path).status_code == 404
        assert not (tmp_path / "data/assets/fonts").exists()
        response = client.patch("/api/settings/general", json={"core_memory_content": "Remember"})
        assert response.status_code == 200
        assert response.json()["core_memory_content"] == "Remember"
        assert client.get("/api/runtime/resources").status_code == 200
        assert "memory" in client.get("/api/runtime/resources").json()
        first = client.patch("/api/pets/settings", json={"values": {"position": {"mode": "custom", "x": 123}}})
        second = client.patch("/api/pets/settings", json={"values": {"position": {"y": 456}}})
        assert first.status_code == second.status_code == 200
        assert second.json()["settings"]["position"] == {"mode": "custom", "x": 123, "y": 456}


def test_portable_package_copies_maintained_guide_and_excludes_local_data(tmp_path, monkeypatch):
    root = tmp_path / "source"
    for name in ("ai_workbench", "alembic", "docs", "scripts", "frontend/dist/assets", "data/models"):
        (root / name).mkdir(parents=True)
    for name in ("pyproject.toml", "uv.lock", "README.md", "README_RUN.md", "alembic.ini", ".env.example",
                 "scripts/run_app.py", "frontend/dist/index.html", "docs/example.md"):
        (root / name).write_text(name, encoding="utf-8")
    (root / "data/models/weights").write_text("weights", encoding="utf-8")
    (root / ".env").write_text("private", encoding="utf-8")
    monkeypatch.setattr(build_portable, "project_root", lambda: root)
    monkeypatch.setattr(build_portable, "run_frontend_build", lambda _: None)
    monkeypatch.setattr(build_portable, "parse_args", lambda: type("Args", (), {"zip": True})())

    build_portable.main()

    output = root / "build" / build_portable.PORTABLE_NAME
    assert (output / "README_RUN.md").read_bytes() == (root / "README_RUN.md").read_bytes()
    assert (output / "docs/example.md").is_file()
    assert (output / "alembic.ini").is_file()
    assert not (output / ".env").exists()
    assert sorted(p.name for p in (output / "data").iterdir()) == [".gitkeep"]
    assert (root / "build" / f"{build_portable.PORTABLE_NAME}.zip").is_file()
    assert not (root / "dist").exists()
