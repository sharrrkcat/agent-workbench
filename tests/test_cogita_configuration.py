"""Configuration cutover, fresh database selection and launcher boundaries."""
import os
import sys

import pytest

from ai_workbench.api.main import _resolve_frontend_dist
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


def test_launcher_passes_cogita_frontend_to_preserved_python_entrypoint(tmp_path, monkeypatch):
    dist = tmp_path / "frontend/dist"
    dist.mkdir(parents=True)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(run_app, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_app.py", "--no-open"])
    monkeypatch.setattr(run_app, "ensure_port_available", lambda host, port: None)
    monkeypatch.setenv("COGITA_FRONTEND_DIST", str(tmp_path / "previous"))
    calls = []
    monkeypatch.setattr(run_app.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    run_app.main()
    assert os.environ["COGITA_FRONTEND_DIST"] == str(dist)
    assert calls == [("ai_workbench.api.main:app", {
        "host": "127.0.0.1", "port": 8765, "reload": False, "factory": False,
    })]
