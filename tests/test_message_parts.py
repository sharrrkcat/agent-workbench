import pytest

from ai_workbench.core.message_parts import (
    MessagePartValidationError,
    blocks_to_parts,
    capability_output_to_parts,
    make_file_part,
    make_audio_part,
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
        validate_message_parts([{"type": "video", "url": "x"}])


@pytest.mark.parametrize("part_type", ["video", "diff"])
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


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"type": "audio", "source": "url", "attachment_id": "a", "url": "/api/attachments/a.wav", "mime_type": "audio/wav"}, "literal_error"),
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
