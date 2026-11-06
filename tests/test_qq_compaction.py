"""QQ rolling memory, strict policy ownership and delivery-safe loop summaries."""
import asyncio
import json
from dataclasses import replace

import pytest
from sqlmodel import Session

from ai_workbench.core.schema.compaction import ContextCheckpoint
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQMessage
from tests.test_harness_compaction import is_summary, summary
from tests.test_qqbot import qq_client, character, configure_execution, child, ingest, freeze, event
from tests.test_qq_followup import clock
from tests.test_qq_icebreaker import setup as icebreaker_setup, tick, binding
from tests.test_qq_reply_policy import execute_batch
from tests.test_qq_media import isolated_attachments, prepare_images, image_event, finish_pending, page
from tests.qq_context_fixture import character_qq_context, prepare_qq_context
from tests.tool_fixtures import completion, ok, tool_call


def setup(client, state, **values):
    policy = ContextPolicy(compaction={"trigger_percent": 25, "target_percent": 15, "max_summary_tokens": 512})
    p, session, connection = configure_execution(client, state, reply_message_limit=1,
        context_policy=policy.model_dump(), **values)
    ok(client.patch(f"/api/models/profiles/{p['model_profile_id']}", json={"context_window_tokens": 8192}))
    return p, session, connection


def respond(request):
    return summary(request) if is_summary(request) else completion(
        tool_call("qq_send_message", {"text": "Confirmed reply"}, "send"), content="PRIVATE INTERNAL PROSE")


def test_qq_policy_defaults_strict_rejection_and_image_ownership(qq_client):
    client, state, _ = qq_client
    p = character(client)
    assert p["context_policy"] == ContextPolicy().model_dump()
    url = f"/api/characters/{p['id']}"
    for policy in ({"max_messages": 100}, {"max_chars": 1000}, {"history_enabled": None},
                   {"strategy": "message_window", "message_window": {"max_messages": 0}},
                   {"compaction": {"trigger_percent": 50, "target_percent": 50}}):
        assert client.patch(url, json={"context_policy": policy}).status_code == 422
    p = ok(client.patch(url, json={"context_policy": {"history_enabled": False}, "image_input_enabled": True}))
    session = child(client, p)
    assert session["effective"]["context_policy"]["history_enabled"] is False
    assert session["effective"]["context_policy"]["include_attachments"] == "explicit"
    assert client.post(f"/api/sessions/{session['session_id']}/compact", json={}).status_code == 409


def test_three_qq_checkpoints_cover_only_submitted_inputs_and_confirmed_sends(qq_client):
    client, state, upstream = qq_client
    p, session, connection = setup(client, state)
    upstream.turns = [respond] * 40
    batches, snapshots = [], []
    previous = None
    for number in range(4):
        batch, run = execute_batch(client, state, p, session, number + 1,
            text=f"bot FACT_{number}=value{number}; " + "padding " * 650)
        assert run.status == "DONE", run
        batches.append(batch)
        checkpoint = state.sessions.get_context_checkpoint(session["session_id"])
        if number:
            assert checkpoint is not None and checkpoint.checkpoint_id != (previous.checkpoint_id if previous else None)
            assert checkpoint.boundary_qq_batch_id == batches[-2].id
            assert checkpoint.boundary_message_id == batches[-2].input_message_id
            assert checkpoint.covered_messages == number * 2
            assert f"FACT_{number}=" not in checkpoint.summary
            for old in range(number):
                assert f"FACT_{old}=value{old};" in checkpoint.summary
            step = next(s for s in state.runs.list_steps(run.run_id) if s.kind == "model")
            snapshot = state.runs.get_context_snapshot(step.step_id)
            snapshots.append(snapshot)
            source = next(s for s in snapshot.sources if s.compaction)
            assert source.compaction.boundary_qq_batch_id == batches[-2].id
        previous = checkpoint
    assert len(connection.calls) == 4
    summary_inputs = [request["messages"][1]["content"] for request in upstream.calls if is_summary(request)]
    assert len(summary_inputs) == 3
    assert all("PRIVATE INTERNAL PROSE" not in text for text in summary_inputs)
    assert "QQ:9999" in summary_inputs[0] and '"status": "sent"' in summary_inputs[0].replace('\\"', '"')
    assert all(state.runs.get_context_snapshot(item.step_id) == item for item in snapshots)
    other = child(client, p, "8899")
    assert state.sessions.get_context_checkpoint(other["session_id"]) is None
    assert "FACT_" not in character_qq_context(state.qq.store, state.messages, other["session_id"], "next", ContextPolicy(), None).model_dump_json()


def test_qq_window_omits_memory_and_switch_back_reuses_it(qq_client):
    client, state, upstream = qq_client
    p, session, connection = setup(client, state)
    upstream.turns = [respond] * 30
    for number in range(2):
        _, run = execute_batch(client, state, p, session, number + 1, text=f"bot FACT_{number}=value{number}; " + "padding " * 650)
        assert run.status == "DONE"
    checkpoint = state.sessions.get_context_checkpoint(session["session_id"])
    assert checkpoint
    policy = ContextPolicy(strategy="message_window", message_window={"max_messages": 2})
    ok(client.patch(f"/api/characters/{p['id']}", json={"context_policy": policy.model_dump()}))
    offset = len(upstream.calls)
    _, run = execute_batch(client, state, p, session, 3)
    assert run.status == "DONE" and len(upstream.calls) == offset + 1
    assert "Historical summary" not in json.dumps(upstream.calls[-1])
    assert "FACT_0=" not in json.dumps(upstream.calls[-1])
    assert "FACT_1=" in json.dumps(upstream.calls[-1])
    assert state.sessions.get_context_checkpoint(session["session_id"]) == checkpoint
    policy.strategy = "token_budget"
    policy.compaction.enabled = False
    ok(client.patch(f"/api/characters/{p['id']}", json={"context_policy": policy.model_dump()}))
    _, run = execute_batch(client, state, p, session, 4)
    assert run.status == "DONE" and checkpoint.summary in json.dumps(upstream.calls[-1])
    assert len(connection.calls) == 4


@pytest.mark.parametrize('strategy', ['token_budget', 'history_retrieval'])
def test_loop_compaction_preserves_qq_delivery_count_and_web_budget(qq_client, strategy):
    client, state, upstream = qq_client
    p, session, connection = setup(client, state)
    if strategy == 'history_retrieval':
        ok(client.patch(f"/api/characters/{p['id']}", json={'context_policy': {'strategy': strategy,
            'retrieval': {'trigger_percent': 25, 'target_percent': 15}}}))
    ok(client.patch(f"/api/characters/{p['id']}", json={"reply_message_limit": 2}))
    calls = []
    async def fetch(arguments, context):
        calls.append(context.tool_call_id)
        return {"url": "https://example.com/evidence", "title": "Evidence",
            "content": "FACT_0=value0; " + "x " * 1700}
    state.tool_registry._tools["web_fetch"] = replace(state.tool_registry.get("web_fetch"), handler=fetch)
    answers = []
    def model(request):
        if is_summary(request):
            return summary(request)
        number = len(answers)
        answers.append(request)
        if number in {0, 2}:
            return completion(tool_call("web_fetch", {"url": "https://example.com/evidence"}, f"fetch_{number}"))
        return completion(tool_call("qq_send_message", {"text": f"Reply {number}"}, f"send_{number}"))
    upstream.turns = [model] * 20
    _, run = execute_batch(client, state, p, session)
    assert run.status == "DONE", run
    assert calls == ["fetch_0", "fetch_2"] and len(connection.calls) == 2
    assert run.metadata["qq_reply"]["sent_count"] == 2 and run.metadata["qq_reply"]["limit_reached"]
    assert any((step.kind == 'compaction' if strategy == 'token_budget' else step.metadata.get('operation') == 'reset')
        and step.status == 'completed' for step in state.runs.list_steps(run.run_id))
    assert "confirmed sends=1/2" in json.dumps(answers[-1])
    web_steps = [step for step in state.runs.list_steps(run.run_id) if step.metadata.get("tool_name") == "web_fetch"]
    assert [step.metadata["web"]["remaining"]["fetch"] for step in web_steps] == [5, 4]
    assert state.sessions.get_context_checkpoint(session["session_id"]) is None
    projected = character_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(), None)
    assert "FACT_0" not in projected.model_dump_json() and "Reply 1" in projected.model_dump_json()


def test_media_description_change_and_history_delete_invalidate_qq_memory(qq_client, monkeypatch):
    client, state, upstream = qq_client
    prepare_images(monkeypatch)
    p, session, _ = setup(client, state)
    upstream.turns = [respond] * 10
    ingest(client, state, p, image_event(text="bot image " + "padding " * 650), 1)
    client.portal.call(finish_pending, state)
    batch = freeze(state, session, 6)
    client.portal.call(state.qq.execute, batch)
    row = state.messages.get_message(batch.input_message_id)
    def save_memory():
        checkpoint = ContextCheckpoint(session_id=session["session_id"], summary="Old image description",
            boundary_message_id=row.message_id, boundary_created_at=row.created_at, boundary_qq_batch_id=batch.id,
            covered_messages=2, history_version=state.sessions.get_session(session["session_id"]).history_version,
            include_attachments="none", model_profile_id=p["model_profile_id"], step_id="summary", input_tokens_after=100, counting="estimated")
        assert state.sessions.save_context_checkpoint(checkpoint)
    snapshot = state.runs.get_context_snapshot(next(s for s in state.runs.list_steps(batch.run_id) if s.kind == "model").step_id)
    save_memory()
    asset_id = page(client, session)[0]["segments"][1]["asset_id"]
    state.qq.store.update_description(asset_id, "Updated description")
    assert state.sessions.get_context_checkpoint(session["session_id"]) is None
    assert state.runs.get_context_snapshot(snapshot.step_id) == snapshot
    def concurrent_description(request):
        state.qq.store.update_description(asset_id, "Later description")
        return summary(request)
    upstream.turns = [concurrent_description]
    policy = ContextPolicy(include_attachments="none", compaction={"trigger_percent": 5, "target_percent": 3})
    frozen = prepare_qq_context(client, state, session["session_id"], policy)
    assert state.sessions.get_context_checkpoint(session["session_id"]) is None
    assert "Updated description" in frozen.model_dump_json() and "Later description" not in frozen.model_dump_json()
    last_run = state.runs.list_runs(session["session_id"])[-1]
    assert any(step.kind == "compaction" and step.status == "failed" for step in state.runs.list_steps(last_run.run_id))
    save_memory()
    incoming, = state.qq.store.batch_messages(batch.id)
    ok(client.delete(f"/api/qq/sessions/{session['session_id']}/messages/{incoming.id}"))
    assert state.sessions.get_context_checkpoint(session["session_id"]) is None


def test_qq_history_pages_bidirectionally_and_bounds_candidate_reads(qq_client, monkeypatch):
    client, state, _ = qq_client
    p, session, _ = setup(client, state)
    sid = session["session_id"]
    with Session(state.qq.store.engine) as db:
        for number in range(1, 131):
            message = state.messages.add_message(sid, "user", f"batch {number} " + "padding " * 2000)
            db.add(QQBatch(id=number, session_id=sid, character_id=p["id"], status="done", text="input",
                created_at=number, input_message_id=message.message_id))
            db.add(QQMessage(session_id=sid, external_id=str(number), sender_id="9999", sender_name="Name",
                timestamp="2026-11-01T00:00:00+00:00", text="input", batch_id=number, disposition="batched"))
        db.commit()
    store = state.qq.store
    ascending = [batch.id for batch, _ in store.iter_history(sid, after=32, before=100, ascending=True)]
    descending = [batch.id for batch, _ in store.iter_history(sid, after=32, before=100)]
    assert ascending == list(range(33, 100)) and descending == ascending[::-1]
    assert store.history_message_count(sid) == 130
    reads = []
    iterate = store.iter_history
    def bounded(*args, **kwargs):
        for row in iterate(*args, **kwargs):
            reads.append(row[0].id)
            assert len(reads) <= 4, "Token selection must stop after its bounded recent suffix"
            yield row
    monkeypatch.setattr(store, "iter_history", bounded)
    result = prepare_qq_context(client, state, sid, ContextPolicy(compaction={"enabled": False}))
    assert 1 <= len(reads) <= 4
    assert "batch 130 " in result.model_dump_json() and "batch 1 " not in result.model_dump_json()
    assert any(item.reason == "token_limit" and item.count >= 127 for item in result.trace.exclusions)


def test_qq_summary_failure_over_window_pauses_without_sending(qq_client):
    client, state, upstream = qq_client
    p, session, connection = setup(client, state)
    policy = ContextPolicy(compaction={"enabled": False})
    ok(client.patch(f"/api/characters/{p['id']}", json={"context_policy": policy.model_dump()}))
    upstream.turns = [respond] * 20
    for number in range(4):
        _, run = execute_batch(client, state, p, session, number + 1, text="bot " + "padding " * 1700)
        assert run.status == "DONE", run
    policy.compaction.enabled = True
    ok(client.patch(f"/api/characters/{p['id']}", json={"context_policy": policy.model_dump()}))
    upstream.turns = [completion(content="truncated summary", finish="length")]
    _, run = execute_batch(client, state, p, session, 5)
    assert run.status == "FAILED" and run.error_code == "CONTEXT_COMPACTION_FAILED"
    assert state.qq.store.get(QQBinding, session["session_id"]).paused
    assert len(connection.calls) == 4
    assert state.sessions.get_context_checkpoint(session["session_id"]) is None


def test_icebreaker_summary_dispatch_starts_cooldown_and_is_cancellable(qq_client, clock, monkeypatch):
    client, state, upstream = qq_client
    reached = asyncio.Event()
    block_summaries = False
    handle = upstream.handle
    async def hold(request):
        if block_summaries and request.url.path.endswith("/chat/completions") and is_summary(json.loads(request.content)):
            reached.set()
            await asyncio.Event().wait()
        return await handle(request)
    monkeypatch.setattr(upstream, "handle", hold)
    policy = ContextPolicy(compaction={"trigger_percent": 25, "target_percent": 15, "max_summary_tokens": 512})
    p, session, connection = icebreaker_setup(qq_client, clock, reply_message_limit=1, context_policy=policy.model_dump())
    ok(client.patch(f"/api/models/profiles/{p['model_profile_id']}", json={"context_window_tokens": 8192}))
    upstream.turns = [respond] * 8
    clock[0] = 6
    ingest(client, state, p, event(1, "bot old topic " + "padding " * 650), 1)
    old = freeze(state, session, 6)
    client.portal.call(state.qq.execute, old)
    assert len(connection.calls) == 1
    tick(qq_client, session, clock, 100)
    ingest(client, state, p, event(2, "A quiet topic " + "padding " * 650), 101)
    batch = tick(qq_client, session, clock, 106)
    assert batch.trigger_kind == "icebreaker"
    block_summaries = True
    async def scenario():
        worker = asyncio.create_task(state.qq.execute(batch))
        signal = asyncio.create_task(reached.wait())
        try:
            await asyncio.wait({worker, signal}, timeout=10, return_when=asyncio.FIRST_COMPLETED)
            current = state.qq.store.get(QQBatch, batch.id)
            assert reached.is_set(), json.dumps({"status": current.status, "error": current.error_code,
                "policy": state.runs.get_config_snapshot(current.run_id)["context_policy"] if current.run_id else None,
                "steps": [{"kind": step.kind, "budget": step.metadata.get("context", {}).get("budget")}
                    for step in state.runs.list_steps(current.run_id)] if current.run_id else []})
            assert binding(state, session).icebreaker_cooldown_until == 136
            await state.qq.ingest(p["id"], event(3, "Another participant", sender="8888"), now=107)
            await asyncio.wait_for(worker, 5)
        finally:
            signal.cancel()
            await asyncio.gather(signal, return_exceptions=True)
            if not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
    client.portal.call(scenario)
    current = state.qq.store.get(QQBatch, batch.id)
    assert current.status == "cancelled" and current.error_code == "QQ_ICEBREAKER_CANCELLED"
    assert not binding(state, session).paused and len(connection.calls) == 1
    assert state.sessions.get_context_checkpoint(session["session_id"]) is None
