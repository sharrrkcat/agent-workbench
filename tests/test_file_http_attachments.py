import os
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.attachments import (
    read_attachment_as_data_url,
    read_attachment_text,
    resolve_attachment_uri,
    save_attachment_from_data_url,
    save_attachment_from_upload,
    validate_attachments,
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


def test_text_file_attachment_is_saved_without_data_url(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    data_url = "data:text/plain;base64,aGVsbG8KICB3b3JsZA=="

    attachments = validate_attachments(
        [
            {
                "id": "client-file",
                "type": "file",
                "mime_type": "text/plain",
                "name": "note.txt",
                "size": 13,
                "data_url": data_url,
            }
        ]
    )

    stored = attachments[0]
    assert stored["type"] == "file"
    assert stored["uri"].startswith("local://attachments/")
    assert "data_url" not in stored
    assert resolve_attachment_uri(stored["uri"]).read_bytes() == b"hello\n  world"
    assert read_attachment_text(stored)["content"] == "hello\n  world"


def test_multiple_attachments_are_all_saved(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))

    attachments = validate_attachments(
        [
            image_attachment(name="cat.png", data_url=PNG_DATA_URL, size=5, mime_type="image/png"),
            {
                "id": "client-file",
                "type": "file",
                "mime_type": "application/yaml",
                "name": "agent.yaml",
                "size": 9,
                "data_url": "data:application/yaml;base64,aWQ6IGNoYXQK",
            },
        ]
    )

    assert [item["type"] for item in attachments] == ["image", "file"]
    assert all(item["uri"].startswith("local://attachments/") for item in attachments)
    assert all("data_url" not in item for item in attachments)


def test_unsupported_binary_attachment_is_rejected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))

    try:
        save_attachment_from_upload("archive.zip", "application/zip", b"PK\x03\x04")
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)
    else:
        raise AssertionError("expected unsupported binary rejection")


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


def test_attachment_api_returns_text_file_bytes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    stored = save_attachment_from_upload("note.txt", "text/plain", b"hello text")
    attachment_id = stored["uri"].removeprefix("local://attachments/")
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))

    response = client.get(f"/api/attachments/{attachment_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.content == b"hello text"


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


def test_cleanup_attachments_tracks_file_attachments(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    db_url = f"sqlite:///{tmp_path / 'workbench.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))
    session = create_session(client)
    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={
            "content": "file",
            "attachments": [
                {
                    "id": "client-file",
                    "type": "file",
                    "mime_type": "text/plain",
                    "name": "note.txt",
                    "size": 5,
                    "data_url": "data:text/plain;base64,aGVsbG8=",
                }
            ],
        },
    )
    attachment = response.json()["messages"][0]["metadata"]["attachments"][0]
    orphan = tmp_path / "attachments" / "files" / "00000000-0000-0000-0000-000000000000.txt"
    orphan.write_bytes(b"orphan")

    exit_code = cleanup_main(["--database-url", db_url])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert attachment["uri"].removeprefix("local://attachments/") in output or "referenced count: 1" in output
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


def test_file_capability_config_defaults_and_patch(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    allowed = tmp_path / "allowed"

    defaults = client.get("/api/capability-configs/file")
    assert defaults.status_code == 200
    resolved = defaults.json()["resolved_config"]
    assert resolved["allowed_directories"] == ["./data", "./examples", "./agents", "./capabilities"]
    assert resolved["max_local_text_read_size_mb"] == 2.0
    assert resolved["max_local_image_read_size_mb"] == 10.0

    patched = client.patch(
        "/api/capability-configs/file",
        json={
            "user_config": {
                "allowed_directories": [str(allowed)],
                "max_local_text_read_size_mb": 0.5,
                "max_local_image_read_size_mb": 0.5,
            }
        },
    )
    assert patched.status_code == 200
    assert patched.json()["resolved_config"]["allowed_directories"] == [str(allowed)]
    assert patched.json()["resolved_config"]["max_local_text_read_size_mb"] == 0.5
    assert patched.json()["resolved_config"]["max_local_image_read_size_mb"] == 0.5

    assert client.patch("/api/capability-configs/file", json={"user_config": {"unknown": True}}).status_code == 400
    assert client.patch("/api/capability-configs/file", json={"user_config": {"enable_read_file": "yes"}}).status_code == 400


def test_file_capability_config_runtime_enforcement(tmp_path: Path) -> None:
    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    client = TestClient(app)
    session = create_session(client)
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    note = allowed / "note.txt"
    note.write_text("hello", encoding="utf-8")
    denied_note = denied / "note.txt"
    denied_note.write_text("secret", encoding="utf-8")
    blocked = allowed / "blocked.exe"
    blocked.write_text("no", encoding="utf-8")
    large = allowed / "large.txt"
    large.write_bytes(b"x" * (200 * 1024))
    image = allowed / "cat.png"
    image.write_bytes(b"hello")
    large_image = allowed / "large.png"
    large_image.write_bytes(b"x" * (200 * 1024))

    client.patch(
        "/api/capability-configs/file",
        json={
            "user_config": {
                "allowed_directories": [str(allowed)],
                "max_local_text_read_size_mb": 0.1,
                "max_local_image_read_size_mb": 0.1,
                "allowed_text_extensions": [".txt"],
                "enable_read_file": True,
                "enable_read_image": True,
            }
        },
    )

    accepted = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {note}"})
    outside = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {denied_note}"})
    too_large = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {large}"})
    bad_ext = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {blocked}"})
    image_ok = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-image {image}"})
    image_large = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-image {large_image}"})

    assert accepted.json()["run"]["status"] == "DONE"
    assert accepted.json()["run"]["target_id"] == "/read-file"
    assert accepted.json()["messages"][-1]["output_type"] == "file_content"
    assert outside.json()["run"]["status"] == "FAILED"
    assert "Path outside allowed directories" in outside.json()["run"]["error"]
    assert "File too large" in too_large.json()["run"]["error"]
    assert "Extension not allowed" in bad_ext.json()["run"]["error"]
    assert image_ok.json()["run"]["status"] == "DONE"
    assert image_ok.json()["messages"][-1]["output_type"] == "image"
    assert "File too large" in image_large.json()["run"]["error"]

    client.patch("/api/capability-configs/file", json={"user_config": {"allowed_directories": [str(allowed)], "enable_read_file": False}})
    disabled_file = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {note}"})
    assert "Command disabled" in disabled_file.json()["run"]["error"]

    client.patch("/api/capability-configs/file", json={"user_config": {"allowed_directories": [str(allowed)], "enable_read_image": False}})
    disabled_image = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-image {image}"})
    assert "Command disabled" in disabled_image.json()["run"]["error"]

    client.patch("/api/capability-configs/file", json={"user_config": {"allowed_directories": []}})
    empty_dirs = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {note}"})
    assert "Path outside allowed directories" in empty_dirs.json()["run"]["error"]


def test_http_capability_config_defaults_patch_and_runtime_enforcement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        timeout = request.extensions.get("timeout") or {}
        if request.url.path == "/timeout":
            return httpx.Response(200, headers={"content-type": "application/json"}, json=timeout, request=request)
        if request.url.path == "/image":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"hello", request=request)
        if request.url.path == "/binary":
            return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"binary", request=request)
        if request.url.path == "/large":
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * (200 * 1024), request=request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"hello text", request=request)

    app = create_app(llm_runtime=FakeLLMRuntime(), use_memory=True)
    app.state.runtime_state.runtimes.replace("http", HttpRuntime(client=httpx.Client(transport=httpx.MockTransport(handler))))
    client = TestClient(app)
    session = create_session(client)

    defaults = client.get("/api/capability-configs/http")
    assert defaults.status_code == 200
    assert defaults.json()["resolved_config"]["timeout_seconds"] == 10.0
    assert defaults.json()["resolved_config"]["allowed_schemes"] == ["http", "https"]

    client.patch(
        "/api/capability-configs/http",
        json={
            "user_config": {
                "timeout_seconds": 3,
                "max_text_response_size_mb": 0.1,
                "max_image_response_size_mb": 0.1,
                "allow_redirects": False,
                "max_redirects": 0,
            }
        },
    )
    timed = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/http-get https://example.test/timeout"})
    large_text = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/http-get https://example.test/large"})
    image = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-image https://example.test/image"})
    binary = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/http-get https://example.test/binary"})

    assert timed.json()["run"]["status"] == "DONE"
    assert '"connect":3.0' in timed.json()["messages"][-1]["content"].replace(" ", "")
    assert "Response too large" in large_text.json()["run"]["error"]
    assert image.json()["messages"][-1]["output_type"] == "image"
    assert "Content type not allowed" in binary.json()["run"]["error"]

    client.patch("/api/capability-configs/http", json={"user_config": {"allowed_schemes": ["https"]}})
    scheme = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/http-get http://example.test/text"})
    assert "Scheme not allowed" in scheme.json()["run"]["error"]

    client.patch("/api/capability-configs/http", json={"user_config": {"enable_http_get": False}})
    disabled_get = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-page https://example.test/text"})
    assert "Command disabled" in disabled_get.json()["run"]["error"]

    client.patch("/api/capability-configs/http", json={"user_config": {"enable_fetch_image": False}})
    disabled_image = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-image https://example.test/image"})
    assert "Command disabled" in disabled_image.json()["run"]["error"]
