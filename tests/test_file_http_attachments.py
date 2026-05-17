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
    save_generated_attachment_file,
    validate_attachments,
    validate_image_attachments,
)
from capabilities.file import CapabilityRuntime as FileRuntime
from capabilities.http import CapabilityRuntime as HttpRuntime
from scripts.cleanup_attachments import main as cleanup_main
from tests.test_api import SVG_DATA_URL, create_llm_profile, create_session, image_attachment
from tests.test_prompt_agent_execution import FakeLLMRuntime


PNG_DATA_URL = "data:image/png;base64,aGVsbG8="


class CountingByteStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.iterated = False

    def __iter__(self):
        self.iterated = True
        yield from self.chunks


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


def test_attachment_api_accepts_text_file_upload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))

    response = client.post(
        "/api/attachments",
        files={"file": ("note.txt", b"hello knowledge", "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "file"
    assert payload["name"] == "note.txt"
    assert payload["uri"].startswith("local://attachments/")
    assert resolve_attachment_uri(payload["uri"]).read_text(encoding="utf-8") == "hello knowledge"


def test_attachment_api_accepts_and_serves_audio_upload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))

    response = client.post(
        "/api/attachments",
        files={"file": ("demo.wav", b"RIFF----WAVEfmt ", "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "audio"
    assert payload["name"] == "demo.wav"
    path = resolve_attachment_uri(payload["uri"])
    assert path.parent.name == "audios"
    served = client.get(payload["url"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("audio/wav")
    assert served.headers["accept-ranges"] == "bytes"
    assert served.headers["content-length"] == str(len(b"RIFF----WAVEfmt "))
    assert served.content == b"RIFF----WAVEfmt "


def test_audio_attachment_api_supports_byte_ranges(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    data = bytes(range(256))
    stored = save_attachment_from_upload("demo.wav", "audio/wav", data)
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))

    full = client.get(stored["url"])
    first_100 = client.get(stored["url"], headers={"Range": "bytes=0-99"})
    from_100 = client.get(stored["url"], headers={"Range": "bytes=100-"})
    suffix_100 = client.get(stored["url"], headers={"Range": "bytes=-100"})
    unsatisfiable = client.get(stored["url"], headers={"Range": "bytes=256-300"})
    escaped = client.get("/api/attachments/..%2Fsecret.wav", headers={"Range": "bytes=0-99"})

    assert full.status_code == 200
    assert full.headers["content-type"].startswith("audio/wav")
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-length"] == str(len(data))
    assert full.content == data

    assert first_100.status_code == 206
    assert first_100.headers["content-type"].startswith("audio/wav")
    assert first_100.headers["accept-ranges"] == "bytes"
    assert first_100.headers["content-range"] == f"bytes 0-99/{len(data)}"
    assert first_100.headers["content-length"] == "100"
    assert first_100.content == data[:100]

    assert from_100.status_code == 206
    assert from_100.headers["content-range"] == f"bytes 100-255/{len(data)}"
    assert from_100.headers["content-length"] == str(len(data) - 100)
    assert from_100.content == data[100:]

    assert suffix_100.status_code == 206
    assert suffix_100.headers["content-range"] == f"bytes 156-255/{len(data)}"
    assert suffix_100.headers["content-length"] == "100"
    assert suffix_100.content == data[-100:]

    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers["content-range"] == f"bytes */{len(data)}"
    assert unsatisfiable.headers["content-length"] == "0"
    assert unsatisfiable.content == b""

    assert escaped.status_code == 404


def test_video_attachment_api_supports_byte_ranges(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    source = tmp_path / "demo.mp4"
    data = bytes(range(256))
    source.write_bytes(data)
    stored = save_generated_attachment_file(source, filename="demo.mp4", mime_type="video/mp4", kind="video", max_size_bytes=len(data))
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))

    full = client.get(stored["url"])
    first_100 = client.get(stored["url"], headers={"Range": "bytes=0-99"})

    assert stored["type"] == "video"
    assert resolve_attachment_uri(stored["uri"]).parent.name == "videos"
    assert full.status_code == 200
    assert full.headers["content-type"].startswith("video/mp4")
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-length"] == str(len(data))
    assert full.content == data
    assert first_100.status_code == 206
    assert first_100.headers["content-type"].startswith("video/mp4")
    assert first_100.headers["content-range"] == f"bytes 0-99/{len(data)}"
    assert first_100.content == data[:100]


def test_attachment_api_returns_text_file_bytes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    stored = save_attachment_from_upload("note.txt", "text/plain", b"hello text")
    attachment_id = stored["uri"].removeprefix("local://attachments/")
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))

    response = client.get(f"/api/attachments/{attachment_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(b"hello text"))
    assert response.content == b"hello text"


def test_local_attachment_is_sent_to_vision_model(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    llm = FakeLLMRuntime(response="vision")
    app = create_app(llm_runtime=llm, use_memory=True)
    client = TestClient(app)
    session = create_session(client)
    provider = client.post(
        "/api/llm-provider-profiles",
        json={"name": "Vision Provider", "provider": "openai_compatible", "base_url": "http://localhost:1234/v1"},
    ).json()
    profile = client.post(
        "/api/llm-profiles",
        json={
            "alias": "vision_profile",
            "name": "Vision Profile",
            "provider_profile_id": provider["id"],
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
    profile = create_llm_profile(client, alias="nonvision")
    client.patch(f"/api/sessions/{session['session_id']}", json={"llm_profile_id": profile["id"]})

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


def test_file_capability_read_file_auto_detects_text(monkeypatch, tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    text_file = allowed / "note.txt"
    text_file.write_text("hello", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    parts = runtime.read_file(str(text_file))

    assert parts == [
        {
            "type": "file",
            "mode": "inline_text",
            "filename": "note.txt",
            "language": "text",
            "mime_type": "text/plain",
            "content": "hello",
            "size": 5,
            "truncated": False,
        }
    ]


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
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    image = allowed / "cat.png"
    text = allowed / "note.txt"
    image.write_bytes(b"hello")
    text.write_text("hello", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    payload = runtime.read_image(str(image))

    assert payload["attachment_id"]
    assert payload["url"].startswith("/api/attachments/")
    assert resolve_attachment_uri(f"local://attachments/{Path(payload['url']).name}").read_bytes() == b"hello"
    try:
        runtime.read_image(str(text))
    except ValueError as exc:
        assert "Only PNG" in str(exc)
    else:
        raise AssertionError("expected non-image rejection")


def test_file_capability_read_file_auto_detects_image(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    image = allowed / "cat.png"
    image.write_bytes(b"hello")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    parts = runtime.read_file(str(image))

    assert parts[0]["type"] == "image"
    assert parts[0]["attachment_id"]
    assert parts[0]["url"].startswith("/api/attachments/")


def test_file_capability_reads_audio_and_rejects_non_audio(monkeypatch, tmp_path: Path) -> None:
    attachments_dir = tmp_path / "attachments"
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(attachments_dir))
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    audio = allowed / "demo.wav"
    text = allowed / "note.txt"
    audio.write_bytes(b"RIFF----WAVEfmt ")
    text.write_text("hello", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    payload = runtime.read_audio(str(audio))

    assert payload["source"] == "attachment"
    assert payload["mime_type"] == "audio/wav"
    assert payload["filename"] == "demo.wav"
    assert payload["url"].startswith("/api/attachments/")
    assert resolve_attachment_uri(f"local://attachments/{Path(payload['url']).name}").read_bytes() == b"RIFF----WAVEfmt "
    try:
        runtime.read_audio(str(text))
    except ValueError as exc:
        assert "Only WAV" in str(exc)
    else:
        raise AssertionError("expected non-audio rejection")


def test_file_capability_read_file_auto_detects_audio(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    audio = allowed / "demo.wav"
    audio.write_bytes(b"RIFF----WAVEfmt ")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    parts = runtime.read_file(str(audio))

    assert parts[0]["type"] == "audio"
    assert parts[0]["source"] == "attachment"
    assert parts[0]["mime_type"] == "audio/wav"


def test_file_capability_read_file_auto_detects_mp4_video(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    video = allowed / "demo.mp4"
    video.write_bytes(b"video")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    parts = runtime.read_file(str(video))

    assert parts[0]["type"] == "video"
    assert parts[0]["source"] == "attachment"
    assert parts[0]["mime_type"] == "video/mp4"
    assert parts[0]["size_bytes"] == 5
    assert resolve_attachment_uri(f"local://attachments/{Path(parts[0]['url']).name}").parent.name == "videos"


def test_file_capability_read_file_auto_detects_webm_video(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    video = allowed / "demo.webm"
    video.write_bytes(b"video")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))
    runtime = FileRuntime()

    parts = runtime.read_file(str(video))

    assert parts[0]["type"] == "video"
    assert parts[0]["mime_type"] == "video/webm"


def test_file_capability_video_obeys_path_and_size_limits(monkeypatch, tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    video = allowed / "demo.mp4"
    large_video = allowed / "large.mp4"
    denied_video = denied / "secret.mp4"
    video.write_bytes(b"video")
    large_video.write_bytes(b"x" * 20)
    denied_video.write_bytes(b"secret")
    config = {
        "allowed_directories": [str(allowed)],
        "max_local_video_read_size_mb": 0.00001,
        "enable_read_file_command": True,
    }
    runtime = FileRuntime()

    parts = runtime.read_file(str(video), context={"capability_config": config})
    assert parts[0]["mime_type"] == "video/mp4"
    try:
        runtime.read_file(str(large_video), context={"capability_config": config})
    except ValueError as exc:
        assert "File too large" in str(exc)
        assert "/read-file video result" in str(exc)
        assert "1e-05 MB" in str(exc)
    else:
        raise AssertionError("expected video size rejection")
    try:
        runtime.read_file(str(denied_video), context={"capability_config": config})
    except ValueError as exc:
        assert "File access denied" in str(exc)
    else:
        raise AssertionError("expected video path rejection")


def test_file_capability_video_copy_does_not_read_full_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    video = allowed / "demo.ogv"
    video.write_bytes(b"video")
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(allowed))

    def fail_read_bytes(self):
        raise AssertionError("read_bytes should not be used for video attachments")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    runtime = FileRuntime()

    parts = runtime.read_file(str(video))

    assert parts[0]["type"] == "video"
    assert parts[0]["mime_type"] == "video/ogg"


def test_file_capability_audio_obeys_path_and_size_limits(monkeypatch, tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    audio = allowed / "demo.mp3"
    large_audio = allowed / "large.mp3"
    denied_audio = denied / "secret.mp3"
    audio.write_bytes(b"audio")
    large_audio.write_bytes(b"x" * 20)
    denied_audio.write_bytes(b"secret")
    config = {
        "allowed_directories": [str(allowed)],
        "max_local_audio_read_size_mb": 0.00001,
        "enable_read_file_command": True,
    }
    runtime = FileRuntime()

    payload = runtime.read_audio(str(audio), context={"capability_config": config})
    assert payload["mime_type"] == "audio/mpeg"
    try:
        runtime.read_audio(str(large_audio), context={"capability_config": config})
    except ValueError as exc:
        assert "File too large" in str(exc)
        assert "/read-file audio result" in str(exc)
        assert "1e-05 MB" in str(exc)
        assert "Attachment file is too large" not in str(exc)
    else:
        raise AssertionError("expected audio size rejection")
    try:
        runtime.read_audio(str(denied_audio), context={"capability_config": config})
    except ValueError as exc:
        assert "File access denied" in str(exc)
    else:
        raise AssertionError("expected audio path rejection")


def test_file_capability_audio_limit_overrides_generated_attachment_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    audio = allowed / "long.mp3"
    audio.write_bytes(b"x" * (11 * 1024 * 1024))
    config = {
        "allowed_directories": [str(allowed)],
        "max_local_audio_read_size_mb": 100,
        "enable_read_file_command": True,
    }
    runtime = FileRuntime()

    payload = runtime.read_audio(str(audio), context={"capability_config": config})

    assert payload["mime_type"] == "audio/mpeg"
    assert resolve_attachment_uri(f"local://attachments/{Path(payload['url']).name}").stat().st_size == 11 * 1024 * 1024


def test_http_capability_rejects_non_http_scheme() -> None:
    runtime = HttpRuntime()
    try:
        runtime.fetch_url("file:///tmp/secret")
    except ValueError as exc:
        assert "only allows http:// and https://" in str(exc)
    else:
        raise AssertionError("expected scheme rejection")


def test_http_capability_fetch_url_auto_detects_supported_parts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/image":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"hello", request=request)
        if request.url.path == "/json":
            return httpx.Response(200, headers={"content-type": "application/json"}, json={"ok": True}, request=request)
        if request.url.path == "/html":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html><body><h1>Title</h1><script>x()</script><p>Hello page</p></body></html>", request=request)
        if request.url.path == "/audio.mp3":
            return httpx.Response(200, headers={"content-type": "audio/mpeg", "content-length": "123456"}, content=b"", request=request)
        if request.url.path == "/audio.ogg":
            return httpx.Response(200, headers={"content-type": "audio/ogg"}, content=b"", request=request)
        if request.url.path == "/audio.m4a":
            return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"", request=request)
        if request.url.path == "/video.mp4":
            return httpx.Response(200, headers={"content-type": "video/mp4", "content-length": "12345678"}, content=b"", request=request)
        if request.url.path == "/video.webm":
            return httpx.Response(200, headers={"content-type": "video/webm"}, content=b"", request=request)
        if request.url.path == "/video.ogv":
            return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"", request=request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"hello text", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test")
    runtime = HttpRuntime(client=client)

    assert runtime.get_text("https://example.test/text") == "hello text"
    assert runtime.fetch_image("https://example.test/image")["url"] == PNG_DATA_URL
    assert runtime.fetch_url("https://example.test/text") == [{"type": "text", "format": "plain", "text": "hello text"}]
    assert runtime.fetch_url("https://example.test/json") == [{"type": "json", "data": {"ok": True}}]
    html = runtime.fetch_url("https://example.test/html")
    assert html[0]["type"] == "text"
    assert html[0]["format"] == "markdown"
    assert "Title" in html[0]["text"]
    assert "Hello page" in html[0]["text"]
    assert "x()" not in html[0]["text"]
    assert runtime.fetch_url("https://example.test/image")[0]["type"] == "image"
    assert runtime.fetch_url("https://example.test/image")[0]["url"] == PNG_DATA_URL
    assert runtime.fetch_url("https://example.test/audio.mp3") == [
        {
            "type": "audio",
            "source": "url",
            "url": "https://example.test/audio.mp3",
            "mime_type": "audio/mpeg",
            "filename": "audio.mp3",
            "title": "audio.mp3",
            "size_bytes": 123456,
        }
    ]
    assert runtime.fetch_url("https://example.test/audio.ogg")[0]["source"] == "url"
    assert runtime.fetch_url("https://example.test/audio.ogg")[0]["mime_type"] == "audio/ogg"
    assert runtime.fetch_url("https://example.test/audio.m4a")[0]["mime_type"] == "audio/mp4"
    assert runtime.fetch_url("https://example.test/video.mp4") == [
        {
            "type": "video",
            "source": "url",
            "url": "https://example.test/video.mp4",
            "mime_type": "video/mp4",
            "filename": "video.mp4",
            "title": "video.mp4",
            "size_bytes": 12345678,
        }
    ]
    assert runtime.fetch_url("https://example.test/video.webm")[0]["mime_type"] == "video/webm"
    assert runtime.fetch_url("https://example.test/video.ogv")[0]["mime_type"] == "video/ogg"
    try:
        runtime.fetch_image("https://example.test/text")
    except ValueError as exc:
        assert "not an image" in str(exc)
    else:
        raise AssertionError("expected non-image rejection")


def test_http_capability_fetch_url_does_not_download_audio_body() -> None:
    stream = CountingByteStream([b"x" * 1024, b"y" * 1024])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "audio/mpeg", "content-length": "2048"},
            stream=stream,
            request=request,
        )

    runtime = HttpRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    part = runtime.fetch_url("https://example.test/audio.mp3")[0]

    assert part["type"] == "audio"
    assert part["source"] == "url"
    assert part["url"] == "https://example.test/audio.mp3"
    assert stream.iterated is False


def test_http_capability_fetch_url_does_not_download_video_body() -> None:
    stream = CountingByteStream([b"x" * 1024, b"y" * 1024])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "video/mp4", "content-length": "2048"},
            stream=stream,
            request=request,
        )

    runtime = HttpRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    part = runtime.fetch_url("https://example.test/video.mp4")[0]

    assert part["type"] == "video"
    assert part["source"] == "url"
    assert part["url"] == "https://example.test/video.mp4"
    assert stream.iterated is False


def test_http_capability_fetch_url_rejects_streaming_and_playlist_sources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content_types = {
            "/playlist.m3u8": "application/vnd.apple.mpegurl",
            "/stream.mpd": "application/dash+xml",
            "/radio.pls": "audio/x-scpls",
            "/feed": "application/rss+xml",
        }
        return httpx.Response(200, headers={"content-type": content_types[request.url.path]}, content=b"", request=request)

    runtime = HttpRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    for path in ["/playlist.m3u8", "/stream.mpd", "/radio.pls", "/feed"]:
        try:
            runtime.fetch_url(f"https://example.test{path}")
        except ValueError as exc:
            assert "Unsupported remote media source" in str(exc)
        else:
            raise AssertionError(f"expected remote media rejection for {path}")


def test_http_capability_fetch_url_audio_is_not_json_text_or_file() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "audio/mp4"}, content=b"", request=request)

    runtime = HttpRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    parts = runtime.fetch_url("https://example.test/audio.m4a")

    assert [part["type"] for part in parts] == ["audio"]
    assert "data" not in parts[0]
    assert "text" not in parts[0]
    assert parts[0]["source"] == "url"


def test_http_capability_fetch_url_video_is_not_json_text_or_file() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "video/webm"}, content=b"", request=request)

    runtime = HttpRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    parts = runtime.fetch_url("https://example.test/video.webm")

    assert [part["type"] for part in parts] == ["video"]
    assert "data" not in parts[0]
    assert "text" not in parts[0]
    assert "content" not in parts[0]
    assert parts[0]["source"] == "url"


def test_http_capability_size_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/image":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"x" * 20, request=request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * (1024 * 1024 + 1), request=request)

    runtime = HttpRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))

    try:
        runtime.get_text("https://example.test/large")
    except ValueError as exc:
        assert "too large" in str(exc)
    else:
        raise AssertionError("expected size rejection")
    try:
        runtime.fetch_url("https://example.test/image", context={"capability_config": {"max_image_response_size_mb": 0.00001}})
    except ValueError as exc:
        assert "too large" in str(exc)
    else:
        raise AssertionError("expected image size rejection")


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


def test_http_capability_fetch_url_preserves_redirect_policy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/one":
            return httpx.Response(302, headers={"location": "https://example.test/two"}, request=request)
        if request.url.path == "/two":
            return httpx.Response(302, headers={"location": "https://example.test/three"}, request=request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"done", request=request)

    runtime = HttpRuntime(client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True, max_redirects=1))

    try:
        runtime.fetch_url("https://example.test/one", context={"capability_config": {"max_redirects": 1}})
    except ValueError as exc:
        assert "HTTP request failed" in str(exc)
    else:
        raise AssertionError("expected redirect rejection")

    try:
        runtime.fetch_url("https://example.test/one", context={"capability_config": {"allow_redirects": False}})
    except ValueError as exc:
        assert "HTTP request failed with status 302" in str(exc)
    else:
        raise AssertionError("expected non-followed redirect rejection")


def test_file_capability_config_defaults_and_patch(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    allowed = tmp_path / "allowed"

    defaults = client.get("/api/capability-configs/file")
    assert defaults.status_code == 200
    resolved = defaults.json()["resolved_config"]
    assert resolved["allowed_directories"] == ["./data", "./examples", "./agents", "./capabilities"]
    assert resolved["max_local_text_read_size_mb"] == 2.0
    assert resolved["max_local_image_read_size_mb"] == 10.0
    assert resolved["max_local_audio_read_size_mb"] == 10.0
    assert resolved["max_local_video_read_size_mb"] == 5120.0

    patched = client.patch(
        "/api/capability-configs/file",
        json={
            "user_config": {
                "allowed_directories": [str(allowed)],
                "max_local_text_read_size_mb": 0.5,
                "max_local_image_read_size_mb": 0.5,
                "max_local_audio_read_size_mb": 0.5,
                "max_local_video_read_size_mb": 0.5,
            }
        },
    )
    assert patched.status_code == 200
    assert patched.json()["resolved_config"]["allowed_directories"] == [str(allowed)]
    assert patched.json()["resolved_config"]["max_local_text_read_size_mb"] == 0.5
    assert patched.json()["resolved_config"]["max_local_image_read_size_mb"] == 0.5
    assert patched.json()["resolved_config"]["max_local_audio_read_size_mb"] == 0.5
    assert patched.json()["resolved_config"]["max_local_video_read_size_mb"] == 0.5

    assert client.patch("/api/capability-configs/file", json={"user_config": {"unknown": True}}).status_code == 400
    assert client.patch("/api/capability-configs/file", json={"user_config": {"enable_read_file": "yes"}}).status_code == 400
    assert client.patch("/api/capability-configs/file", json={"user_config": {"enable_read_file_command": "yes"}}).status_code == 400
    assert client.patch("/api/capability-configs/file", json={"user_config": {"enable_read_image": False}}).status_code == 400
    assert client.patch("/api/capability-configs/file", json={"user_config": {"enable_read_audio_command": False}}).status_code == 400


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
    audio = allowed / "demo.wav"
    audio.write_bytes(b"RIFF----WAVEfmt ")
    large_audio = allowed / "large.wav"
    large_audio.write_bytes(b"x" * (200 * 1024))
    video = allowed / "demo.mp4"
    video.write_bytes(b"video")
    large_video = allowed / "large.mp4"
    large_video.write_bytes(b"x" * (200 * 1024))

    client.patch(
        "/api/capability-configs/file",
        json={
            "user_config": {
                "allowed_directories": [str(allowed)],
                "max_local_text_read_size_mb": 0.1,
                "max_local_image_read_size_mb": 0.1,
                "max_local_audio_read_size_mb": 0.1,
                "max_local_video_read_size_mb": 0.1,
                "allowed_text_extensions": [".txt"],
                "enable_read_file_command": True,
            }
        },
    )

    accepted = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {note}"})
    outside = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {denied_note}"})
    too_large = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {large}"})
    bad_ext = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {blocked}"})
    image_ok = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {image}"})
    image_large = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {large_image}"})
    audio_ok = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {audio}"})
    audio_large = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {large_audio}"})
    video_ok = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {video}"})
    video_large = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {large_video}"})
    removed_image = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-image {image}"})
    removed_audio = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-audio {audio}"})

    assert accepted.json()["run"]["status"] == "DONE"
    assert accepted.json()["run"]["target_id"] == "/read-file"
    assert accepted.json()["messages"][-1]["parts"][0]["type"] == "file"
    assert outside.json()["run"]["status"] == "FAILED"
    assert "Path outside allowed directories" in outside.json()["run"]["error"]
    assert "File too large" in too_large.json()["run"]["error"]
    assert "Unsupported file type" in bad_ext.json()["run"]["error"]
    assert image_ok.json()["run"]["status"] == "DONE"
    assert image_ok.json()["messages"][-1]["parts"][0]["type"] == "image"
    assert "File too large" in image_large.json()["run"]["error"]
    assert audio_ok.json()["run"]["status"] == "DONE"
    assert audio_ok.json()["messages"][-1]["parts"][0]["type"] == "audio"
    assert audio_ok.json()["messages"][-1]["parts"][0]["source"] == "attachment"
    assert "File too large" in audio_large.json()["run"]["error"]
    assert video_ok.json()["run"]["status"] == "DONE"
    assert video_ok.json()["messages"][-1]["parts"][0]["type"] == "video"
    assert video_ok.json()["messages"][-1]["parts"][0]["source"] == "attachment"
    assert "File too large" in video_large.json()["run"]["error"]
    assert removed_image.status_code == 400
    assert "Unknown command: /read-image" in removed_image.text
    assert removed_audio.status_code == 400
    assert "Unknown command: /read-audio" in removed_audio.text

    client.patch("/api/capability-configs/file", json={"user_config": {"allowed_directories": [str(allowed)], "enable_read_file_command": False}})
    disabled_file = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {note}"})
    disabled_image = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {image}"})
    disabled_audio = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {audio}"})
    disabled_video = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {video}"})
    assert "Command disabled" in disabled_file.json()["run"]["error"]
    assert "Command disabled" in disabled_image.json()["run"]["error"]
    assert "Command disabled" in disabled_audio.json()["run"]["error"]
    assert "Command disabled" in disabled_video.json()["run"]["error"]

    legacy_audio = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/file-audio {audio}"})
    assert legacy_audio.status_code == 400
    assert "Unknown command: /file-audio" in legacy_audio.text

    client.patch("/api/capability-configs/file", json={"user_config": {"allowed_directories": [], "enable_read_file_command": True}})
    empty_dirs = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": f"/read-file {note}"})
    assert "Path outside allowed directories" in empty_dirs.json()["run"]["error"]


def test_http_capability_config_defaults_patch_and_runtime_enforcement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        timeout = request.extensions.get("timeout") or {}
        if request.url.path == "/timeout":
            return httpx.Response(200, headers={"content-type": "application/json"}, json=timeout, request=request)
        if request.url.path == "/image":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"hello", request=request)
        if request.url.path == "/html":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<h1>Hello</h1><p>Page</p>", request=request)
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
    assert defaults.json()["resolved_config"]["enable_fetch_url_command"] is True

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
    timed = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-url https://example.test/timeout"})
    large_text = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-url https://example.test/large"})
    image = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-url https://example.test/image"})
    html = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-url https://example.test/html"})
    binary = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-url https://example.test/binary"})

    assert timed.json()["run"]["status"] == "DONE"
    assert timed.json()["messages"][-1]["parts"][0]["type"] == "json"
    assert timed.json()["messages"][-1]["parts"][0]["data"]["connect"] == 3.0
    assert "Response too large" in large_text.json()["run"]["error"]
    assert image.json()["messages"][-1]["parts"][0]["type"] == "image"
    assert image.json()["messages"][-1]["parts"][0]["url"].startswith("data:image/png;base64,")
    assert html.json()["messages"][-1]["parts"][0]["type"] == "text"
    assert "Unsupported content type" in binary.json()["run"]["error"]

    client.patch("/api/capability-configs/http", json={"user_config": {"allowed_schemes": ["https"]}})
    scheme = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-url http://example.test/text"})
    assert "Scheme not allowed" in scheme.json()["run"]["error"]

    removed_get = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/http-get https://example.test/text"})
    removed_page = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-page https://example.test/html"})
    removed_image = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-image https://example.test/image"})
    assert removed_get.status_code == 400
    assert removed_page.status_code == 400
    assert removed_image.status_code == 400
    assert "Unknown command: /http-get" in removed_get.text
    assert "Unknown command: /fetch-page" in removed_page.text
    assert "Unknown command: /fetch-image" in removed_image.text

    client.patch("/api/capability-configs/http", json={"user_config": {"enable_fetch_url_command": False}})
    disabled_text = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-url https://example.test/text"})
    disabled_json = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-url https://example.test/timeout"})
    disabled_html = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-url https://example.test/html"})
    disabled_image = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/fetch-url https://example.test/image"})
    assert "Command disabled" in disabled_text.json()["run"]["error"]
    assert "Command disabled" in disabled_json.json()["run"]["error"]
    assert "Command disabled" in disabled_html.json()["run"]["error"]
    assert "Command disabled" in disabled_image.json()["run"]["error"]
