from tests.history_helpers import history_messages
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from ai_workbench.api.main import create_app
from ai_workbench.core.attachments import resolve_attachment_uri
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, ok
from tests.test_vision_input import image_bytes


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def chat(tmp_path, monkeypatch, request):
    monkeypatch.setenv("COGITA_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    upstream = ToolOpenAI()
    app = create_app(root=tmp_path, use_memory=request.param,
                     database_url=f"sqlite:///{tmp_path / 'chat.db'}", adapter_factory=upstream.factory)
    with TestClient(app) as client:
        configure_model(client)
        ok(client.patch("/api/settings/general", json={"auto_generate_session_titles": False}))
        session = ok(client.post("/api/sessions", json={"harness_enabled": False}))
        attachments = [ok(client.post("/api/attachments", files={"file": file})) for file in [
            ("picture.png", image_bytes(), "image/png"),
            ("keep.txt", b"KEEP_FILE_CONTEXT", "text/plain"),
            ("remove.txt", b"DROP_FILE_CONTEXT", "text/plain"),
        ]]
        path = f"/api/sessions/{session['session_id']}/messages"
        response = ok(client.post(path, json={"content": "original", "attachments": attachments}))
        user = next(message for message in response["messages"] if message["role"] == "user")
        yield client, upstream, path, user, attachments


def test_edit_persists_retained_order_and_regenerates_only_retained_attachments(chat):
    client, upstream, path, user, attachments = chat
    later = ok(client.post(path, json={"content": "later"}))
    response = ok(client.post(f"/api/messages/{user['message_id']}/edit", json={
        "content": "edited", "attachment_ids": [attachments[1]["id"], attachments[0]["id"]],
    }))
    assert response["success"]
    history = history_messages(ok(client.get(path.removesuffix("/messages") + "/history")))
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert history[0]["message_id"] == user["message_id"]
    assert history[0]["created_at"] != user["created_at"]
    assert history[0]["metadata"]["attachments"] == attachments[:2]
    assert later["run"]["run_id"] in response["deleted_run_ids"]
    request = json.dumps(upstream.calls[-1]["messages"])
    assert "KEEP_FILE_CONTEXT" in request and "DROP_FILE_CONTEXT" not in request
    assert "data:image/png;base64," in request
    assert not resolve_attachment_uri(attachments[2]["uri"]).exists()
    assert all(resolve_attachment_uri(item["uri"]).exists() for item in attachments[:2])
    updated = [event for event in client.app.state.runtime_state.events.list_events()
               if event.type == "message_updated" and event.message_id == user["message_id"]]
    assert updated[-1].payload["message"]["metadata"]["attachments"] == attachments[:2]


def test_invalid_attachment_edits_do_not_prune_or_change_the_message(chat):
    client, _, path, user, attachments = chat
    before = history_messages(ok(client.get(path.removesuffix("/messages") + "/history")))
    cases = [
        ({"content": "edited"}, 422, None),
        ({"content": "edited", "attachment_ids": [1]}, 422, None),
        ({"content": "edited", "attachment_ids": ["unrelated"]}, 400, "INVALID_ATTACHMENTS"),
        ({"content": "edited", "attachment_ids": [attachments[0]["id"]] * 2}, 400, "INVALID_ATTACHMENTS"),
        ({"content": " \n", "attachment_ids": []}, 400, "EMPTY_MESSAGE"),
    ]
    for payload, status, code in cases:
        response = client.post(f"/api/messages/{user['message_id']}/edit", json={**payload, "rerun": False})
        assert response.status_code == status, response.text
        if code:
            assert response.json()["error"]["code"] == code
        assert history_messages(ok(client.get(path.removesuffix("/messages") + "/history"))) == before
        assert all(resolve_attachment_uri(item["uri"]).exists() for item in attachments)


def test_attachment_only_edit_and_remove_all_preserve_shared_files(chat):
    client, _, path, user, attachments = chat
    shared = ok(client.post("/api/sessions", json={"harness_enabled": False}))
    other = ok(client.post(f"/api/sessions/{shared['session_id']}/messages", json={
        "content": "shared", "attachments": [attachments[0]],
    }))
    url = f"/api/messages/{user['message_id']}/edit"
    edited = ok(client.post(url, json={"content": "", "attachment_ids": [attachments[0]["id"]], "rerun": False}))
    assert edited["messages"][0]["parts"] == []
    assert history_messages(ok(client.get(path.removesuffix("/messages") + "/history")))[0]["metadata"]["attachments"] == attachments[:1]
    assert not resolve_attachment_uri(attachments[1]["uri"]).exists()
    ok(client.post(url, json={"content": "text only", "attachment_ids": [], "rerun": False}))
    assert history_messages(ok(client.get(path.removesuffix("/messages") + "/history")))[0]["metadata"]["attachments"] == []
    image_path = resolve_attachment_uri(attachments[0]["uri"])
    assert image_path.exists()
    other_user = next(message for message in other["messages"] if message["role"] == "user")
    ok(client.delete(f"/api/messages/{other_user['message_id']}"))
    assert not image_path.exists()


def test_failed_edit_commit_preserves_history_metadata_and_files(chat, monkeypatch):
    client, _, path, user, attachments = chat
    state = client.app.state.runtime_state
    before = history_messages(ok(client.get(path.removesuffix("/messages") + "/history")))
    engine = getattr(state.history.store, "engine", None)

    def fail(*args):
        raise RuntimeError("injected edit failure")

    def fail_update(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("UPDATE messagerecord"):
            fail()

    if engine:
        event.listen(engine, "before_cursor_execute", fail_update)
    else:
        monkeypatch.setattr(state.history.store, "prune", fail)
    try:
        with pytest.raises(RuntimeError, match="injected edit failure"):
            client.post(f"/api/messages/{user['message_id']}/edit", json={
                "content": "changed", "attachment_ids": [], "rerun": False,
            })
    finally:
        if engine:
            event.remove(engine, "before_cursor_execute", fail_update)
    assert history_messages(ok(client.get(path.removesuffix("/messages") + "/history"))) == before
    assert state.runs.list_runs(user["session_id"])
    assert all(resolve_attachment_uri(item["uri"]).exists() for item in attachments)
