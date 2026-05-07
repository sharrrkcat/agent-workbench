import os
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.attachments import (
    read_attachment_as_data_url,
    resolve_attachment_uri,
    save_attachment_from_data_url,
    validate_image_attachments,
)
from capabilities.file import CapabilityRuntime as FileRuntime
from capabilities.http import CapabilityRuntime as HttpRuntime
from scripts.cleanup_attachments import main as cleanup_main
from tests.test_api import SVG_DATA_URL, create_session, image_attachment
from tests.test_prompt_agent_execution import FakeLLMRuntime


PNG_DATA_URL = "data:image/png;base64,aGVsbG8="


def test_data_url_attachment_is_saved_as_local_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))

    stored = save_attachment_from_data_url(image_attachment(name="cat.png", data_url=PNG_DATA_URL, size=5, mime_type="image/png"))

    assert stored["uri"].startswith("local://attachments/")
    assert "data_url" not in stored
    assert stored["name"] == "cat.png"
    assert resolve_attachment_uri(stored["uri"]).read_bytes() == b"hello"
    assert read_attachment_as_data_url(stored) == PNG_DATA_URL


def test_validate_image_attachments_migrates_data_url(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))

    attachments = validate_image_attachments([image_attachment()])

    assert attachments[0]["uri"].startswith("local://attachments/")
    assert "data_url" not in attachments[0]
    assert attachments[0]["created_at"]


def test_attachment_api_returns_bytes_and_rejects_traversal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    stored = save_attachment_from_data_url(image_attachment(name="cat.png", data_url=PNG_DATA_URL, size=5, mime_type="image/png"))
    attachment_id = stored["uri"].removeprefix("local://attachments/")
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))

    response = client.get(f"/api/attachments/{attachment_id}")
    escaped = client.get("/api/attachments/..%2Fsecret.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"hello"
    assert escaped.status_code == 404


def test_local_attachment_is_sent_to_vision_model(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    llm = FakeLLMRuntime(response="vision")
    app = create_app(llm_runtime=llm, use_memory=True)
    client = TestClient(app)
    session = create_session(client)
    profile = client.post(
        "/api/llm-profiles",
        json={
            "alias": "vision_profile",
            "name": "Vision Profile",
            "base_url": "http://localhost:1234/v1",
            "model_id": "fake-vision",
            "supports_streaming": False,
            "supports_vision": True,
        },
    ).json()
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": profile["id"]})

    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "describe", "attachments": [image_attachment(name="cat.png", data_url=PNG_DATA_URL, size=5, mime_type="image/png")]},
    )

    assert response.status_code == 200
    sent = llm.calls[-1]["messages"][-1]["content"]
    assert sent[1] == {"type": "image_url", "image_url": {"url": PNG_DATA_URL}}
    assert response.json()["run"]["metadata"]["vision_input"] == {
        "supported": True,
        "images_attached": 1,
        "images_sent": 1,
        "images_ignored": 0,
    }


def test_non_vision_model_does_not_read_local_attachment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    llm = FakeLLMRuntime(response="text")
    client = TestClient(create_app(llm_runtime=llm, use_memory=True))
    session = create_session(client)

    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "describe", "attachments": [image_attachment(name="cat.png", data_url=PNG_DATA_URL, size=5, mime_type="image/png")]},
    )

    assert response.status_code == 200
    sent = llm.calls[-1]["messages"][-1]["content"]
    assert PNG_DATA_URL not in sent
    assert response.json()["run"]["metadata"]["vision_input"]["images_sent"] == 0


def test_delete_message_removes_unreferenced_attachment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    session = create_session(client)
    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "image", "attachments": [image_attachment(name="cat.png", data_url=PNG_DATA_URL, size=5, mime_type="image/png")]},
    )
    user_message = response.json()["messages"][0]
    attachment_path = resolve_attachment_uri(user_message["metadata"]["attachments"][0]["uri"])

    deleted = client.delete(f"/api/messages/{user_message['message_id']}")

    assert deleted.status_code == 200
    assert not attachment_path.exists()


def test_delete_message_keeps_attachment_referenced_elsewhere(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    client = TestClient(app)
    session = create_session(client)
    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "image", "attachments": [image_attachment(name="cat.png", data_url=PNG_DATA_URL, size=5, mime_type="image/png")]},
    )
    first = response.json()["messages"][0]
    attachment = first["metadata"]["attachments"][0]
    attachment_path = resolve_attachment_uri(attachment["uri"])
    app.state.runtime_state.messages.add_message(
        session_id=session["session_id"],
        role="user",
        content="same image",
        metadata={"attachments": [attachment]},
    )

    deleted = client.delete(f"/api/messages/{first['message_id']}")

    assert deleted.status_code == 200
    assert attachment_path.exists()


def test_cleanup_attachments_dry_run(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    db_url = f"sqlite:///{tmp_path / 'workbench.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))
    session = create_session(client)
    client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "image", "attachments": [image_attachment(name="cat.png", data_url=PNG_DATA_URL, size=5, mime_type="image/png")]},
    )
    orphan = tmp_path / "attachments" / "images" / "00000000-0000-0000-0000-000000000000.png"
    orphan.write_bytes(b"orphan")

    exit_code = cleanup_main(["--database-url", db_url])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "referenced count: 1" in output
    assert "orphan count: 1" in output
    assert orphan.exists()


def test_file_capability_reads_allowed_text_and_rejects_outside(monkeypatch, tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    text_file = allowed / "note.txt"
    denied_file = denied / "secret.txt"
    text_file.write_text("hello", encoding="utf-8")
    denied_file.write_text("secret", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    payload = runtime.read_text(str(text_file))
    assert payload["filename"] == "note.txt"
    assert payload["language"] == "text"
    assert payload["mime_type"] == "text/plain"
    assert payload["content"] == "hello"
    assert payload["size"] == 5
    assert payload["truncated"] is False
    try:
        runtime.read_text(str(denied_file))
    except ValueError as exc:
        assert "File access denied" in str(exc)
    else:
        raise AssertionError("expected denied path")


def test_file_capability_returns_language_and_preserves_content(monkeypatch, tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "tool.py"
    source.write_bytes(b"def main():\n    return 'ok'\n")
    config = allowed / "agent.yaml"
    config.write_bytes(b"id: chat\nname: Chat\n")
    env_file = allowed / ".env.example"
    env_file.write_bytes(b"API_KEY=value\n")
    markdown = allowed / "README.md"
    markdown.write_bytes(b"# Title\n\n- item\n")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    py_payload = runtime.read_text(str(source))
    yaml_payload = runtime.read_text(str(config))
    env_payload = runtime.read_text(str(env_file))
    md_payload = runtime.read_text(str(markdown))

    assert py_payload["language"] == "python"
    assert py_payload["content"] == "def main():\n    return 'ok'\n"
    assert yaml_payload["language"] == "yaml"
    assert env_payload["language"] == "dotenv"
    assert md_payload["language"] == "markdown"
    assert md_payload["content"] == "# Title\n\n- item\n"


def test_file_capability_truncates_large_utf8_text(monkeypatch, tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    large = allowed / "large.log"
    large.write_bytes(("a" * (1024 * 1024) + "界").encode("utf-8"))
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    payload = runtime.read_text(str(large))

    assert payload["language"] == "log"
    assert payload["size"] == 1024 * 1024 + len("界".encode("utf-8"))
    assert payload["truncated"] is True
    assert payload["content"] == "a" * (1024 * 1024)


def test_file_capability_reads_image_and_rejects_non_image(monkeypatch, tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    image = allowed / "cat.png"
    text = allowed / "note.txt"
    image.write_bytes(b"hello")
    text.write_text("hello", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    payload = runtime.read_image(str(image))

    assert payload["url"] == PNG_DATA_URL
    try:
        runtime.read_image(str(text))
    except ValueError as exc:
        assert "Only PNG" in str(exc)
    else:
        raise AssertionError("expected non-image rejection")


def test_http_capability_rejects_non_http_scheme() -> None:
    runtime = HttpRuntime()
    try:
        runtime.get_text("file:///tmp/secret")
    except ValueError as exc:
        assert "only allows http:// and https://" in str(exc)
    else:
        raise AssertionError("expected scheme rejection")


def test_http_capability_fetches_text_and_image_and_rejects_non_image() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/image":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"hello", request=request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"hello text", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test")
    runtime = HttpRuntime(client=client)

    assert runtime.get_text("https://example.test/text") == "hello text"
    assert runtime.fetch_image("https://example.test/image")["url"] == PNG_DATA_URL
    try:
        runtime.fetch_image("https://example.test/text")
    except ValueError as exc:
        assert "not an image" in str(exc)
    else:
        raise AssertionError("expected non-image rejection")


def test_http_capability_size_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * (1024 * 1024 + 1), request=request)

    runtime = HttpRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    try:
        runtime.get_text("https://example.test/large")
    except ValueError as exc:
        assert "too large" in str(exc)
    else:
        raise AssertionError("expected size rejection")


def test_http_capability_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    runtime = HttpRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    try:
        runtime.get_text("https://example.test/slow")
    except ValueError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("expected timeout rejection")
