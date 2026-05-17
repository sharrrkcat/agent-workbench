import pytest

from ai_workbench.core.message_parts import (
    MessagePartValidationError,
    blocks_to_parts,
    capability_output_to_parts,
    make_file_part,
    make_audio_part,
    make_video_part,
    make_text_part,
    validate_message_parts,
)
from ai_workbench.core.schema.capability import CapabilitySchema


def test_text_and_json_parts_validate() -> None:
    parts = validate_message_parts(
        [
            {"type": "text", "format": "markdown", "text": "hello"},
            {"type": "json", "data": {"ok": True}},
        ]
    )

    assert parts == [
        {"id": "part_1", "type": "text", "format": "markdown", "text": "hello"},
        {"id": "part_2", "type": "json", "data": {"ok": True}},
    ]


def test_invalid_part_type_fails_clearly() -> None:
    with pytest.raises(MessagePartValidationError, match="unsupported message part type"):
        validate_message_parts([{"type": "diff", "url": "x"}])


@pytest.mark.parametrize("part_type", ["diff", "chart"])
def test_future_part_types_are_rejected(part_type: str) -> None:
    with pytest.raises(MessagePartValidationError, match="unsupported message part type"):
        validate_message_parts([{"type": part_type, "url": "x"}])


def test_file_part_keeps_raw_inline_text() -> None:
    part = make_file_part("a < b", filename="a.txt", language="txt", mime_type="text/plain")

    assert part["type"] == "file"
    assert part["mode"] == "inline_text"
    assert part["content"] == "a < b"


def test_audio_part_accepts_attachment_source() -> None:
    part = make_audio_part(
        attachment_id="att-1",
        url="/api/attachments/att-1.wav",
        mime_type="audio/wav",
        filename="demo.wav",
        title="Demo audio",
        duration_ms=500,
    )

    assert part == {
        "id": "part_1",
        "type": "audio",
        "source": "attachment",
        "attachment_id": "att-1",
        "url": "/api/attachments/att-1.wav",
        "mime_type": "audio/wav",
        "filename": "demo.wav",
        "title": "Demo audio",
        "duration_ms": 500,
    }


def test_audio_part_accepts_url_source() -> None:
    parts = validate_message_parts(
        [
            {
                "type": "audio",
                "source": "url",
                "url": "https://example.test/demo.mp3",
                "mime_type": "audio/mpeg",
                "filename": "demo.mp3",
                "title": "demo.mp3",
                "duration_ms": 0,
                "size_bytes": 123,
            }
        ]
    )

    assert parts == [
        {
            "id": "part_1",
            "type": "audio",
            "source": "url",
            "url": "https://example.test/demo.mp3",
            "mime_type": "audio/mpeg",
            "filename": "demo.mp3",
            "title": "demo.mp3",
            "duration_ms": 0,
            "size_bytes": 123,
        }
    ]


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"type": "audio", "source": "attachment", "url": "/api/attachments/a.wav", "mime_type": "audio/wav"}, "attachment_id"),
        ({"type": "audio", "source": "attachment", "attachment_id": "a", "mime_type": "audio/wav"}, "url"),
        ({"type": "audio", "source": "attachment", "attachment_id": "a", "url": "/api/attachments/a.txt", "mime_type": "text/plain"}, "audio/\\*"),
        ({"type": "audio", "source": "attachment", "attachment_id": "a", "url": "/api/attachments/a.wav", "mime_type": "audio/wav", "duration_ms": -1}, "greater than or equal"),
    ],
)
def test_audio_part_rejects_invalid_payloads(payload: dict, error: str) -> None:
    with pytest.raises(MessagePartValidationError, match=error):
        validate_message_parts([payload])


@pytest.mark.parametrize("url", ["http://example.test/a.wav", "https://example.test/a.wav", "file:///tmp/a.wav", "data:audio/wav;base64,AAAA", "javascript:alert(1)"])
def test_audio_part_rejects_non_local_urls(url: str) -> None:
    with pytest.raises(MessagePartValidationError, match="local attachment URL|/api/attachments"):
        validate_message_parts([{"type": "audio", "source": "attachment", "attachment_id": "a", "url": url, "mime_type": "audio/wav"}])


@pytest.mark.parametrize("url", ["file:///tmp/a.wav", "data:audio/wav;base64,AAAA", "javascript:alert(1)", "blob:https://example.test/id", "/api/attachments/a.wav"])
def test_audio_part_url_source_rejects_non_http_urls(url: str) -> None:
    with pytest.raises(MessagePartValidationError, match="http:// or https://"):
        validate_message_parts([{"type": "audio", "source": "url", "url": url, "mime_type": "audio/wav"}])


def test_audio_part_url_source_rejects_non_audio_mime() -> None:
    with pytest.raises(MessagePartValidationError, match="audio/\\*"):
        validate_message_parts([{"type": "audio", "source": "url", "url": "https://example.test/a.wav", "mime_type": "text/plain"}])


def test_audio_part_url_source_rejects_attachment_id() -> None:
    with pytest.raises(MessagePartValidationError, match="must not include attachment_id"):
        validate_message_parts([{"type": "audio", "source": "url", "attachment_id": "a", "url": "https://example.test/a.wav", "mime_type": "audio/wav"}])


@pytest.mark.parametrize("source", ["stream", "hls", "dash", "rss"])
def test_audio_part_rejects_unsupported_sources(source: str) -> None:
    with pytest.raises(MessagePartValidationError, match="literal_error"):
        validate_message_parts([{"type": "audio", "source": source, "url": "https://example.test/a.wav", "mime_type": "audio/wav"}])


def test_video_part_accepts_attachment_source() -> None:
    part = make_video_part(
        attachment_id="att-1",
        url="/api/attachments/att-1.mp4",
        mime_type="video/mp4",
        filename="demo.mp4",
        title="Demo video",
        size_bytes=123,
        duration_ms=500,
        width=1920,
        height=1080,
    )

    assert part == {
        "id": "part_1",
        "type": "video",
        "source": "attachment",
        "attachment_id": "att-1",
        "url": "/api/attachments/att-1.mp4",
        "mime_type": "video/mp4",
        "filename": "demo.mp4",
        "title": "Demo video",
        "size_bytes": 123,
        "duration_ms": 500,
        "width": 1920,
        "height": 1080,
    }


def test_video_part_accepts_url_source() -> None:
    parts = validate_message_parts(
        [
            {
                "type": "video",
                "source": "url",
                "url": "https://example.test/demo.mp4",
                "mime_type": "video/mp4",
                "filename": "demo.mp4",
                "title": "demo.mp4",
                "duration_ms": 0,
                "size_bytes": 123,
                "width": 1920,
                "height": 1080,
            }
        ]
    )

    assert parts == [
        {
            "id": "part_1",
            "type": "video",
            "source": "url",
            "url": "https://example.test/demo.mp4",
            "mime_type": "video/mp4",
            "filename": "demo.mp4",
            "title": "demo.mp4",
            "size_bytes": 123,
            "duration_ms": 0,
            "width": 1920,
            "height": 1080,
        }
    ]


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"type": "video", "source": "url", "attachment_id": "a", "url": "https://example.test/a.mp4", "mime_type": "video/mp4"}, "must not include attachment_id"),
        ({"type": "video", "source": "attachment", "url": "/api/attachments/a.mp4", "mime_type": "video/mp4"}, "attachment_id"),
        ({"type": "video", "source": "attachment", "attachment_id": "a", "mime_type": "video/mp4"}, "url"),
        ({"type": "video", "source": "attachment", "attachment_id": "a", "url": "/api/attachments/a.mp4", "mime_type": "text/plain"}, "video/\\*"),
        ({"type": "video", "source": "attachment", "attachment_id": "a", "url": "/api/attachments/a.mp4", "mime_type": "video/mp4", "size_bytes": -1}, "greater than or equal"),
        ({"type": "video", "source": "attachment", "attachment_id": "a", "url": "/api/attachments/a.mp4", "mime_type": "video/mp4", "duration_ms": -1}, "greater than or equal"),
        ({"type": "video", "source": "attachment", "attachment_id": "a", "url": "/api/attachments/a.mp4", "mime_type": "video/mp4", "width": 0}, "greater than or equal"),
        ({"type": "video", "source": "attachment", "attachment_id": "a", "url": "/api/attachments/a.mp4", "mime_type": "video/mp4", "height": 0}, "greater than or equal"),
        ({"type": "video", "source": "attachment", "attachment_id": "a", "url": "/api/attachments/a.mp4", "mime_type": "video/mp4", "poster_url": "https://example.test/poster.png"}, "local attachment URL"),
    ],
)
def test_video_part_rejects_invalid_payloads(payload: dict, error: str) -> None:
    with pytest.raises(MessagePartValidationError, match=error):
        validate_message_parts([payload])


@pytest.mark.parametrize("url", ["http://example.test/a.mp4", "https://example.test/a.mp4", "file:///tmp/a.mp4", "data:video/mp4;base64,AAAA", "javascript:alert(1)"])
def test_video_part_rejects_non_local_urls(url: str) -> None:
    with pytest.raises(MessagePartValidationError, match="local attachment URL|/api/attachments"):
        validate_message_parts([{"type": "video", "source": "attachment", "attachment_id": "a", "url": url, "mime_type": "video/mp4"}])


@pytest.mark.parametrize("url", ["file:///tmp/a.mp4", "data:video/mp4;base64,AAAA", "javascript:alert(1)", "blob:https://example.test/id", "/api/attachments/a.mp4"])
def test_video_part_url_source_rejects_non_http_urls(url: str) -> None:
    with pytest.raises(MessagePartValidationError, match="http:// or https://"):
        validate_message_parts([{"type": "video", "source": "url", "url": url, "mime_type": "video/mp4"}])


def test_video_part_url_source_rejects_non_video_mime() -> None:
    with pytest.raises(MessagePartValidationError, match="video/\\*"):
        validate_message_parts([{"type": "video", "source": "url", "url": "https://example.test/a.mp4", "mime_type": "text/plain"}])


@pytest.mark.parametrize("source", ["stream", "hls", "dash", "youtube", "page"])
def test_video_part_rejects_unsupported_sources(source: str) -> None:
    with pytest.raises(MessagePartValidationError, match="literal_error"):
        validate_message_parts([{"type": "video", "source": source, "url": "https://example.test/a.mp4", "mime_type": "video/mp4"}])


def test_capability_media_group_output_converts_to_parts() -> None:
    parts = capability_output_to_parts(
        {"part_type": "media_group", "layout": "gallery"},
        {"images": [{"url": "/api/attachments/a.png", "alt": "A"}]},
    )

    assert parts == [
        {
            "id": "part_1",
            "type": "media_group",
            "layout": "gallery",
            "items": [{"type": "image", "url": "/api/attachments/a.png", "alt": "A"}],
        }
    ]


def test_capability_audio_output_converts_to_audio_part() -> None:
    parts = capability_output_to_parts(
        {"part_type": "audio"},
        {"source": "attachment", "attachment_id": "att-1", "url": "/api/attachments/att-1.mp3", "mime_type": "audio/mpeg"},
    )

    assert parts[0]["type"] == "audio"
    assert parts[0]["source"] == "attachment"


def test_capability_video_output_converts_to_video_part() -> None:
    parts = capability_output_to_parts(
        {"part_type": "video"},
        {"source": "attachment", "attachment_id": "att-1", "url": "/api/attachments/att-1.mp4", "mime_type": "video/mp4"},
    )

    assert parts[0]["type"] == "video"
    assert parts[0]["source"] == "attachment"


def test_reply_blocks_input_converts_immediately_to_parts() -> None:
    parts = blocks_to_parts(
        [
            {
                "type": "action_form",
                "form_id": "demo",
                "title": "Demo",
                "fields": [{"name": "prompt", "type": "textarea", "required": True}],
                "submit": {"action_id": "submit"},
            }
        ]
    )

    assert parts[0]["type"] == "form"
    assert parts[0]["form_id"] == "demo"


def test_manifest_output_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="output.type is not supported"):
        CapabilitySchema.model_validate(
            {
                "id": "bad",
                "name": "Bad",
                "methods": [{"id": "run", "output": {"type": "json"}}],
            }
        )


def test_manifest_output_part_type_accepts_video() -> None:
    capability = CapabilitySchema.model_validate(
        {
            "id": "video_cap",
            "name": "Video Cap",
            "methods": [{"id": "run", "output": {"part_type": "video"}}],
        }
    )

    assert capability.methods[0].output["part_type"] == "video"
