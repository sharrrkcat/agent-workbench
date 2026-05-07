from pathlib import Path
import base64

from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.attachments import save_attachment_from_upload
from ai_workbench.core.settings import AppSettingsStore
from scripts.cleanup_attachments import main as cleanup_main
from tests.test_api import create_session
from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, run


TXT_DATA_URL = "data:text/plain;base64,aGVsbG8="


def test_general_settings_get_patch_validate_and_persist(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'settings.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))

    response = client.get("/api/settings/general")
    assert response.status_code == 200
    assert response.json()["max_file_size_mb"] == 10

    patched = client.patch("/api/settings/general", json={"max_file_size_mb": 20, "send_text_file_attachments_to_llm": False})
    assert patched.status_code == 200
    assert patched.json()["max_file_size_mb"] == 20
    assert patched.json()["send_text_file_attachments_to_llm"] is False

    assert client.patch("/api/settings/general", json={"unknown": 1}).status_code == 422
    assert client.patch("/api/settings/general", json={"max_file_size_mb": 0}).status_code == 422

    restarted = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))
    assert restarted.get("/api/settings/general").json()["max_file_size_mb"] == 20


def test_message_upload_limits_use_general_settings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    session = create_session(client)
    client.patch("/api/settings/general", json={"max_image_size_mb": 1, "max_file_size_mb": 1, "max_attachments_per_message": 1})
    large_payload = base64.b64encode(b"x" * (2 * 1024 * 1024)).decode("ascii")

    too_large_image = {
        "id": "image",
        "type": "image",
        "mime_type": "image/svg+xml",
        "name": "image.svg",
        "size": 2 * 1024 * 1024,
        "data_url": f"data:image/svg+xml;base64,{large_payload}",
    }
    image_response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "x", "attachments": [too_large_image]})
    assert image_response.status_code == 400
    assert "Maximum size is 1 MB" in image_response.json()["error"]["message"]

    too_large_file = {
        "id": "file",
        "type": "file",
        "mime_type": "text/plain",
        "name": "note.txt",
        "size": 2 * 1024 * 1024,
        "data_url": f"data:text/plain;base64,{large_payload}",
    }
    file_response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "x", "attachments": [too_large_file]})
    assert file_response.status_code == 400
    assert "Maximum size is 1 MB" in file_response.json()["error"]["message"]

    count_response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "x", "attachments": [{**too_large_file, "size": 5}, {**too_large_file, "id": "file-2", "size": 5}]},
    )
    assert count_response.status_code == 400
    assert "At most 1 attachments" in count_response.json()["error"]["message"]


def test_prompt_file_context_uses_general_settings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    llm = FakeLLMRuntime(response="ok")
    fixture = PromptRuntimeFixture(llm=llm)
    settings = AppSettingsStore()
    fixture.agent_runner.app_settings_store = settings
    session = fixture.sessions.create_session(default_agent_id="chat")
    first = save_attachment_from_upload("a.txt", "text/plain", b"a" * 2048)
    second = save_attachment_from_upload("b.txt", "text/plain", b"b" * 2048)

    settings.patch({"max_file_context_per_file_kb": 1, "max_total_file_context_per_message_kb": 1})
    result = run(fixture.runtime.handle_input(session, "summarize", attachments=[first, second]))
    sent = _last_non_title_user_content(llm)
    metadata = fixture.runs.get_run(result.run_id).metadata["file_context"]
    assert metadata["enabled"] is True
    assert metadata["files_sent"] == 1
    assert metadata["total_chars"] == 1024
    assert "Truncated: true" in sent

    settings.patch({"send_text_file_attachments_to_llm": False})
    result = run(fixture.runtime.handle_input(session, "again", attachments=[first]))
    sent = _last_non_title_user_content(llm)
    metadata = fixture.runs.get_run(result.run_id).metadata["file_context"]
    assert "file context is disabled" in sent
    assert "aaaa" not in sent
    assert metadata["enabled"] is False
    assert metadata["files_sent"] == 0


def _last_non_title_user_content(llm: FakeLLMRuntime) -> str:
    for call in reversed(llm.calls):
        content = call["messages"][-1]["content"]
        if not str(content).startswith("Generate a short title"):
            return content
    raise AssertionError("no prompt agent call found")


def test_data_storage_stats_scan_and_cleanup(monkeypatch, tmp_path: Path) -> None:
    attachments_dir = tmp_path / "attachments"
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(attachments_dir))
    db_url = f"sqlite:///{tmp_path / 'workbench.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))
    state = client.app.state.runtime_state
    session = state.sessions.create_session()
    referenced = attachments_dir / "files" / "11111111-1111-1111-1111-111111111111.txt"
    orphan = attachments_dir / "files" / "22222222-2222-2222-2222-222222222222.txt"
    outside = tmp_path / "outside.txt"
    referenced.parent.mkdir(parents=True)
    referenced.write_text("keep", encoding="utf-8")
    orphan.write_text("delete", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    state.messages.add_message(
        session_id=session.session_id,
        role="user",
        content="attached",
        metadata={"attachments": [{"id": "keep", "uri": f"local://attachments/{referenced.name}", "type": "file"}]},
    )

    stats = client.get("/api/data/storage-stats")
    assert stats.status_code == 200
    assert stats.json()["database"]["size_bytes"] >= 0
    assert stats.json()["attachments"]["count"] == 2
    assert stats.json()["attachments"]["orphan_count"] == 1

    scan = client.post("/api/data/attachments/scan-orphans")
    assert scan.status_code == 200
    assert scan.json()["orphans"][0]["id"] == orphan.name

    rejected = client.post("/api/data/attachments/cleanup-orphans", json={"confirm": False})
    assert rejected.status_code == 400
    cleaned = client.post("/api/data/attachments/cleanup-orphans", json={"confirm": True})
    assert cleaned.status_code == 200
    assert cleaned.json()["deleted_count"] == 1
    assert referenced.exists()
    assert not orphan.exists()
    assert outside.exists()


def test_cleanup_attachments_script_still_runs(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    orphan = tmp_path / "attachments" / "files" / "33333333-3333-3333-3333-333333333333.txt"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("orphan", encoding="utf-8")

    assert cleanup_main(["--database-url", f"sqlite:///{tmp_path / 'missing.db'}"]) == 0
    assert "orphan count: 1" in capsys.readouterr().out
    assert cleanup_main(["--database-url", f"sqlite:///{tmp_path / 'missing.db'}", "--apply"]) == 0
    assert not orphan.exists()
