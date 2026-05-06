import argparse
import asyncio
import base64
import json
import mimetypes
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_workbench.api.deps import build_runtime_state


async def run_command(
    raw_command: str,
    image_path: str | None = None,
    use_memory: bool = True,
    json_output: bool = False,
) -> int:
    command_name, args = _parse_command(raw_command)
    if not command_name:
        payload = {"run": None, "events": [], "messages": [], "error": "Command input must start with '/'."}
        _emit(payload, json_output=json_output)
        return 1

    state = build_runtime_state(root=ROOT, use_memory=use_memory)
    session = state.sessions.create_session()
    input_message_id = ""

    try:
        attachments = [_load_image_attachment(Path(image_path))] if image_path else []
    except Exception as exc:
        payload = {"run": None, "events": [], "messages": [], "error": str(exc)}
        _emit(payload, json_output=json_output)
        return 1

    if attachments:
        user = state.messages.add_message(
            session_id=session.session_id,
            role="user",
            content=raw_command,
            metadata={"attachments": attachments},
        )
        input_message_id = user.message_id
    result = await state.command_runner.run(command_name, args, session.session_id, input_message_id=input_message_id)

    run = state.runs.get_run(result.run_id) if result.run_id else None
    events = _list_run_events(state, result.run_id) if result.run_id else []
    messages = state.messages.list_messages(session.session_id)
    payload = {
        "run": _dump_model(run) if run else None,
        "events": [_dump_model(event) for event in events],
        "messages": [_dump_model(message) for message in messages],
        "result": _dump_model(result),
        "error": result.error,
    }
    _emit(payload, json_output=json_output)
    return 0 if result.success else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a slash Command from the command line.")
    parser.add_argument("command", help='full command text, for example "/base64 hello"')
    parser.add_argument("--image", help="attach a local image to the current user message")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--use-memory", action="store_true", default=True, help="use an in-memory runtime")
    parser.add_argument("--use-sqlite", action="store_true", help="use the configured SQLite database")
    args = parser.parse_args(argv)
    return asyncio.run(
        run_command(
            args.command,
            image_path=args.image,
            use_memory=not args.use_sqlite,
            json_output=args.json,
        )
    )


def _parse_command(raw_command: str) -> tuple[str, str]:
    value = (raw_command or "").strip()
    if not value.startswith("/"):
        return "", ""
    parts = value.split(maxsplit=1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_human(payload)


def _print_human(payload: dict[str, Any]) -> None:
    run = payload.get("run")
    result = payload.get("result") or {}
    print(f"run id: {run.get('run_id') if run else '(none)'}")
    if run:
        print(f"run status: {str(run.get('status', 'failed')).lower()}")
        if run.get("current_step"):
            print(f"current step: {run['current_step']}")
        if run.get("error"):
            print(f"run error: {run['error']}")
    else:
        print("run status: failed")

    output_type = result.get("output_type") or _last_output_type(payload)
    print(f"output_type: {output_type}")

    if payload.get("error"):
        print(f"error: {payload['error']}")

    events = payload.get("events") or []
    if events:
        print("events:")
        for event in events:
            event_payload = json.dumps(_safe_preview(event.get("payload", {})), ensure_ascii=False)
            print(f"- {event.get('type')}: {event_payload}")

    messages = payload.get("messages") or []
    command_messages = [item for item in messages if item.get("role") == "command"]
    if command_messages:
        message = command_messages[-1]
        print("content:")
        print(_format_content(message.get("content"), message.get("output_type") or output_type))


def _last_output_type(payload: dict[str, Any]) -> str:
    for message in reversed(payload.get("messages") or []):
        if message.get("role") == "command":
            return message.get("output_type") or "text"
    return "text"


def _format_content(content: Any, output_type: str) -> str:
    if output_type == "json":
        return json.dumps(_safe_preview(content), ensure_ascii=False, indent=2)
    if output_type == "image":
        return _image_summary(content)
    if output_type == "image_gallery":
        images = content.get("images", []) if isinstance(content, dict) else []
        return f"image_gallery: {len(images)} image(s)"
    if output_type == "rich_content":
        blocks = content.get("blocks", []) if isinstance(content, dict) else []
        return f"rich_content: {len(blocks)} block(s)"
    if isinstance(content, (dict, list)):
        return json.dumps(_safe_preview(content), ensure_ascii=False, indent=2)
    return "" if content is None else str(content)


def _image_summary(content: Any) -> str:
    if not isinstance(content, dict):
        return str(content)
    url = str(content.get("url") or "")
    mime = _data_url_mime(url)
    return (
        f"image: mime={mime or 'unknown'} size={_data_url_size(url) or 'unknown'} "
        f"url_prefix={url[:32]!r} url_length={len(url)}"
    )


def _safe_preview(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe_preview_url(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_preview(item) for item in value]
    return value


def _safe_preview_url(key: str, value: Any) -> Any:
    if isinstance(value, str) and (key in {"url", "data_url", "base64"} or value.startswith("data:image/")):
        return {"prefix": value[:32], "length": len(value)}
    return _safe_preview(value)


def _load_image_attachment(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"Image file not found: {path}")
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not mime_type.startswith("image/"):
        raise ValueError(f"File is not an image: {path}")
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "id": path.name,
        "type": "image",
        "mime_type": mime_type,
        "name": path.name,
        "size": len(data),
        "data_url": f"data:{mime_type};base64,{encoded}",
    }


def _data_url_mime(url: str) -> str:
    if not url.startswith("data:") or ";base64," not in url:
        return ""
    return url.split(";", 1)[0].removeprefix("data:")


def _data_url_size(url: str) -> int | None:
    if ";base64," not in url:
        return None
    raw = url.split(",", 1)[1]
    padding = raw.count("=")
    return max(0, (len(raw) * 3) // 4 - padding)


def _list_run_events(state: Any, run_id: str) -> list[Any]:
    if hasattr(state.run_events, "list_events"):
        return state.run_events.list_events(run_id)
    return [event for event in state.events.list_events() if event.run_id == run_id]


def _dump_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value


if __name__ == "__main__":
    raise SystemExit(main())
