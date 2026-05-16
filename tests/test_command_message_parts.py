import asyncio
from typing import Any

from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.runner import CommandRunner
from ai_workbench.core.schema.capability import CapabilitySchema
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore
from tests.test_api import create_session, make_client, post_message


class OutputRuntime:
    def text(self, args: str) -> str:
        return "plain result"

    def markdown(self, args: str) -> str:
        return "**markdown result**"

    def json(self, args: str) -> dict[str, Any]:
        return {"ok": True}

    def file_content(self, args: str) -> dict[str, Any]:
        return {"filename": "log.txt", "language": "text", "content": "line 1", "truncated": False}

    def image(self, args: str) -> dict[str, Any]:
        return {"url": "/api/attachments/image.png", "alt": "Image"}

    def image_gallery(self, args: str) -> dict[str, Any]:
        return {"images": [{"url": "/api/attachments/a.png", "alt": "A"}]}

    def rich_form(self, args: str) -> dict[str, Any]:
        return [
            {
                "type": "form",
                "form_id": "demo",
                "title": "Demo",
                "fields": [{"name": "prompt", "type": "textarea", "required": True}],
                "submit": {"action_id": "submit"},
            }
        ]

    def rich_buttons(self, args: str) -> list[dict[str, Any]]:
        return [{"type": "command_buttons", "buttons": [{"label": "Run", "message": "@chat hello"}]}]

    def inferred_json(self, args: str) -> dict[str, Any]:
        return {"inferred": True}


def run(coro):
    return asyncio.run(coro)


def make_runner() -> tuple[CommandRunner, SessionStore, MessageStore, EventBus]:
    capability = CapabilitySchema.model_validate(
        {
            "id": "output_demo",
            "name": "Output Demo",
            "methods": [
                {"id": "text", "output": {"part_type": "text", "format": "plain"}},
                {"id": "markdown", "output": {"part_type": "text", "format": "markdown"}},
                {"id": "json", "output": {"part_type": "json"}},
                {"id": "file_content", "output": {"part_type": "file", "mode": "inline_text"}},
                {"id": "image", "output": {"part_type": "image"}},
                {"id": "image_gallery", "output": {"part_type": "media_group", "layout": "gallery"}},
                {"id": "rich_form", "output": {"part_type": "parts"}},
                {"id": "rich_buttons", "output": {"part_type": "parts"}},
                {"id": "inferred_json"},
            ],
            "commands": [
                {"name": "/out-text", "method": "text"},
                {"name": "/out-markdown", "method": "markdown"},
                {"name": "/out-json", "method": "json"},
                {"name": "/out-file", "method": "file_content"},
                {"name": "/out-image", "method": "image"},
                {"name": "/out-gallery", "method": "image_gallery"},
                {"name": "/out-form", "method": "rich_form"},
                {"name": "/out-buttons", "method": "rich_buttons"},
                {"name": "/out-inferred", "method": "inferred_json"},
            ],
        }
    )
    capabilities = CapabilityRegistry()
    capabilities.register(capability)
    commands = CommandRegistry.from_capability_registry(capabilities)
    runtimes = CapabilityRuntimeRegistry()
    runtimes.register("output_demo", OutputRuntime())
    sessions = SessionStore()
    messages = MessageStore(session_store=sessions)
    runs = RunStore()
    events = EventBus()
    runner = CommandRunner(
        command_registry=commands,
        runtime_registry=runtimes,
        run_store=runs,
        message_store=messages,
        event_bus=events,
        capability_registry=capabilities,
    )
    return runner, sessions, messages, events


def command_message(command_name: str):
    runner, sessions, messages, events = make_runner()
    session = sessions.create_session()
    result = run(runner.run(command_name, "", session.session_id))
    assert result.success is True
    message = messages.list_messages(session.session_id)[-1]
    return result, message, events


def test_capability_command_text_output_writes_plain_text_part() -> None:
    result, message, events = command_message("/out-text")

    assert not hasattr(result, "output_type")
    assert message.content_version == 2
    assert message.parts == [{"id": "part_1", "type": "text", "format": "plain", "text": "plain result"}]
    assert not hasattr(message, "content")
    assert not hasattr(message, "output_type")
    assert _completed_message(events)["parts"] == message.parts


def test_capability_command_markdown_output_writes_markdown_text_part() -> None:
    _, message, _ = command_message("/out-markdown")

    assert message.parts[0]["type"] == "text"
    assert message.parts[0]["format"] == "markdown"
    assert not hasattr(message, "content")
    assert not hasattr(message, "output_type")


def test_capability_command_json_output_writes_json_part() -> None:
    _, message, _ = command_message("/out-json")

    assert message.parts == [{"id": "part_1", "type": "json", "data": {"ok": True}}]
    assert not hasattr(message, "content")
    assert not hasattr(message, "output_type")


def test_capability_command_file_content_output_writes_file_part() -> None:
    _, message, _ = command_message("/out-file")

    assert message.parts[0]["type"] == "file"
    assert message.parts[0]["mode"] == "inline_text"
    assert message.parts[0]["content"] == "line 1"
    assert not hasattr(message, "output_type")


def test_capability_command_image_output_writes_image_part() -> None:
    _, message, _ = command_message("/out-image")

    assert message.parts == [{"id": "part_1", "type": "image", "url": "/api/attachments/image.png", "alt": "Image"}]
    assert not hasattr(message, "output_type")


def test_capability_command_image_gallery_output_writes_media_group_part() -> None:
    _, message, _ = command_message("/out-gallery")

    assert message.parts[0]["type"] == "media_group"
    assert message.parts[0]["layout"] == "gallery"
    assert message.parts[0]["items"][0]["url"] == "/api/attachments/a.png"
    assert not hasattr(message, "output_type")


def test_rich_content_action_form_block_writes_form_part() -> None:
    _, message, _ = command_message("/out-form")

    assert message.parts[0]["type"] == "form"
    assert message.parts[0]["form_id"] == "demo"
    assert not hasattr(message, "output_type")
    assert not hasattr(message, "content")


def test_rich_content_command_buttons_block_writes_command_buttons_part() -> None:
    _, message, _ = command_message("/out-buttons")

    assert message.parts == [
        {
            "id": "part_1",
            "type": "command_buttons",
            "buttons": [{"label": "Run", "message": "@chat hello"}],
        }
    ]
    assert not hasattr(message, "output_type")
    assert not hasattr(message, "content")


def test_command_runner_inferred_dict_output_writes_json_part() -> None:
    result, message, _ = command_message("/out-inferred")

    assert not hasattr(result, "output_type")
    assert message.parts == [{"id": "part_1", "type": "json", "data": {"inferred": True}}]
    assert not hasattr(message, "output_type")


def test_session_load_api_response_returns_command_result_parts() -> None:
    client = make_client()
    session = create_session(client)

    payload = post_message(client, session["session_id"], "/base64 hello")
    loaded = client.get(f"/api/sessions/{session['session_id']}/messages").json()

    command_result = payload["messages"][-1]
    loaded_result = loaded[-1]
    assert command_result["content_version"] == 2
    assert command_result["parts"] == [{"id": "part_1", "type": "text", "format": "plain", "text": "aGVsbG8="}]
    assert "content" not in command_result
    assert "output_type" not in command_result
    assert loaded_result["parts"] == command_result["parts"]


def _completed_message(events: EventBus) -> dict[str, Any]:
    completed = [event for event in events.list_events() if event.type == "message_completed"]
    assert completed
    return completed[-1].payload["message"]
