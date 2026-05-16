import pytest

from ai_workbench.core.message_parts import (
    MessagePartValidationError,
    legacy_output_to_parts,
    make_file_part,
    make_json_part,
    make_text_part,
    parts_to_legacy_output,
    validate_message_parts,
)


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
        validate_message_parts([{"type": "audio", "url": "x"}])


def test_file_part_keeps_raw_inline_text() -> None:
    part = make_file_part("a < b", filename="a.txt", language="txt", mime_type="text/plain")

    assert part["type"] == "file"
    assert part["mode"] == "inline_text"
    assert part["content"] == "a < b"


def test_legacy_output_converts_to_parts_and_back() -> None:
    parts = legacy_output_to_parts("image_gallery", {"images": [{"url": "/api/attachments/a.png", "alt": "A"}]})

    assert parts == [
        {
            "id": "part_1",
            "type": "media_group",
            "layout": "gallery",
            "items": [{"type": "image", "url": "/api/attachments/a.png", "alt": "A"}],
        }
    ]
    assert parts_to_legacy_output(parts) == ("image_gallery", {"images": [{"url": "/api/attachments/a.png", "alt": "A"}]})


def test_rich_content_form_converts_to_form_part() -> None:
    parts = legacy_output_to_parts(
        "rich_content",
        {
            "blocks": [
                {
                    "type": "action_form",
                    "form_id": "demo",
                    "title": "Demo",
                    "fields": [{"name": "prompt", "type": "textarea", "required": True}],
                    "submit": {"action_id": "submit"},
                }
            ]
        },
    )

    assert parts[0]["type"] == "form"
    assert parts[0]["form_id"] == "demo"
    assert parts_to_legacy_output(parts)[0] == "rich_content"
