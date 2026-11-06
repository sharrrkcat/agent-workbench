"""Deterministic streaming fixtures for the conversation browser tests."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from io import BytesIO
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from PIL import Image
import uvicorn
from fastapi import Body
from fastapi.testclient import TestClient

from tests.tool_fixtures import create_tool_app as create_app
from ai_workbench.core.assistant_output import AssistantDraft
from ai_workbench.core.message_parts import make_tool_call_part, make_tool_result_part
from ai_workbench.core.schema.run import RunStatus
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, register_approval_tool, tool_call
from tests.runtime_browser_fixture import install_runtime_fixture
from tests.qq_browser_fixture import install_qq_fixture
from tests.web_tools_browser_fixture import WEB_URL, install_web_fixture
from ai_workbench.core.web_schemas import WebToolsSettingsPatch


class FixtureStream(httpx.AsyncByteStream):
    def __init__(self, chunks, finish="stop", delay=0.15, hold=False, fail=False, prompt_tokens=20):
        self.chunks, self.finish, self.delay, self.hold, self.fail = chunks, finish, delay, hold, fail
        self.prompt_tokens = prompt_tokens

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
        if self.prompt_tokens is not None:
            yield self._data({"choices": [], "usage": {"prompt_tokens": self.prompt_tokens, "completion_tokens": 10, "total_tokens": self.prompt_tokens + 10,
                "prompt_tokens_details": {"cached_tokens": 4}, "completion_tokens_details": {"reasoning_tokens": 3}}})
        yield b"data: [DONE]\n\n"

    @staticmethod
    def _data(value):
        return ("data: " + json.dumps(value) + "\n\n").encode()


class PresentationOpenAI(ToolOpenAI):
    def __init__(self):
        super().__init__()
        self.loop_rounds = {}

    async def handle(self, request):
        if request.url.path.endswith("/images/generations"):
            payload = json.loads(request.content)
            if payload['prompt'] == 'hold-image':
                await asyncio.Event().wait()
            await asyncio.sleep(.8)
            if payload['prompt'] == 'fail-image':
                return httpx.Response(500, json={'error': {'message': 'Fixture image generation failed'}})
            output = BytesIO()
            Image.new('RGB', (640, 480), '#4e8db0').save(output, 'PNG')
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(output.getvalue()).decode()}]})
        if not request.url.path.endswith("/chat/completions"):
            return await super().handle(request)
        data = json.loads(request.content)
        self.calls.append(data)
        from ai_workbench.core.compaction_generation import SUMMARY_INSTRUCTION, RUN_SUMMARY_INSTRUCTION
        if data['messages'][0]['content'] in {SUMMARY_INSTRUCTION, RUN_SUMMARY_INSTRUCTION}:
            if 'HOLD_COMPACTION' in data['messages'][1]['content']:
                await self.compaction_release.wait()
            await asyncio.sleep(1)
            if 'FAIL_COMPACTION' in data['messages'][1]['content']:
                return httpx.Response(200, json={'choices': [{'index': 0, 'message': {
                    'role': 'assistant', 'content': ''}, 'finish_reason': 'length'}]})
            return httpx.Response(200, json={'choices': [{'index': 0, 'message': {
                'role': 'assistant', 'content': '## Confirmed facts\nThe budget is 42 EUR. Do not send email.'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1400, 'completion_tokens': 24, 'total_tokens': 1424}})
        history = data["messages"]
        user_index = max(i for i, item in enumerate(history) if item["role"] == "user" and not (
            isinstance(item["content"], str) and item["content"].startswith(("[Historical summary;", "[Current run summary;"))))
        command = history[user_index]["content"]
        if isinstance(command, list):
            command = "".join(part["text"] for part in command if part["type"] == "text")
        transcript = history[user_index + 1:]
        outputs = [item for item in transcript if item["role"] == "tool"]
        if command.startswith("history-retrieval-fixture"):
            number = self.loop_rounds.get(command, 0)
            self.loop_rounds[command] = number + 1
            if number == 0:
                source = re.search(r"Current input: (message:[\w-]+)", json.dumps(history))[1]
                call = tool_call('context_checkpoint_update', {'scope': 'memory', 'text': 'Budget: 47 EUR.', 'references': [source]}, 'remember')
            elif number < 5:
                call = tool_call('test_echo', {'value': 'Budget: 47 EUR. ' + 'padding ' * 1800}, f'history_{number}')
            elif number == 5:
                call = tool_call('context_read', {'source_id': 'call:history_1', 'max_tokens': 100}, 'recall')
            else:
                assert '47 EUR' in history[-1]['content']
                call = None
            stream = (FixtureStream([{'tool_calls': [{'index': 0, **call}]}], 'tool_calls', delay=.01)
                if call else FixtureStream([{'content': 'Recovered budget: 47 EUR.'}], delay=.01))
        elif command.startswith("loop-compaction-fixture"):
            number = self.loop_rounds.get(command, 0)
            self.loop_rounds[command] = number + 1
            stream = FixtureStream([{"tool_calls": [{"index": 0, **tool_call("test_echo", {
                "value": "The budget is 42 EUR. Do not send email. " + "padding " * 450}, f"loop_{number}")}]}],
                "tool_calls", delay=.02) if number < 4 else FixtureStream([{"content": "Browser final answer."}])
        elif "qq-compaction-fixture" in command:
            stream = FixtureStream([{"tool_calls": [{"index": 0, **tool_call("qq_send_message", {"text": "Budget noted: 42 EUR."})}]}],
                "tool_calls", delay=.02)
        elif "qq-resource-image-fixture" in command:
            runtime = next(item['content'] for item in history if item['role'] == 'system' and 'Favorite image candidates: ' in item['content'])
            candidate = json.loads(runtime.split('Favorite image candidates: ', 1)[1].split('\n', 1)[0])[0]
            stream = FixtureStream([{'tool_calls': [{'index': 0, **tool_call('qq_send_image', {'asset_id': candidate['asset_id']})}]}],
                'tool_calls', delay=.01)
        elif "qq-image-" in command:
            prompt = 'hold-image' if 'qq-image-hold-fixture' in command else 'fail-image' if 'qq-image-failure-fixture' in command else 'Browser generated image'
            chunks = [{'tool_calls': [{'index': 0, **tool_call('qq_generate_image', {'prompt': prompt})}]}] if not outputs else [
                {'tool_calls': [{'index': 0, **tool_call('qq_send_message', {'text': 'Image generation failed; here is a text reply.'}, 'text_reply')}]}]
            stream = FixtureStream(chunks, 'tool_calls', delay=.01)
        elif "qq-web-" in command:
            failed = "qq-web-failure-fixture" in command
            if not outputs:
                call = tool_call("web_search", {"searches": [{"query": "web-failure" if failed else "fixture query"}]}, "qq_search")
            elif len(outputs) == 1 and not failed:
                call = tool_call("web_fetch", {"url": WEB_URL}, "qq_fetch")
            else:
                call = tool_call("qq_send_message", {"text": "Search unavailable; here is a reply." if failed else
                    "Here are the current facts from the web."}, "qq_reply")
            stream = FixtureStream([{"tool_calls": [{"index": 0, **call}]}], "tool_calls", delay=.01)
        elif "qq-limit-fixture" in command:
            calls = [{"index": index, **tool_call("qq_send_message", {"text": f"Limited QQ reply {index + 1}"}, f"call_{index}")}
                     for index in range(21)]
            stream = FixtureStream([{"tool_calls": calls}], "tool_calls", delay=.01)
        elif "qq-missing-fixture" in command:
            stream = FixtureStream([{"content": "This reply was never sent to QQ"}], delay=.01)
        elif "qq-skip-fixture" in command:
            stream = FixtureStream([{"tool_calls": [{"index": 0, **tool_call("qq_skip_reply", "{}")}]}], "tool_calls", delay=.01)
        elif "qq-fixture" in command:
            chunks = [{"tool_calls": [{"index": 0, **tool_call("qq_send_message", {"text": "Confirmed QQ reply"})}]}] if not outputs else [{"content": "Internal QQ prose"}]
            stream = FixtureStream(chunks, "tool_calls" if not outputs else "stop", delay=.01)
        elif command.startswith("web-"):
            if command == "web-no-call":
                stream = FixtureStream([{"content": "Unknown [W1] in this reply."}])
            elif not outputs:
                searches = ([{"query": "fixture query", "recency": "month"}, {"query": "web-failure"}]
                            if command == "web-partial" else [{"query": command if command != "web-research" else "fixture query"}])
                stream = FixtureStream([{"tool_calls": [{"index": 0, **tool_call("web_search",
                    {"searches": searches}, "web_search_call")}]}], "tool_calls")
            elif command != "web-research":
                stream = FixtureStream([{"content": "Search finished without usable sources."}])
            elif len(outputs) == 1:
                stream = FixtureStream([{"tool_calls": [{"index": 0, **tool_call("web_fetch", {"url": WEB_URL}, "web_fetch_call")}]}], "tool_calls")
            else:
                stream = FixtureStream([{"content": "Evidence ["}, {"content": "W1"}, {"content": "] and repeated [W1]. "},
                    {"content": "Reference [W2].\n\nCode `[W1]` stays literal."}], delay=.4)
        elif command in {"context-usage", "context-no-usage"}:
            stream = FixtureStream([{"content": "Context meter answer."}], delay=1,
                prompt_tokens=8126 if command == "context-usage" else None)
        elif command == "scroll-output":
            stream = FixtureStream([{"content": f"Paragraph {index}: streamed progress text.\n\n"} for index in range(40)], delay=0.12)
        elif command in {"reasoning-live", "reasoning-cancel"}:
            chunks = [{"reasoning_content": "Reasoning beginning.  \nSecond line.  \nThird line.  \nFourth line.  \n"}]
            chunks += [{"reasoning_content": f"Latest reasoning {index}.  \n"} for index in range(8)]
            if command == "reasoning-live":
                chunks += [{"content": "Reasoning finished."}, {"content": " The answer"}, {"content": " is ready."}, {"content": " Final answer."}]
            stream = FixtureStream(chunks, delay=0.8, hold=command == "reasoning-cancel")
        elif command == "cancel-stream" or command == "fail-stream":
            stream = FixtureStream([{"reasoning_content": "Received reasoning before interruption."},
                                    {"content": "Incomplete streamed answer."}], hold=command == "cancel-stream", fail=command == "fail-stream")
        elif command == "approval" and not outputs:
            stream = FixtureStream([{"reasoning_content": "I will run the requested test tool."},
                                    {"tool_calls": [{"index": 0, **tool_call("test_approval", {"value": "confirm"})}]}], "tool_calls")
        elif command == "two-rounds" and len(outputs) < 2:
            index = len(outputs)
            call = tool_call("test_echo" if index == 0 else "test_other", {"value": "hi" if index == 0 else "aGk="}, f"call_{index}")
            stream = FixtureStream([{"reasoning_content": "I will encode first." if index == 0 else "I will decode the encoded text."},
                                    {"content": "Working on the conversion."}, {"tool_calls": [{"index": 0, **call}]}], "tool_calls", delay=0.8)
        elif command == "two-rounds":
            stream = FixtureStream([{"content": "Final result: "}, {"content": "aGk= decodes to hi."}], delay=1)
        else:
            stream = FixtureStream([{"content": "Browser final answer."}])
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=stream)


def create_fixture_app(repository: Path, root: Path):
    upstream = PresentationOpenAI()
    app = create_app(root=root, database_url=f"sqlite:///{root / 'browser.db'}", adapter_factory=upstream.factory,
        frontend_dist=repository / "frontend/dist")
    client = TestClient(app)
    profile = configure_model(client, alias="chat-model", request_options={"streaming": True})
    configure_model(client, kind="embedding", alias="resource-embedding", parameters={"dimensions": 2})
    client.patch("/api/settings/general", json={"auto_generate_session_titles": False}).raise_for_status()
    state = app.state.runtime_state
    register_approval_tool(state.tool_registry, content="Approved browser fixture result")
    install_runtime_fixture(app, root)
    install_qq_fixture(app)
    install_web_fixture(app)
    from ai_workbench.core.schema.character import COGITA_CHARACTER_ID
    state.character_service.update(COGITA_CHARACTER_ID, {"model_profile_id": profile["id"],
        "tools_allowed": [tool.name for tool in state.tool_registry.list() if tool.scope == "general"]})

    @app.post("/__test__/session")
    async def fixture_session(values: dict = Body(default={})):
        await state.active_runs.cancel_all()
        upstream.loop_rounds.clear()
        upstream.compaction_release = asyncio.Event()
        state.model_profiles.update(profile['id'], {'context_window_tokens': 4096 if values.get('compaction') or values.get('loop_compaction') else profile['context_window_tokens']})
        state.app_settings.patch({"show_full_processing": bool(values.get("show_full_processing", False))})
        if values.get("web_tools"):
            state.web_tools.settings.patch(WebToolsSettingsPatch(api_key="browser-web-key"))
        session = state.chat_service.create_session(COGITA_CHARACTER_ID, {"title": "Presentation fixture", "overrides": {"harness_enabled": True,
                                                     "model_profile_id": profile["id"]}})
        if values.get('history_retrieval'):
            state.model_profiles.update(profile['id'], {'context_window_tokens': 8192})
            session = state.chat_service.update_session(session.session_id, {'overrides': {'tools_allowed': ['test_echo'],
                'context_policy': {'strategy': 'history_retrieval', 'retrieval': {
                    'trigger_percent': 40, 'target_percent': 25, 'max_checkpoint_tokens': 512}}}})
        if values.get("loop_compaction"):
            session = state.chat_service.update_session(session.session_id, {'overrides': {'tools_allowed': ['test_echo'],
                'context_policy': {'history_enabled': False, 'compaction': {
                    'trigger_percent': 70, 'target_percent': 45, 'max_summary_tokens': 512}}}})
        if values.get("compaction"):
            session = state.chat_service.update_session(session.session_id, {'overrides': {'harness_enabled': False,
                'context_policy': {'compaction': {'trigger_percent': 50, 'target_percent': 35, 'max_summary_tokens': 512}}}})
            for index in range(14):
                marker = {'hold': 'HOLD_COMPACTION ', 'fail': 'HOLD_COMPACTION FAIL_COMPACTION '}.get(values.get('compaction'), '')
                user = state.messages.add_message(session.session_id, 'user', marker + 'The budget is 42 EUR. Do not send email. ' + 'Background information. ' * 85)
                state.messages.add_message(session.session_id, 'assistant', 'Recorded.', parent_message_id=user.message_id)
        if values.get("long_history"):
            config = state.chat_service.resolve(session)
            user = state.messages.add_message(session.session_id, role="user", content="Inspect the conversion results")
            run = state.runs.create_run(kind="chat", persona_id=config.persona_id, session_id=session.session_id,
                                       metadata={"input_message_id": user.message_id, "configuration": config.public_summary()},
                                       config_snapshot=config.model_dump(), character_id=config.character_id)
            state.runs.update_status(run.run_id, RunStatus.RUNNING)
            draft = AssistantDraft(messages=state.messages, events=state.events, session_id=session.session_id, run_id=run.run_id,
                                   message_id="long-calls-" + run.run_id, config=config, parent_message_id=user.message_id, streamed=False)
            draft.append(reasoning_content="Checking the conversion values.\n\n" * 28)
            draft.persist(extra_parts=[make_tool_call_part(f"long_{i}", "test_other", {"value": "aGk="}, part_id=f"call_{i}") for i in range(12)])
            for index in range(12):
                state.messages.add_message(session.session_id, role="tool", run_id=run.run_id,
                    parts=[make_tool_result_part(f"long_{index}", "test_other", "success", {"value": "large-result:" + "0123456789" * 500, "rows": list(range(200))})])
            final = AssistantDraft(messages=state.messages, events=state.events, session_id=session.session_id, run_id=run.run_id,
                                   message_id="long-final-" + run.run_id, config=config, parent_message_id=user.message_id, streamed=False)
            final.append("## Conversion result\n\nAll 12 commands completed.\n\n`aGk=` decodes to **hi**.")
            final.persist()
            state.runs.update_status(run.run_id, RunStatus.DONE)
        return state.chat_service.session_response(state.sessions.get_session(session.session_id))

    @app.post("/__test__/release-compaction")
    async def release_compaction():
        upstream.compaction_release.set()
        return {"released": True}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18767)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="cogita-presentation-") as directory:
        root = Path(directory)
        os.environ["COGITA_ATTACHMENTS_DIR"] = str(root / "data/attachments")
        app = create_fixture_app(Path(__file__).resolve().parents[1], root)
        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
