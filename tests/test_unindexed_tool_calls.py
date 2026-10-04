"""Opt-in normalization of the observed complete, terminal third-party tool delta."""
import asyncio
import copy
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.schema import ChatRequest, ExternalConnection, ModelProfile
from tests.model_fixtures import configure_model
from tests.test_phase2a_manager import ControlledAdapter
from tests.test_phase4_harness import configure, send, results
from tests.tool_fixtures import ToolOpenAI, completion, tool_call

OPTION = "allow_unindexed_complete_tool_call"
# Shape captured from the third-party stream; identifiers and arguments are synthetic.
CALL = {"id": "call_fixture", "type": "function", "function": {
    "name": "base64_encode", "arguments": '{"value":"hello"}'}}


def event(delta, finish=None):
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def response(events, done=True):
    body = "".join("data: " + json.dumps(e) + "\n\n" for e in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                         text=body + ("data: [DONE]\n\n" if done else ""))


def terminal(call=None):
    return event({"role": "assistant", "content": None, "tool_calls": [copy.deepcopy(call or CALL)]}, "tool_calls")


def profile():
    return ModelProfile(name="Fixture", alias="fixture", model_ref="fixture", kind="llm",
                        source={"type": "provider", "provider_profile_id": "fixture"})


def request():
    return ChatRequest(model="fixture", messages=[{"role": "user", "content": "test"}], stream=True)


@pytest.mark.parametrize("enabled", [False, True])
def test_captured_stream_and_provider_isolation(enabled):
    async def scenario():
        events = [event({"content": "Working"}), terminal(),
                  {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 5}}]
        original = copy.deepcopy(events)
        def handle(req):
            assert OPTION not in json.loads(req.content)
            return response(events)
        adapter = OpenAIAdapter(ExternalConnection(base_url="http://fixture.test", **{OPTION: enabled}),
                                transport=httpx.MockTransport(handle))
        try:
            if not enabled:
                with pytest.raises(ModelError, match="invalid inference response"):
                    _ = [c async for c in adapter.chat_stream(profile(), request())]
            else:
                # Concurrent calls share an adapter, but never the tool-seen state.
                async def collect():
                    return [c async for c in adapter.chat_stream(profile(), request())]
                for chunks in await asyncio.gather(collect(), collect()):
                    assert chunks[1].delta.tool_calls[0].index == 0
                    assert chunks[1].delta.tool_calls[0].function.arguments == CALL["function"]["arguments"]
                    assert chunks[-1].usage.completion_tokens == 5
            assert events == original
        finally:
            await adapter.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["multiple", "prior", "id", "name", "type", "arguments",
    "partial", "duplicate", "nan", "overflow", "array", "null_index", "negative_index", "finish", "done", "extra"])
def test_ambiguous_or_invalid_streams_still_fail(case):
    events = [terminal()]
    call = events[0]["choices"][0]["delta"]["tool_calls"][0]
    if case == "multiple":
        events[0]["choices"][0]["delta"]["tool_calls"].append(copy.deepcopy(CALL))
    elif case == "prior":
        events.insert(0, event({"tool_calls": [{"index": 0}]}))
    elif case in {"id", "type"}:
        call.pop(case)
    elif case in {"name", "arguments"}:
        call["function"].pop(case)
    elif case in {"partial", "duplicate", "nan", "overflow", "array"}:
        call["function"]["arguments"] = {"partial": '{"value":', "duplicate": '{"a":1,"a":2}',
            "nan": '{"a":NaN}', "overflow": '{"a":1e999}', "array": '[]'}[case]
    elif case.endswith("index"):
        call["index"] = None if case == "null_index" else -1
    elif case == "finish":
        events[0]["choices"][0]["finish_reason"] = "stop"
    elif case == "extra":
        call["unknown"] = True
    async def scenario():
        adapter = OpenAIAdapter(ExternalConnection(base_url="http://fixture.test", **{OPTION: True}),
            transport=httpx.MockTransport(lambda _: response(events, done=case != "done")))
        try:
            with pytest.raises(ModelError) as error:
                _ = [c async for c in adapter.chat_stream(profile(), request())]
            assert error.value.code == "PROVIDER_PROTOCOL_ERROR"
        finally:
            await adapter.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("enabled", [False, True])
def test_standard_parallel_stream_and_nonstream_unchanged(enabled):
    async def scenario():
        upstream = ToolOpenAI(completion(tool_call(), tool_call(call_id="call_2")), completion(CALL))
        adapter = OpenAIAdapter(ExternalConnection(base_url="http://fixture.test", **{OPTION: enabled}),
                                transport=httpx.MockTransport(upstream.handle))
        try:
            chunks = [c async for c in adapter.chat_stream(profile(), request())]
            calls = [t for c in chunks for t in c.delta.tool_calls or []]
            assert [t.index for t in calls] == [1, 0, 0, 1]
            result = await adapter.chat(profile(), request().model_copy(update={"stream": False}))
            assert result.message.tool_calls[0].id == CALL["id"]
        finally:
            await adapter.close()
    asyncio.run(scenario())


def test_provider_api_persistence_validation_and_invalidation(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    app = create_app(root=tmp_path, database_url=database_url)
    with TestClient(app) as client:
        payload = {"name": "Fixture", "connection": {"base_url": "http://fixture.test", "api_key": "private"}}
        provider = client.post('/api/models/providers', json=payload).json()
        path = '/api/models/providers/' + provider['id']
        assert provider['connection'][OPTION] is False
        invalidate = AsyncMock()
        app.state.runtime_state.model_manager.invalidate = invalidate
        assert client.patch(path, json={"connection": {OPTION: True}}).json()['connection'][OPTION] is True
        invalidate.assert_awaited_once_with(("provider", provider['id']))
        assert client.patch(path, json={"name": "Renamed"}).json()['connection'][OPTION] is True
        for bad in [None, 0, 1, "true", "false"]:
            assert client.patch(path, json={"connection": {OPTION: bad}}).status_code == 422
            assert client.post('/api/models/providers', json={**payload,
                "connection": {**payload['connection'], OPTION: bad}}).status_code == 422
        assert client.get(path).json()['connection']['has_api_key'] is True
        assert 'private' not in client.get(path).text
    with TestClient(create_app(root=tmp_path, database_url=database_url)) as client:
        assert client.get(path).json()['connection'][OPTION] is True
        assert client.patch(path, json={"connection": {OPTION: False}}).json()['connection'][OPTION] is False


def test_busy_provider_cannot_change_option(tmp_path):
    adapter = ControlledAdapter()
    with TestClient(create_app(root=tmp_path, use_memory=True, adapter_factory=lambda _: adapter)) as client:
        model = configure_model(client)
        path = '/api/models/providers/' + model['source']['provider_profile_id']
        manager = client.app.state.runtime_state.model_manager
        task = client.portal.start_task_soon(manager.chat, model['id'], request().model_copy(update={"stream": False}))
        client.portal.call(adapter.started.wait)
        try:
            assert client.patch(path, json={"connection": {OPTION: True}}).status_code == 409
            assert client.get(path).json()['connection'][OPTION] is False
        finally:
            client.portal.call(adapter.release.set)
            task.result(timeout=5)


def test_harness_executes_normalized_call_once_and_returns_result(tmp_path):
    upstream = ToolOpenAI(completion(content="finished"))
    sent = []
    async def handle(req):
        data = json.loads(req.content)
        if req.url.path.endswith('/chat/completions'):
            sent.append(data)
            if len(sent) == 1:
                return response([terminal()])
        return await upstream.handle(req)
    factory = lambda connection: OpenAIAdapter(connection, transport=httpx.MockTransport(handle))
    with TestClient(create_app(root=tmp_path, use_memory=True, adapter_factory=factory)) as client:
        session, _, model = configure(client)
        assert client.patch('/api/models/providers/' + model['source']['provider_profile_id'],
                            json={"connection": {OPTION: True}}).status_code == 200
        payload = send(client, session)
        assert payload['run']['status'] == 'DONE'
        assert len(results(payload)) == 1
        assert results(payload)[0]['data']['value'] == 'aGVsbG8='
        assert len(sent) == 2
        assert sent[1]['messages'][-1]['tool_call_id'] == CALL['id']
        assert json.loads(sent[1]['messages'][-1]['content'])['status'] == 'success'
        assert all(OPTION not in body for body in sent)
