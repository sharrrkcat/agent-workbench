"""Configuration cutover, fresh database selection and launcher boundaries."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import _resolve_frontend_dist, create_app
from ai_workbench.core.attachments import attachments_root
from ai_workbench.db.database import get_database_url, get_engine, init_db
from scripts import audit_workspace, reset_data, run_app


@pytest.mark.parametrize("suffix, resolve", [
    ("DATABASE_URL", get_database_url),
    ("ATTACHMENTS_DIR", lambda: str(attachments_root())),
    ("FRONTEND_DIST", lambda: str(_resolve_frontend_dist(None))),
])
def test_only_cogita_environment_overrides_are_read(tmp_path, monkeypatch, suffix, resolve):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COGITA_" + suffix, raising=False)
    default = resolve()
    monkeypatch.setenv("AGENT_WORKBENCH_" + suffix, str(tmp_path / "ignored"))
    assert resolve() == default
    configured = str(tmp_path / "configured")
    if suffix == "DATABASE_URL":
        configured = "sqlite:///" + configured + ".db"
    monkeypatch.setenv("COGITA_" + suffix, configured)
    assert resolve() == configured


def test_default_database_and_maintenance_leave_old_file_untouched(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COGITA_DATABASE_URL", raising=False)
    old = tmp_path / "data/agent_workbench.db"
    old.parent.mkdir()
    old.write_bytes(b"unselected database remains untouched")
    monkeypatch.setenv("AGENT_WORKBENCH_DATABASE_URL", "sqlite:///" + str(old))
    assert get_database_url() == "sqlite:///./data/cogita.db"
    engine = get_engine()
    try:
        init_db(engine)
    finally:
        engine.dispose()
    report = audit_workspace.audit(tmp_path)
    assert report.database_path == str(tmp_path / "data/cogita.db")
    assert report.database_exists and report.errors == ()
    monkeypatch.setattr(reset_data, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["reset_data.py"])
    assert reset_data.main() == 0
    assert "data/cogita.db" in capsys.readouterr().out
    assert old.read_bytes() == b"unselected database remains untouched"
    assert (tmp_path / "data/cogita.db").is_file()


def test_explicit_database_and_frontend_options_override_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("COGITA_DATABASE_URL", "sqlite:///environment.db")
    monkeypatch.setenv("COGITA_FRONTEND_DIST", str(tmp_path / "environment"))
    assert get_database_url("sqlite:///explicit.db") == "sqlite:///explicit.db"
    assert _resolve_frontend_dist(tmp_path / "explicit") == tmp_path / "explicit"


@pytest.mark.parametrize("arguments, host, browser_host", [
    ([], "0.0.0.0", "127.0.0.1"),
    (["--host", "0.0.0.0"], "0.0.0.0", "127.0.0.1"),
    (["--host", "127.0.0.1"], "127.0.0.1", "127.0.0.1"),
    (["--host", "localhost"], "localhost", "localhost"),
])
def test_launcher_binds_web_host_and_opens_concrete_browser_address(tmp_path, monkeypatch, arguments, host, browser_host):
    dist = tmp_path / "frontend/dist"
    dist.mkdir(parents=True)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(run_app, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_app.py", "--open", "--port", "8766", *arguments])
    monkeypatch.setattr(run_app, "ensure_port_available", lambda host, port: None)
    monkeypatch.setenv("COGITA_FRONTEND_DIST", str(tmp_path / "previous"))
    calls = []
    opened = []
    monkeypatch.setattr(run_app, "open_later", opened.append)
    monkeypatch.setattr(run_app.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    run_app.main()
    assert os.environ["COGITA_FRONTEND_DIST"] == str(dist)
    assert calls == [("ai_workbench.api.main:app", {
        "host": host, "port": 8766, "reload": False, "factory": False,
    })]
    assert opened == [f"http://{browser_host}:8766"]


def test_lan_web_and_events_are_available_but_public_inference_remains_local(tmp_path):
    dist = tmp_path / "frontend"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>Cogita</html>", encoding="utf-8")
    (dist / "assets/app.js").write_text("export {};", encoding="utf-8")
    app = create_app(root=tmp_path, use_memory=True, frontend_dist=dist)
    origin = "http://192.168.1.10:8765"
    with TestClient(app, base_url=origin, client=("192.168.1.20", 40000), headers={"Origin": origin}) as client:
        for path in ("/", "/new", "/settings", "/assets/app.js", "/api/settings/general"):
            assert client.get(path).status_code == 200
        session = client.post("/api/sessions", json={"title": "LAN chat"}).json()
        for path in ("/api/models/events", f"/api/ws/{session['session_id']}"):
            with client.websocket_connect(path) as websocket:
                websocket.send_json({"type": "ping"})
                assert websocket.receive_json() == {"type": "pong"}
        client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "test-key"}).raise_for_status()
        response = client.get("/v1/models", headers={"Authorization": "Bearer test-key"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "LOCALHOST_ONLY"
