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


def parse_target(value: str) -> tuple[str, str]:
    if ":" not in value:
        return value, "default"
    agent_id, action_id = value.split(":", 1)
    return agent_id, action_id or "default"


async def run_agent(target: str, text: str, use_memory: bool = True) -> int:
    agent_id, action_id = parse_target(target)
    state = build_runtime_state(root=ROOT, use_memory=use_memory)
    try:
        state.agents.get(agent_id)
    except KeyError:
        print(f"[FAIL] Unknown agent: {agent_id}")
        return 1

    session = state.sessions.create_session(default_agent_id=agent_id)
    result = await state.runtime.invoke_action(
        session_id=session.session_id,
        agent_id=agent_id,
        action_id=action_id,
        input_text=text,
    )

    print(f"run id: {result.run_id or '(none)'}")
    if result.run_id:
        run = state.runs.get_run(result.run_id)
        print(f"run status: {run.status.value.lower()}")
        if run.current_step:
            print(f"current step: {run.current_step}")
        if run.error:
            print(f"run error: {run.error}")
        events = _list_run_events(state, result.run_id)
        if events:
            print("events:")
            for event in events:
                print(f"- {event.type}: {event.payload}")
    else:
        print("run status: failed")

    if result.error:
        print(f"error: {result.error}")

    messages = state.messages.list_messages(session.session_id)
    if messages:
        print("messages:")
        for message in messages:
            content = _format_content(message.content)
            print(f"- {message.role} [{message.output_type}]: {content}")

    return 0 if result.success else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an Agent from the command line.")
    parser.add_argument("target", help="agent_id or agent_id:action_id")
    parser.add_argument("text", help="input text")
    parser.add_argument("--use-memory", action="store_true", default=True, help="use an in-memory runtime")
    parser.add_argument("--use-sqlite", action="store_true", help="use the configured SQLite database")
    args = parser.parse_args(argv)
    return asyncio.run(run_agent(args.target, args.text, use_memory=not args.use_sqlite))


def _list_run_events(state: Any, run_id: str) -> list[Any]:
    if hasattr(state.run_events, "list_events"):
        return state.run_events.list_events(run_id)
    return [event for event in state.events.list_events() if event.run_id == run_id]


def _format_content(content: Any) -> str:
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


if __name__ == "__main__":
    raise SystemExit(main())
