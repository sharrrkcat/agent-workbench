import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_workbench.api.deps import build_runtime_state


LLM_MODEL_HINT = (
    "LLM model is not selected. Set AGENT_WORKBENCH_LLM_MODEL, save an llm model in Settings, "
    "or specify model in the Agent manifest. When using the default memory runtime, SQLite Settings may not be read; "
    "use --use-sqlite to test saved Settings."
)


def parse_target(value: str) -> tuple[str, str]:
    if ":" not in value:
        return value, "default"
    agent_id, action_id = value.split(":", 1)
    return agent_id, action_id or "default"


async def run_agent(
    target: str,
    text: str,
    action: str | None = None,
    use_memory: bool = True,
    json_output: bool = False,
    show_trace: bool = False,
) -> int:
    agent_id, action_id = parse_target(target)
    if action:
        action_id = action
    state = build_runtime_state(root=ROOT, use_memory=use_memory)
    try:
        state.agents.get(agent_id)
    except KeyError:
        payload = {"run": None, "events": [], "messages": [], "result": None, "error": f"Unknown agent: {agent_id}"}
        _emit(payload, json_output=json_output, show_trace=show_trace)
        return 1

    session = state.sessions.create_session(default_agent_id=agent_id)
    result = await state.runtime.invoke_action(
        session_id=session.session_id,
        agent_id=agent_id,
        action_id=action_id,
        input_text=text,
    )

    run = state.runs.get_run(result.run_id) if result.run_id else None
    events = _list_run_events(state, result.run_id) if result.run_id else []
    messages = state.messages.list_messages(session.session_id)
    error = _developer_error(result.error)

    payload = {
        "run": _dump_model(run) if run else None,
        "events": [_dump_model(event) for event in events],
        "messages": [_dump_model(message) for message in messages],
        "result": _dump_model(result),
        "error": error,
    }
    _emit(payload, json_output=json_output, show_trace=show_trace)
    return 0 if result.success else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an Agent from the command line.")
    parser.add_argument("target", help="agent_id or agent_id:action_id")
    parser.add_argument("text", help="input text")
    parser.add_argument("--action", help="action id to invoke")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--show-trace", action="store_true", help="show traceback/debug metadata when present")
    parser.add_argument("--use-memory", action="store_true", default=True, help="use an in-memory runtime")
    parser.add_argument("--use-sqlite", action="store_true", help="use the configured SQLite database")
    args = parser.parse_args(argv)
    return asyncio.run(
        run_agent(
            args.target,
            args.text,
            action=args.action,
            use_memory=not args.use_sqlite,
            json_output=args.json,
            show_trace=args.show_trace,
        )
    )


def _emit(payload: dict[str, Any], json_output: bool, show_trace: bool) -> None:
    if json_output:
        print(json.dumps(_payload_for_json(payload, show_trace=show_trace), ensure_ascii=False, indent=2))
        return
    _print_human(payload, show_trace=show_trace)


def _print_human(payload: dict[str, Any], show_trace: bool) -> None:
    run = payload.get("run")
    print(f"run id: {run.get('run_id') if run else '(none)'}")
    if run:
        print(f"run status: {str(run.get('status', 'failed')).lower()}")
        if run.get("current_step"):
            print(f"current step: {run['current_step']}")
        if run.get("error"):
            print(f"run error: {_developer_error(run['error'])}")
        metadata = run.get("metadata") or {}
        if isinstance(metadata, dict):
            metrics = metadata.get("llm_metrics")
            if metrics:
                print(f"metrics: {json.dumps(metrics, ensure_ascii=False)}")
            reasoning = metadata.get("reasoning")
            if isinstance(reasoning, dict):
                print(f"reasoning: expected={bool(reasoning.get('expected'))} received={bool(reasoning.get('received'))}")
    else:
        print("run status: failed")

    result = payload.get("result") or {}
    if isinstance(result, dict) and result.get("error_code"):
        print(f"error code: {result['error_code']}")
    if payload.get("error"):
        print(f"error: {payload['error']}")

    events = payload.get("events") or []
    if events:
        print("events:")
        for event in events:
            payload_text = json.dumps(_safe_preview(event.get("payload", {})), ensure_ascii=False)
            print(f"- {event.get('type')}: {payload_text}")

    messages = payload.get("messages") or []
    if messages:
        print("messages:")
        for message in messages:
            print(f"- {message.get('role')} [{message.get('output_type')}]:")
            print(_format_content(message.get("content"), message.get("output_type") or "text"))

    if show_trace:
        trace = _trace_from_payload(payload)
        if trace:
            print("traceback:")
            print(trace)


def _payload_for_json(payload: dict[str, Any], show_trace: bool) -> dict[str, Any]:
    if show_trace:
        return payload
    run = payload.get("run")
    if isinstance(run, dict):
        metadata = dict(run.get("metadata") or {})
        metadata.pop("traceback", None)
        if isinstance(metadata.get("debug"), dict):
            debug = dict(metadata["debug"])
            debug.pop("traceback", None)
            metadata["debug"] = debug
        run = {**run, "metadata": metadata}
    return {**payload, "run": run}


def _list_run_events(state: Any, run_id: str) -> list[Any]:
    if hasattr(state.run_events, "list_events"):
        return state.run_events.list_events(run_id)
    return [event for event in state.events.list_events() if event.run_id == run_id]


def _format_content(content: Any, output_type: str) -> str:
    if output_type == "image":
        return _image_summary(content)
    if output_type == "image_gallery":
        images = content.get("images", []) if isinstance(content, dict) else []
        summaries = [_image_summary(image) for image in images[:3]]
        suffix = "" if len(images) <= 3 else f"\n... {len(images) - 3} more image(s)"
        return f"image_gallery: {len(images)} image(s)" + (("\n" + "\n".join(summaries)) if summaries else "") + suffix
    if output_type == "rich_content":
        blocks = content.get("blocks", []) if isinstance(content, dict) else []
        types = [str(block.get("type", "unknown")) for block in blocks if isinstance(block, dict)]
        return f"rich_content: {len(blocks)} block(s); types={', '.join(types) if types else 'none'}"
    if output_type == "file_content":
        if not isinstance(content, dict):
            return str(content)
        body = str(content.get("content") or "")
        label = content.get("filename") or "file"
        language = content.get("language") or "text"
        suffix = " (truncated)" if content.get("truncated") else ""
        return f"file_content: {label} [{language}] {len(body)} chars{suffix}\n{body}"
    if output_type == "json":
        parsed = _parse_json_like(content)
        if isinstance(parsed, (dict, list)):
            return json.dumps(_safe_preview(parsed), ensure_ascii=False, indent=2)
        return str(parsed)
    if isinstance(content, (dict, list)):
        return json.dumps(_safe_preview(content), ensure_ascii=False, indent=2)
    if isinstance(content, str):
        return _unwrap_json_string(content)
    return "" if content is None else str(content)


def _parse_json_like(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    unwrapped = _unwrap_json_string(content)
    try:
        return json.loads(unwrapped)
    except json.JSONDecodeError:
        return unwrapped


def _unwrap_json_string(value: str) -> str:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    return parsed if isinstance(parsed, str) else value


def _image_summary(content: Any) -> str:
    if not isinstance(content, dict):
        return str(content)
    url = str(content.get("url") or "")
    return (
        f"image: mime={_data_url_mime(url) or 'remote/unknown'} "
        f"size={_data_url_size(url) or 'unknown'} url_prefix={url[:32]!r} url_length={len(url)}"
    )


def _safe_preview(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe_preview_value(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_preview(item) for item in value]
    return value


def _safe_preview_value(key: str, value: Any) -> Any:
    if key == "message" and isinstance(value, dict):
        return {
            "message_id": value.get("message_id"),
            "role": value.get("role"),
            "output_type": value.get("output_type"),
            "run_id": value.get("run_id"),
            "content_length": len(str(value.get("content") or "")),
        }
    if isinstance(value, str) and (key in {"url", "data_url", "base64"} or value.startswith("data:image/")):
        return {"prefix": value[:32], "length": len(value)}
    return _safe_preview(value)


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


def _developer_error(error: Any) -> Any:
    if not isinstance(error, str) or not error:
        return error
    if "LLM model is not selected" in error or "LLM model is required" in error or "LLM_MODEL_NOT_SELECTED" in error:
        return f"{error}\n{LLM_MODEL_HINT}"
    return error


def _trace_from_payload(payload: dict[str, Any]) -> str:
    run = payload.get("run") or {}
    metadata = run.get("metadata") if isinstance(run, dict) else {}
    if not isinstance(metadata, dict):
        return ""
    if isinstance(metadata.get("traceback"), str):
        return metadata["traceback"]
    debug = metadata.get("debug")
    if isinstance(debug, dict) and isinstance(debug.get("traceback"), str):
        return debug["traceback"]
    return ""


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
