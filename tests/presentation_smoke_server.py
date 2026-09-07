"""Deterministic streaming fixtures for the conversation browser tests."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from fastapi import Body
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.assistant_output import AssistantDraft
from ai_workbench.core.message_parts import make_tool_call_part, make_tool_result_part
from ai_workbench.core.schema.run import RunStatus
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, tool_call
from tests.runtime_browser_fixture import install_runtime_fixture


class FixtureStream(httpx.AsyncByteStream):
    def __init__(self, chunks, finish="stop", delay=0.15, hold=False, fail=False):
        self.chunks, self.finish, self.delay, self.hold, self.fail = chunks, finish, delay, hold, fail

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield self._data({"choices": [{"index": 0, "delta": chunk, "finish_reason": None}]})
        if self.hold:
            await asyncio.Event().wait()
        if self.fail:
            yield self._data({"error": {"message": "Fixture failure"}})
            return
        await asyncio.sleep(self.delay)
        yield self._data({"choices": [{"index": 0, "delta": {}, "finish_reason": self.finish}]})
        yield b"data: [DONE]\n\n"

    @staticmethod
    def _data(value):
        return ("data: " + json.dumps(value) + "\n\n").encode()


class PresentationOpenAI(ToolOpenAI):
    async def handle(self, request):
        if not request.url.path.endswith("/chat/completions"):
            return await super().handle(request)
        data = json.loads(request.content)
        self.calls.append(data)
        history = data["messages"]
        user_index = max(i for i, item in enumerate(history) if item["role"] == "user")
        command = history[user_index]["content"]
        transcript = history[user_index + 1:]
        outputs = [item for item in transcript if item["role"] == "tool"]
        if command == "scroll-output":
            stream = FixtureStream([{"content": f"Paragraph {index}: streamed progress text.\n\n"} for index in range(40)], delay=0.12)
        elif command == "cancel-stream" or command == "fail-stream":
            stream = FixtureStream([{"reasoning_content": "Received reasoning before interruption."},
                                    {"content": "Incomplete streamed answer."}], hold=command == "cancel-stream", fail=command == "fail-stream")
        elif command == "approval" and not outputs:
            stream = FixtureStream([{"reasoning_content": "I will read the requested file."},
                                    {"tool_calls": [{"index": 0, **tool_call("read_file", {"path": "data/knowledge/note.txt"})}]}], "tool_calls")
        elif command == "two-rounds" and len(outputs) < 2:
            index = len(outputs)
            call = tool_call("base64_encode" if index == 0 else "base64_decode", {"value": "hi" if index == 0 else "aGk="}, f"call_{index}")
            stream = FixtureStream([{"reasoning_content": "I will encode first." if index == 0 else "I will decode the encoded text."},
                                    {"content": "Working on the conversion."}, {"tool_calls": [{"index": 0, **call}]}], "tool_calls", delay=0.8)
        elif command == "two-rounds":
            stream = FixtureStream([{"content": "Final result: "}, {"content": "aGk= decodes to hi."}], delay=1)
        else:
            stream = FixtureStream([{"content": "Browser final answer."}])
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=stream)


def create_fixture_app(repository: Path, root: Path):
    upstream = PresentationOpenAI()
    app = create_app(root=root, use_memory=True, adapter_factory=upstream.factory, frontend_dist=repository / "frontend/dist")
    client = TestClient(app)
    profile = configure_model(client, alias="chat-model", capabilities={"streaming": True, "tools": True})
    client.patch("/api/settings/general", json={"auto_generate_session_titles": False}).raise_for_status()
    state = app.state.runtime_state
    install_runtime_fixture(app, root)

    @app.post("/__test__/session")
    async def fixture_session(values: dict = Body(default={})):
        await state.active_runs.cancel_all()
        state.app_settings.patch({"show_full_processing": bool(values.get("show_full_processing", False))})
        session = state.chat_service.create_session({"title": "Presentation fixture", "harness_enabled": True,
                                                     "model_profile_id": profile["id"]})
        if values.get("long_history"):
            config = state.chat_service.resolve(session)
            user = state.messages.add_message(session.session_id, role="user", content="Inspect the conversion results")
            run = state.runs.create_run(kind="chat", persona_id=config.persona_id, session_id=session.session_id,
                                       metadata={"input_message_id": user.message_id, "configuration": config.public_summary()},
                                       config_snapshot=config.model_dump())
            state.runs.update_status(run.run_id, RunStatus.RUNNING)
            draft = AssistantDraft(messages=state.messages, events=state.events, session_id=session.session_id, run_id=run.run_id,
                                   message_id="long-calls-" + run.run_id, config=config, parent_message_id=user.message_id, streamed=False)
            draft.append(reasoning_content="Checking the conversion values.\n\n" * 28)
            draft.persist(extra_parts=[make_tool_call_part(f"long_{i}", "base64_decode", {"value": "aGk="}, part_id=f"call_{i}") for i in range(12)])
            for index in range(12):
                state.messages.add_message(session.session_id, role="tool", run_id=run.run_id,
                    parts=[make_tool_result_part(f"long_{index}", "base64_decode", "success", {"value": "large-result:" + "0123456789" * 500, "rows": list(range(200))})])
            final = AssistantDraft(messages=state.messages, events=state.events, session_id=session.session_id, run_id=run.run_id,
                                   message_id="long-final-" + run.run_id, config=config, parent_message_id=user.message_id, streamed=False)
            final.append("## Conversion result\n\nAll 12 commands completed.\n\n`aGk=` decodes to **hi**.")
            final.persist()
            state.runs.update_status(run.run_id, RunStatus.DONE)
        return state.chat_service.session_response(state.sessions.get_session(session.session_id))

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18767)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="workbench-presentation-") as directory:
        root = Path(directory)
        os.environ["AGENT_WORKBENCH_ATTACHMENTS_DIR"] = str(root / "data/attachments")
        note = root / "data/knowledge/note.txt"
        note.parent.mkdir(parents=True)
        note.write_text("Approved browser fixture result", encoding="utf-8")
        app = create_fixture_app(Path(__file__).resolve().parents[1], root)
        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
