"""QQ participant clocks, immutable batches and explicit no-reply decisions."""
import json
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.qq_store import QQStore
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQDelivery, QQParticipant
from tests.test_qqbot import qq_client, child, configure_execution, event, freeze, ingest, project
from tests.tool_fixtures import completion, ok, tool_call


@pytest.fixture
def clock(monkeypatch):
    value = [0]
    monkeypatch.setattr("ai_workbench.core.qq_service.time", SimpleNamespace(time=lambda: value[0]))
    return value


def participant(state, session, sender="9999"):
    return state.qq.store.get(QQParticipant, (session["session_id"], sender))


def execute(qq_client, batch):
    client, state, _ = qq_client
    client.portal.call(state.qq.execute, batch)
    batch = state.qq.store.get(QQBatch, batch.id)
    return batch, state.runs.get_run(batch.run_id)


def reply(upstream, text="reply"):
    upstream.turns = [completion(tool_call("qq_send_message", {"text": text})), completion(content="Internal end")]


def followup(qq_client, clock, *, streaming=False, **values):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, streaming=streaming, **values)
    ingest(client, state, p, event(1), 0)
    clock[0] = 6
    reply(upstream)
    initial, run = execute(qq_client, freeze(state, session, 5))
    assert initial.status == "done" and run.status == "DONE"
    ingest(client, state, p, event(2, "a follow-up"), 10)
    clock[0] = 16
    upstream.calls.clear()
    return p, session, connection, freeze(state, session, 15)


def test_example_timeline_batches_and_reply_clocks(qq_client, clock):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    # Seconds relative to noon; nonparticipants are included without extending silence.
    for number, when, sender, text in [(1, -3, "4444", "earlier context"), (2, -2, "9999", "bot"),
            (3, -1, "3333", "C context"), (4, 0, "9999", "bot again"), (5, 1, "2222", "B context")]:
        ingest(client, state, p, event(number, text, sender=sender), when)
    assert participant(state, session).expires_at == 60
    first = freeze(state, session, 5)
    assert first.trigger_kind == "keyword" and len(state.qq.store.batch_messages(first.id)) == 5
    assert set(first.participants) == {"9999"}

    original = connection.call
    async def while_first_generates(action, params):
        await state.qq.ingest(p["id"], event(6, "A follow-up"), now=7)
        clock[0] = 8
        return await original(action, params)
    connection.call = while_first_generates
    reply(upstream)
    assert execute(qq_client, first)[0].status == "done"
    connection.call = original
    ingest(client, state, p, event(7, "C context", sender="3333"), 9)
    second = freeze(state, session, 12)
    assert second.trigger_kind == "followup"
    assert [m.external_id for m in state.qq.store.batch_messages(second.id)] == ["6", "7"]
    ingest(client, state, p, event(8, "later C context", sender="3333"), 13)
    clock[0] = 14
    reply(upstream)
    assert execute(qq_client, second)[0].status == "done"
    assert participant(state, session).expires_at == 60  # max(60, 14 + 45)

    ingest(client, state, p, event(9, "A follow-up"), 30)
    third = freeze(state, session, 35)
    assert [m.external_id for m in state.qq.store.batch_messages(third.id)] == ["8", "9"]
    clock[0] = 35
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}"))]
    batch, run = execute(qq_client, third)
    assert batch.status == "done" and run.metadata["qq_reply"]["skipped"]
    assert participant(state, session).expires_at == 35
    assert participant(state, session, "3333") is None
    assert len(connection.calls) == 2
    ingest(client, state, p, event(10, "ordinary after skip"), 36)
    assert freeze(state, session, 50) is None


def test_silence_latches_participants_past_expiry_and_exact_cutoff(qq_client):
    client, state, _ = qq_client
    p = project(client, keywords=["bot"])
    session = child(client, p)
    ingest(client, state, p, event(1), 0)
    freeze(state, session, 5)
    ingest(client, state, p, event(2, "just before expiry"), 59)
    for number, now in enumerate([63, 67, 71], 3):
        ingest(client, state, p, event(number, "still talking"), now)
    ingest(client, state, p, event(6, "bystander", sender="8888"), 75)
    assert freeze(state, session, 75.99) is None
    # The exact cutoff freezes first; the expired sender cannot open a new window.
    ingest(client, state, p, event(7, "too late"), 76)
    batches = state.qq.store.page(QQBatch, session["session_id"])["items"]
    assert len(batches) == 2 and batches[0]["trigger_kind"] == "followup"
    assert [m.external_id for m in state.qq.store.batch_messages(batches[0]["id"])] == ["2", "3", "4", "5", "6"]
    assert state.qq.store.get(QQBinding, session["session_id"]).deadline is None
    assert not participant(state, session).in_window
    # Eligibility is exclusive at its exact expiration, even outside a window.
    ingest(client, state, p, event(8), 80)
    freeze(state, session, 85)
    ingest(client, state, p, event(9, "at expiry"), 140)
    assert freeze(state, session, 145) is None


def test_keyword_promotes_window_before_truncation_and_snapshots_only_submitted_speakers(qq_client):
    client, state, _ = qq_client
    p = project(client, keywords=["bot"])
    session = child(client, p)
    ingest(client, state, p, event(1), 0)
    freeze(state, session, 5)
    ingest(client, state, p, event(2, "follow-up"), 10)
    ingest(client, state, p, event(3, "BOT", sender="8888"), 11)
    keyword_id = participant(state, session, "8888").keyword_message_id
    ingest(client, state, p, event(4, "continuation", sender="8888"), 12)
    ingest(client, state, p, event(5, "bystander", sender="7777"), 13)
    batch = freeze(state, session, 17, limit=2)
    assert batch.trigger_kind == "keyword"
    assert [m.external_id for m in state.qq.store.batch_messages(batch.id)] == ["4", "5"]
    assert batch.participants == {"8888": keyword_id}
    assert participant(state, session).expires_at == 60
    assert participant(state, session, "8888").expires_at == 71
    # A duplicate cannot renew eligibility, join a window, or change keyword epochs.
    ingest(client, state, p, event(3, "bot", sender="8888"), 20)
    assert participant(state, session, "8888").keyword_message_id == keyword_id
    assert participant(state, session, "8888").expires_at == 71
    assert state.qq.store.get(QQBinding, session["session_id"]).deadline is None


@pytest.mark.parametrize("cq", [False, True])
def test_actual_mentions_share_keyword_matching_without_name_queries(qq_client, cq):
    client, state, _ = qq_client
    p = project(client, keywords=["@12345"])
    session = child(client, p)
    message = "[CQ:at,qq=12345]" if cq else [{"type": "at", "data": {"qq": "12345"}}]
    ingest(client, state, p, {**event(1), "message": message}, 0)
    assert freeze(state, session, 5).trigger_kind == "keyword"
    assert participant(state, session).expires_at == 60
    other = child(client, p, "7789")
    for number, message in enumerate(["[CQ:at,qq=all]", "[CQ:at,qq=8888]", "[CQ:reply,id=@12345]", "[CQ:image,file=@12345]"], 2):
        ingest(client, state, p, {**event(number, target="7789", sender="7777"), "message": message}, number)
    assert freeze(state, other, 20) is None


@pytest.mark.parametrize("streaming", [False, True])
def test_skip_is_a_single_successful_round_and_preserves_history(qq_client, clock, streaming):
    client, state, upstream = qq_client
    p, session, connection, batch = followup(qq_client, clock, streaming=streaming)
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}")), completion(content="must not call again")]
    batch, run = execute(qq_client, batch)
    assert batch.status == "done" and run.status == "DONE" and run.error_code is None
    assert run.metadata["qq_reply"] == {"sent_count": 0, "message_limit": 4, "limit_reached": False, "skipped": True}
    assert len(upstream.calls) == 1 and len(upstream.turns) == 1 and len(connection.calls) == 1
    assert upstream.calls[0]["tool_choice"] == "required"
    assert [t["function"]["name"] for t in upstream.calls[0]["tools"]] == ["qq_send_message", "qq_skip_reply"]
    model_step = next(step for step in state.runs.list_steps(run.run_id) if step.kind == "model")
    snapshot = state.runs.get_context_snapshot(model_step.step_id)
    assert snapshot.request.tool_choice == "required"
    assert any(source.kind == "qq_runtime" for source in snapshot.sources)
    assert "follow-up batch" in upstream.calls[0]["messages"][0]["content"]
    assert not state.qq.store.get(QQBinding, session["session_id"]).paused
    assert state.runs.get_harness_state(run.run_id) == {}
    context = build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(), None)
    assert any("a follow-up" in str(m.get("content")) for m in context.messages)
    assert not any(call.function.name == "qq_skip_reply" for m in context.messages for call in m.get("tool_calls", []))
    public_batch = ok(client.get(f"/api/qq/sessions/{session['session_id']}/batches"))["items"][0]
    assert public_batch["trigger_kind"] == "followup" and "participants_json" not in public_batch
    assert "window_kind" not in ok(client.get(f"/api/qq/sessions/{session['session_id']}"))


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("skip_first", [False, True])
def test_mixed_send_and_skip_obeys_call_order(qq_client, clock, streaming, skip_first):
    _, state, upstream = qq_client
    p, session, connection, batch = followup(qq_client, clock, streaming=streaming)
    clock[0] = 40
    send = tool_call("qq_send_message", {"text": "follow-up reply"}, "send")
    skip = tool_call("qq_skip_reply", "{}", "skip")
    upstream.turns = [completion(*([skip, send] if skip_first else [send, skip])), completion(content="end")]
    batch, run = execute(qq_client, batch)
    assert batch.status == "done" and run.metadata["qq_reply"]["skipped"] == skip_first
    assert len(connection.calls) == (1 if skip_first else 2)
    assert participant(state, session).expires_at == (40 if skip_first else 85)
    steps = [step for step in state.runs.list_steps(run.run_id) if step.kind == "tool"]
    assert [s.status for s in steps] == ["completed", "skipped"]
    assert steps[1].error_code == ("QQ_REPLY_SKIPPED" if skip_first else "TOOL_NOT_ALLOWED")
    assert len(upstream.calls) == (1 if skip_first else 2)
    if not skip_first:
        assert [t["function"]["name"] for t in upstream.calls[1]["tools"]] == ["qq_send_message"]
        assert upstream.calls[1]["tool_choice"] == "auto"


@pytest.mark.parametrize("private", [False, True])
def test_required_batches_reject_skip_and_can_still_send(qq_client, clock, private):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    if private:
        session = child(client, p, "9999", "friend")
    ingest(client, state, p, event(1, kind="private" if private else "group"), 0)
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}")),
        completion(tool_call("qq_send_message", {"text": "required reply"}, "send")), completion(content="end")]
    batch, run = execute(qq_client, freeze(state, session, 5))
    assert batch.status == "done" and batch.trigger_kind == ("private" if private else "keyword")
    assert not run.metadata["qq_reply"]["skipped"] and len(connection.calls) == 1
    assert all([t["function"]["name"] for t in call["tools"]] == ["qq_send_message"] for call in upstream.calls)
    assert json.loads(upstream.calls[1]["messages"][-1]["content"])["error_code"] == "TOOL_NOT_ALLOWED"


@pytest.mark.parametrize("arguments", [None, '{"sender_id":"9999"}', '{"reason":"unnecessary"}', '[]'])
def test_no_reply_without_a_valid_skip_is_still_a_failure(qq_client, clock, arguments):
    _, state, upstream = qq_client
    p, session, connection, batch = followup(qq_client, clock)
    upstream.turns = ([] if arguments is None else [completion(tool_call("qq_skip_reply", arguments))]) + [completion(content="silent prose")]
    batch, run = execute(qq_client, batch)
    assert batch.status == "failed" and run.error_code == "QQ_REPLY_REQUIRED"
    assert not run.metadata["qq_reply"]["skipped"] and run.metadata["qq_reply"]["sent_count"] == 0
    assert participant(state, session).expires_at == 60 and len(connection.calls) == 1
    assert state.qq.store.get(QQBinding, session["session_id"]).paused


def test_skip_preserves_new_keywords_pending_windows_and_queued_batches(qq_client, clock):
    client, state, upstream = qq_client
    p, session, connection, first = followup(qq_client, clock)
    ingest(client, state, p, event(3, "another follow-up"), 20)
    second = freeze(state, session, 25)
    ingest(client, state, p, event(4, "pending follow-up"), 30)
    clock[0] = 31
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}"))]
    assert execute(qq_client, first)[0].status == "done"
    assert participant(state, session).expires_at == 31
    assert state.qq.store.get(QQBatch, second.id).status == "queued"
    assert state.qq.store.get(QQBinding, session["session_id"]).deadline == 35
    ingest(client, state, p, event(5, "latched after skip"), 34)
    third = freeze(state, session, 39)
    assert third.trigger_kind == "followup" and len(state.qq.store.batch_messages(third.id)) == 2
    clock[0] = 70
    reply(upstream)
    assert execute(qq_client, second)[0].status == "done"
    assert participant(state, session).expires_at == 115
    # A newer keyword is independent of the pending old follow-up decision.
    ingest(client, state, p, event(6, "bot new topic"), 71)
    new_epoch = participant(state, session).keyword_message_id
    assert new_epoch != third.participants["9999"]
    clock[0] = 72
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}"))]
    assert execute(qq_client, third)[0].status == "done"
    assert participant(state, session).expires_at == 131
    assert freeze(state, session, 76).trigger_kind == "keyword"


def test_multiple_confirmations_renew_only_batch_speakers_and_survive_failure(qq_client, clock):
    client, state, upstream = qq_client
    p, session, connection, batch = followup(qq_client, clock)
    # A different participant qualifies after this batch was frozen.
    ingest(client, state, p, event(3, "bot", sender="8888"), 20)
    original = connection.call
    async def confirm_or_fail(action, params):
        if len(connection.calls) == 1:
            clock[0] = 40
        elif len(connection.calls) == 2:
            assert participant(state, session).expires_at == 85
            clock[0] = 50
        else:
            assert participant(state, session).expires_at == 95
            raise TimeoutError()
        return await original(action, params)
    connection.call = confirm_or_fail
    upstream.turns = [completion(*(tool_call("qq_send_message", {"text": str(n)}, f"send{n}") for n in range(3)))]
    batch, run = execute(qq_client, batch)
    assert batch.status == "failed" and run.error_code == "QQ_DELIVERY_UNKNOWN"
    assert run.metadata["qq_reply"]["sent_count"] == 2
    assert participant(state, session).expires_at == 95
    assert participant(state, session, "8888").expires_at == 80


def test_participant_state_and_frozen_policy_survive_store_recovery(qq_client):
    client, state, _ = qq_client
    p = project(client, keywords=["bot"])
    session = child(client, p)
    ingest(client, state, p, event(1), 0)
    queued = freeze(state, session, 5)
    ingest(client, state, p, event(2, "follow-up"), 59)
    restored = QQStore(state.qq.store.engine)
    restored.recover()
    assert restored.get(QQBatch, queued.id).participants == queued.participants
    assert restored.get(QQBinding, session["session_id"]).deadline == 64
    assert restored.get(QQParticipant, (session["session_id"], "9999")).in_window
    assert restored.get(QQParticipant, (session["session_id"], "9999")).expires_at == 60
    state.qq.store = restored
    ingest(client, state, p, event(3, "after restart and expiry"), 63)
    batch = freeze(state, session, 68)
    assert batch.trigger_kind == "followup" and set(batch.participants) == {"9999"}
    ok(client.delete(f"/api/sessions/{session['session_id']}"))
    with Session(restored.engine) as db:
        assert not db.exec(select(QQParticipant)).all()


def test_skip_stays_out_of_general_tools_and_public_snapshot_state(qq_client):
    client, state, _ = qq_client
    tools = ok(client.get("/api/tools"))
    assert not {"qq_send_message", "qq_skip_reply"}.intersection(t["name"] for t in tools)
    session = ok(client.post("/api/sessions", json={}))
    assert "qq_skip_reply" not in session["tools_allowed"]
    assert client.patch(f"/api/sessions/{session['session_id']}", json={"tools_allowed": ["qq_skip_reply"]}).status_code == 422
    assert client.post("/api/tools/qq_skip_reply/call", json={"session_id": session["session_id"], "arguments": {}}).status_code == 400
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert schemas["QQBatchResponse"]["properties"]["trigger_kind"]["enum"] == ["keyword", "followup", "private", "icebreaker"]
    assert "participants_json" not in schemas["QQBatchResponse"]["properties"]
    assert "window_kind" not in schemas["QQBindingResponse"]["properties"]


def test_skip_expires_only_submitted_participants_in_the_same_session(qq_client, clock):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    other = child(client, p, "7799")
    ingest(client, state, p, event(1), 0)
    ingest(client, state, p, event(2, sender="8888"), 1)
    ingest(client, state, p, event(3, target="7799", sender="8888"), 2)
    clock[0] = 7
    reply(upstream)
    execute(qq_client, freeze(state, session, 6))
    ingest(client, state, p, event(4, "A follow-up"), 10)
    ingest(client, state, p, event(5, "B follow-up", sender="8888"), 11)
    batch = freeze(state, session, 16, limit=1)
    assert batch.trigger_kind == "followup" and set(batch.participants) == {"8888"}
    clock[0] = 17
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}"))]
    assert execute(qq_client, batch)[0].status == "done"
    assert participant(state, session, "8888").expires_at == 17
    assert participant(state, session).expires_at == 60
    assert participant(state, other, "8888").expires_at == 62


def test_cancellation_wins_when_a_skip_has_just_completed(qq_client, clock, monkeypatch):
    from ai_workbench.core.schema.run import RunStatus
    _, state, upstream = qq_client
    p, session, connection, batch = followup(qq_client, clock)
    original = state.qq.skip
    async def skip_then_cancel(context):
        result = await original(context)
        state.runs.update_status(context.run_id, RunStatus.RUNNING, cancel_requested=True)
        return result
    monkeypatch.setattr(state.qq, "skip", skip_then_cancel)
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}"), tool_call("qq_send_message", {"text": "never send"}, "send"))]
    batch, run = execute(qq_client, batch)
    assert batch.status == "cancelled" and run.status == "CANCELLED" and run.error_code == "RUN_CANCELLED"
    assert run.metadata["qq_reply"]["skipped"] and len(connection.calls) == 1
    assert len(upstream.calls) == 1 and state.qq.store.get(QQBinding, session["session_id"]).paused
