import asyncio
from datetime import timedelta

import httpx
import pytest
from pydantic import ValidationError

from ai_workbench.core.models.llm_metrics import LLMCallMetrics, LLMUsage, NativeGenerationTiming
from ai_workbench.core.models.schema import ChatChunk, ChatResult
from tests.model_fixtures import configure_model
from tests.test_phase2a_manager import local_manager_fixture, manager_fixture, request, wait_until
from tests.test_phase2a_protocol import app_client, enable_external, sse_data
from tests.test_chat_presentation import presentation_client, configure, send
from tests.tool_fixtures import completion, tool_call, ok


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def test_usage_preserves_unknown_zero_details_and_validates_provider_fields():
    empty = LLMUsage.from_provider({"completion_tokens": 0, "vendor": "ignored"})
    assert empty.completion_tokens == 0 and empty.prompt_tokens is empty.total_tokens is None
    counted = LLMUsage.from_provider({"prompt_tokens": 10, "completion_tokens": 5,
        "prompt_tokens_details": {"cached_tokens": 8, "audio_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 3}})
    assert counted.total_tokens == 15
    assert counted.prompt_tokens_details.cached_tokens == 8
    assert counted.completion_tokens_details.reasoning_tokens == 3
    for value in (-1, True, "3", 1.5):
        with pytest.raises(ValidationError):
            LLMUsage.from_provider({"completion_tokens": value})
    with pytest.raises(ValidationError):
        LLMUsage(prompt_tokens=1, surprise=True)
    for value in (float("inf"), float("nan"), -1, "5", True):
        with pytest.raises(ValidationError):
            NativeGenerationTiming.from_provider({"predicted_ms": value})
    for value in ([], 3, "invalid"):
        with pytest.raises(ValueError):
            LLMUsage.from_provider(value)
        with pytest.raises(ValueError):
            NativeGenerationTiming.from_provider(value)


@pytest.mark.parametrize("first", [
    {"content": "<think>"}, {"reasoning_content": "thinking"},
    {"tool_calls": [{"index": 0, "function": {"name": "lookup"}}]},
    {"tool_calls": [{"index": 0, "function": {"arguments": "{"}}]},
])
def test_first_response_and_estimate_use_output_not_protocol_frames(first):
    clock = Clock()
    metrics = LLMCallMetrics(clock=clock)
    metrics.start()
    for delta in ({}, {"role": "assistant"}, {"content": ""}, {"tool_calls": [{"index": 0, "id": "call"}]}):
        clock.now += 1
        metrics.observe(ChatChunk(delta=delta))
    assert metrics.first is None
    clock.now = 105
    metrics.observe(ChatChunk(delta=first))
    clock.now = 106
    metrics.observe(ChatChunk(delta={"content": "answer"}))
    clock.now = 109
    metrics.observe(ChatChunk(finish_reason="stop", usage={"prompt_tokens": 10, "completion_tokens": 20}))
    clock.now = 110
    metrics.observe(ChatChunk(usage={"prompt_tokens": 10, "completion_tokens": 20}))
    metrics.finish(completed=True)
    clock.now = 999  # Later release/serialization must not change the result.
    metrics.finish()
    saved = metrics.snapshot("profile", "alias", "message")
    assert saved.timing.first_response_ms == 5000
    assert saved.first_response_at == saved.started_at + timedelta(seconds=5)
    assert saved.timing.total_ms == 10000
    assert saved.timing.generation_ms == 4000
    assert saved.timing.tokens_per_second == 5
    assert saved.timing.tps_source == "estimated"
    assert saved.usage.total_tokens == 30  # Repeated snapshots are not additive.


@pytest.mark.parametrize("chunks,complete,finish,usage", [
    (1, True, "stop", {"completion_tokens": 20}),
    (2, False, "stop", {"completion_tokens": 20}),
    (2, True, "length", {"completion_tokens": 20}),
    (2, True, "content_filter", {"completion_tokens": 20}),
    (2, True, "stop", None),
    (2, True, "stop", {"prompt_tokens": 20}),
])
def test_unobservable_or_incomplete_generation_has_no_estimate(chunks, complete, finish, usage):
    clock = Clock()
    metrics = LLMCallMetrics(clock=clock)
    metrics.start()
    for _ in range(chunks):
        clock.now += 1
        metrics.observe(ChatChunk(delta={"content": "text"}))
    clock.now += 1
    metrics.observe(ChatChunk(finish_reason=finish, usage=usage))
    metrics.finish(completed=complete)
    assert metrics.timing().tokens_per_second is None


def test_native_speed_uses_its_own_token_count_and_nonstream_has_no_first_response():
    metrics = LLMCallMetrics()
    metrics.start()
    metrics.observe_result(ChatResult(message={"role": "assistant", "content": "text"}, finish_reason="stop",
        usage={"prompt_tokens": 10, "completion_tokens": 40}, timings={"predicted_n": 30, "predicted_ms": 1500}))
    assert metrics.timing().tokens_per_second == 20
    assert metrics.timing().generation_tokens == 30
    assert metrics.timing().tps_source == "native"
    assert metrics.timing().first_response_ms is None


@pytest.mark.parametrize("streaming,prepared", [(False, False), (True, False), (True, True)])
def test_queue_loading_and_generation_are_measured_before_release(tmp_path, streaming, prepared):
    async def scenario():
        manager, profile, adapter = local_manager_fixture(tmp_path, {"unload": "after_request"})
        clock = Clock()
        metrics = LLMCallMetrics(clock=clock)
        original_load, original_unload = adapter.load, adapter.unload

        async def load(*args, **kwargs):
            clock.now += 2
            return await original_load(*args, **kwargs)

        async def unload(*args, **kwargs):
            clock.now += 50
            return await original_unload(*args, **kwargs)

        async def chat(*_, capture=None):
            clock.now += 3
            return ChatResult(message={"role": "assistant", "content": "answer"}, finish_reason="stop")

        async def stream(*_, capture=None):
            clock.now += 1
            yield ChatChunk(delta={"content": "a"})
            clock.now += 1
            yield ChatChunk(delta={"content": "b"})
            clock.now += 1
            yield ChatChunk(finish_reason="stop", usage={"prompt_tokens": 1, "completion_tokens": 4})

        adapter.load, adapter.unload, adapter.chat, adapter.chat_stream = load, unload, chat, stream
        slot = manager._slots[manager.execution_key(profile)]
        await slot.semaphore.acquire()

        async def execute():
            if streaming:
                stream = (await manager.prepare_chat_stream(profile.id, request(True), metrics=metrics) if prepared else
                          manager.chat_stream(profile.id, request(True), metrics=metrics))
                async for _ in stream:
                    pass
            else:
                await manager.chat(profile.id, request(), metrics=metrics)

        task = asyncio.create_task(execute())
        await wait_until(lambda: slot.queued == 1)
        clock.now += 7
        slot.semaphore.release()
        await task
        timing = metrics.timing()
        assert timing.queue_ms == 7000 and timing.load_ms == 2000
        assert timing.total_ms == 12000 and clock.now == 162
        if streaming:
            assert timing.first_response_ms == 10000 and timing.tokens_per_second == 2
        await manager.close()
    asyncio.run(scenario())


def test_cancel_before_output_keeps_elapsed_and_releases_occupancy():
    async def scenario():
        manager, profile, adapter = manager_fixture()
        metrics = LLMCallMetrics()
        task = asyncio.create_task(manager.chat(profile.id, request(), metrics=metrics))
        await adapter.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not metrics.completed and metrics.usage is None
        assert metrics.timing().total_ms is not None and metrics.timing().first_response_ms is None
        assert manager.status(profile.id).active == 0
        await manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("include_usage", [False, True])
@pytest.mark.parametrize("include_metrics", [False, True])
def test_external_statistics_are_opt_in_and_one_tail_snapshot(app_client, include_usage, include_metrics):
    client, upstream = app_client
    configure_model(client, request_options={"streaming": True})
    upstream.stream_events = [
        {"choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": " world"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 9, "completion_tokens": 4}},
        {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 5},
                                  "completion_tokens_details": {"reasoning_tokens": 2}},
         "timings": {"predicted_n": 4, "predicted_ms": 200, "prompt_ms": 25}},
    ]
    response = client.post("/v1/chat/completions", headers=enable_external(client), json={
        "model": "local", "messages": [{"role": "user", "content": "hello"}], "stream": True,
        "stream_options": {"include_usage": include_usage}, "cogita": {"include_metrics": include_metrics}})
    assert response.status_code == 200, response.text
    chunks = sse_data(response)
    tails = [chunk for chunk in chunks if not chunk["choices"]]
    assert len(tails) == int(include_usage or include_metrics)
    assert response.text.count("data: [DONE]") == 1
    assert len([chunk for chunk in chunks if chunk["choices"] and chunk["choices"][0]["finish_reason"]]) == 1
    assert "cogita" not in upstream.calls[-1]
    if include_metrics:
        assert upstream.calls[-1]["stream_options"]["include_usage"] is True
        assert tails[0]["cogita_metrics"]["tokens_per_second"] == 20
        assert tails[0]["cogita_metrics"]["tps_source"] == "native"
    if include_usage:
        assert tails[0]["usage"]["total_tokens"] == 13
        assert tails[0]["usage"]["prompt_tokens_details"]["cached_tokens"] == 5
        assert tails[0]["usage"]["completion_tokens_details"]["reasoning_tokens"] == 2
        assert all(chunk["usage"] is None for chunk in chunks if chunk["choices"])
    else:
        assert all("usage" not in chunk for chunk in chunks)
    if not include_metrics:
        assert all("cogita_metrics" not in chunk for chunk in chunks)
    state = client.app.state.runtime_state
    assert state.runs.list_all_runs() == [] and state.messages.list_all_messages() == []


def test_external_nonstream_metrics_and_missing_stream_usage(app_client):
    client, upstream = app_client
    configure_model(client, request_options={"streaming": True})
    headers = enable_external(client)
    payload = {"model": "local", "messages": [{"role": "user", "content": "hello"}], "cogita": {"include_metrics": True}}
    body = ok(client.post("/v1/chat/completions", headers=headers, json=payload))
    assert body["usage"]["total_tokens"] == 5
    assert body["cogita_metrics"]["first_response_ms"] is None
    assert body["cogita_metrics"]["tokens_per_second"] is None
    assert body["cogita_metrics"]["total_ms"] >= 0
    upstream.stream_events = [{"choices": [{"index": 0, "delta": {"content": "one"}, "finish_reason": "stop"}]}]
    tail = sse_data(client.post("/v1/chat/completions", headers=headers,
        json={**payload, "stream": True, "stream_options": {"include_usage": True}}))[-1]
    assert tail["usage"] is None and tail["cogita_metrics"]["tokens_per_second"] is None
    assert tail["cogita_metrics"]["first_response_ms"] is not None
    plain = ok(client.post("/v1/chat/completions", headers=headers, json={**payload, "cogita": {"include_metrics": False}}))
    assert "cogita_metrics" not in plain
    for invalid in (None, 1, "true"):
        rejected = client.post("/v1/chat/completions", headers=headers,
            json={**payload, "cogita": {"include_metrics": invalid}})
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("ending", [
    '',
    'data: {"error":{"message":"private upstream failure"}}\n\n',
    'data: {"choices":[],"usage":{"completion_tokens":-1}}\n\ndata: [DONE]\n\n',
])
def test_external_stream_errors_never_publish_successful_statistics(app_client, ending):
    client, upstream = app_client
    configure_model(client, request_options={"streaming": True})
    body = ('data: {"choices":[{"index":0,"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"completion_tokens":3}}\n\n')

    async def handle(_):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body + ending)

    upstream.handle = handle
    response = client.post("/v1/chat/completions", headers=enable_external(client), json={
        "model": "local", "messages": [{"role": "user", "content": "hello"}], "stream": True,
        "stream_options": {"include_usage": True}, "cogita": {"include_metrics": True}})
    frames = sse_data(response)
    assert frames[-1]["error"]["code"] in {"PROVIDER_ERROR", "PROVIDER_PROTOCOL_ERROR"}
    assert not any(frame.get("choices") == [] or "cogita_metrics" in frame for frame in frames)
    assert response.text.count("data: [DONE]") == 1
    assert "private upstream failure" not in response.text


@pytest.mark.parametrize("harness", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_call_snapshots_persist_once_per_model_step(presentation_client, harness, streaming):
    client, upstream = presentation_client
    session = configure(client, harness=harness, streaming=streaming)
    turns = ([completion(tool_call(), content="thinking")] if harness else []) + [completion(content="answer")]
    upstream.turns = [{**turn, "usage": {"prompt_tokens": 10 + index, "completion_tokens": 3}} for index, turn in enumerate(turns)]
    response = send(client, session)
    assert response["success"], response
    saved = ok(client.get(f"/api/runs/{response['run']['run_id']}"))
    model_steps = [step for step in saved["steps"] if step["kind"] == "model"]
    assert len(model_steps) == len(turns)
    for index, step in enumerate(model_steps):
        snapshot = step["metadata"]["llm"]
        assert snapshot["usage"]["prompt_tokens"] == 10 + index and snapshot["completed"]
        assert snapshot["usage"]["total_tokens"] == 13 + index
        assert snapshot["message_id"] in {message["message_id"] for message in response["messages"]}
        assert (snapshot["first_response_at"] is not None) == streaming
        assert snapshot["timing"]["total_ms"] >= 0
    assert all("llm" not in message["metadata"] for message in response["messages"])
    if streaming:
        assert all(call["stream_options"]["include_usage"] for call in upstream.calls)
    events = ok(client.get(f"/api/runs/{saved['run_id']}/events"))
    assert any(event["type"] == "run_step_updated" and event["payload"]["step"]["metadata"].get("llm") for event in events)


def test_failed_call_keeps_incomplete_statistics_without_an_answer(presentation_client):
    client, upstream = presentation_client
    session = configure(client, harness=False)
    upstream.stream_chunks = [{"refusal": "no"}]
    response = send(client, session)
    assert response["run"]["status"] == "FAILED"
    step = next(step for step in response["run"]["steps"] if step["kind"] == "model")
    assert not step["metadata"]["llm"]["completed"]
    assert step["metadata"]["llm"]["timing"]["total_ms"] >= 0
    assert not any(message["role"] == "assistant" for message in response["messages"])
