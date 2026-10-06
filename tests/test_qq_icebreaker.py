"""Quiet-group observation, optional replies and cancellation before dispatch."""
import asyncio
import json

import pytest
from sqlmodel import Session, select

from ai_workbench.core.qq_icebreaker import QQIcebreaker
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQDelivery, QQParticipant
from tests.test_qqbot import qq_client, child, configure_execution, event, freeze, ingest, project
from tests.test_qq_followup import clock, execute, reply, participant, followup
from tests.test_qq_image_generation import image_provider, draw, assets, attachment_files
from tests.test_qq_media import isolated_attachments
from tests.tool_fixtures import completion, ok, tool_call


def binding(state, session):
    return state.qq.store.get(QQBinding, session["session_id"])


def tick(qq_client, session, clock, now):
    client, state, _ = qq_client
    async def advance():
        clock[0] = now
        bound = binding(state, session)
        state.qq.tick_binding(state.projects.get(bound.project_id), bound, now)
    client.portal.call(advance)
    return state.qq.store.next_batch(session["project_id"])


def setup(qq_client, clock, **values):
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, **{
        "icebreaker_enabled": True, "icebreaker_cold_seconds": 10,
        "icebreaker_wait_seconds": 5, "icebreaker_cooldown_seconds": 30, **values})
    tick(qq_client, session, clock, 0)
    return p, session, connection


def queued(qq_client, clock, **values):
    client, state, _ = qq_client
    p, session, connection = setup(qq_client, clock, **values)
    ingest(client, state, p, event(1, "A quiet thought"), 11)
    batch = tick(qq_client, session, clock, 16)
    assert batch.trigger_kind == "icebreaker"
    return p, session, connection, batch


def test_settings_defaults_strict_patch_and_private_state(qq_client):
    client, state, _ = qq_client
    p = project(client)
    fields = {"icebreaker_enabled": False, "icebreaker_cold_seconds": 7200,
        "icebreaker_wait_seconds": 120, "icebreaker_cooldown_seconds": 10800}
    assert {key: p[key] for key in fields} == fields
    url = f"/api/projects/{p['id']}"
    for key in fields:
        invalid = [None, 0, 1, "true"] if key == "icebreaker_enabled" else [None, 0, -1, True, 1.5, "10"]
        for value in invalid:
            assert client.patch(url, json={key: value}).status_code == 422
    changed = {"icebreaker_enabled": True, "icebreaker_cold_seconds": 60,
        "icebreaker_wait_seconds": 7, "icebreaker_cooldown_seconds": 90}
    ok(client.patch(url, json=changed))
    saved = ok(client.patch(url, json={"name": "renamed"}))
    assert {key: saved[key] for key in fields} == changed
    saved = ok(client.patch(url, json={"icebreaker_enabled": False}))
    assert saved["icebreaker_wait_seconds"] == 7
    session = child(client, p)
    state.qq.store.start_icebreaker_cooldown(session["session_id"], 100)
    public = ok(client.get(f"/api/qq/sessions/{session['session_id']}"))
    assert "icebreaker_cooldown_until" not in public
    schemas = client.get('/openapi.json').json()['components']['schemas']
    assert "icebreaker_cooldown_until" not in schemas["QQBindingResponse"]["properties"]
    assert "icebreaker" in schemas["QQBatchResponse"]["properties"]["trigger_kind"]["enum"]


def test_cold_threshold_is_strict_and_supplements_restart_wait(qq_client, clock):
    client, state, _ = qq_client
    p, session, _ = setup(qq_client, clock, batch_message_limit=2)
    ingest(client, state, p, event(1, "Not cold at the boundary"), 10)
    assert tick(qq_client, session, clock, 15) is None
    for number, when in [(2, 21), (3, 24), (4, 28)]:
        ingest(client, state, p, event(number, f"thought {number}"), when)
    assert tick(qq_client, session, clock, 32.99) is None
    batch = tick(qq_client, session, clock, 33)
    assert batch.trigger_kind == "icebreaker"
    assert batch.participants == {"9999": state.qq.store.batch_messages(batch.id)[-1].id}
    assert [m.external_id for m in state.qq.store.batch_messages(batch.id)] == ["3", "4"]
    assert binding(state, session).icebreaker_cooldown_until is None
    ingest(client, state, p, event(5, "after freezing"), 34)
    assert tick(qq_client, session, clock, 50).id == batch.id
    assert [m.external_id for m in state.qq.store.batch_messages(batch.id)] == ["3", "4"]
    assert len(state.qq.store.page(QQBatch, session["session_id"])["items"]) == 1


@pytest.mark.parametrize("when", [13, 16, 20])
def test_second_speaker_cancels_observation_or_queue_without_cooldown(qq_client, clock, when):
    client, state, _ = qq_client
    p, session, _ = setup(qq_client, clock)
    ingest(client, state, p, event(1, "first speaker"), 11)
    if when > 16:
        tick(qq_client, session, clock, 16)
    ingest(client, state, p, event(2, "someone joins", sender="8888"), when)
    assert tick(qq_client, session, clock, 25) is None
    assert all(row["status"] == "cancelled" for row in state.qq.store.page(QQBatch, session["session_id"])["items"])
    assert binding(state, session).icebreaker_cooldown_until is None
    assert not binding(state, session).paused
    ingest(client, state, p, event(3, "fresh quiet period"), 36)
    assert tick(qq_client, session, clock, 41).trigger_kind == "icebreaker"


@pytest.mark.parametrize("message", [
    [{"type": "image", "data": {"file": "picture"}}],
    [{"type": "face", "data": {"id": 1}}],
    "[CQ:image,file=sticker,sub_type=1]",
])
def test_media_qualifies_but_duplicates_empty_malformed_and_echoes_do_not(qq_client, clock, message):
    client, state, _ = qq_client
    p, session, _ = setup(qq_client, clock)
    incoming = {**event(1), "message": message}
    ingest(client, state, p, incoming, 11)
    ingest(client, state, p, incoming, 14)
    ingest(client, state, p, event(2, " \t\n", sender="8888"), 14)
    ingest(client, state, p, {**event(3, sender="8888"), "message": 123}, 14)
    ingest(client, state, p, event(4, sender="12345"), 14)
    batch = tick(qq_client, session, clock, 16)
    assert [m.external_id for m in state.qq.store.batch_messages(batch.id)] == ["1"]


def test_keyword_and_existing_followup_take_priority(qq_client, clock):
    client, state, upstream = qq_client
    p, session, _, batch = queued(qq_client, clock)
    ingest(client, state, p, event(2, "bot please respond"), 17)
    assert state.qq.store.get(QQBatch, batch.id).status == "cancelled"
    normal = tick(qq_client, session, clock, 22)
    assert normal.trigger_kind == "keyword"
    reply(upstream)
    assert execute(qq_client, normal)[0].status == "done"
    ingest(client, state, p, event(3, "still eligible after another quiet period"), 34)
    followup = tick(qq_client, session, clock, 39)
    assert followup.trigger_kind == "followup"
    assert binding(state, session).icebreaker_cooldown_until is None


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("skip", [False, True])
def test_only_confirmed_icebreaker_replies_grant_eligibility(qq_client, clock, streaming, skip):
    client, state, upstream = qq_client
    p, session, connection, batch = queued(qq_client, clock, streaming=streaming)
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}")) if skip else completion(
        tool_call("qq_send_message", {"text": "a brief reply"}, "one"),
        tool_call("qq_send_message", {"text": "must not send"}, "two"))]
    batch, run = execute(qq_client, batch)
    assert batch.status == "done" and run.status == "DONE"
    assert run.metadata["qq_reply"] == {"sent_count": 0 if skip else 1, "message_limit": 1,
        "limit_reached": not skip, "skipped": skip}
    assert len(connection.calls) == (0 if skip else 1)
    assert len(upstream.calls) == 1 and upstream.calls[0]["tool_choice"] == "required"
    assert "optional icebreaker" in str(upstream.calls[0]["messages"])
    assert binding(state, session).icebreaker_cooldown_until == 46
    with Session(state.qq.store.engine) as db:
        participants = db.exec(select(QQParticipant)).all()
    assert len(participants) == (0 if skip else 1)
    if not skip:
        assert participants[0].expires_at == 76
        assert participants[0].grant_message_id == batch.participants["9999"]
    ingest(client, state, p, event(2, "during cooldown"), 30)
    followup = tick(qq_client, session, clock, 35)
    if skip:
        assert followup is None
    else:
        assert followup.trigger_kind == "followup"
        upstream.turns = [completion(tool_call("qq_skip_reply", "{}"))]
        execute(qq_client, followup)
    # Expiring a cooldown alone cannot create a batch.
    assert tick(qq_client, session, clock, 47) is None
    ingest(client, state, p, event(3, "a new quiet conversation"), 48)
    assert tick(qq_client, session, clock, 53).trigger_kind == "icebreaker"


def test_groups_are_independent_and_friends_keep_mandatory_replies(qq_client, clock):
    client, state, upstream = qq_client
    p, first, _, batch = queued(qq_client, clock)
    second, friend = child(client, p, "7789"), child(client, p, "9999", "friend")
    tick(qq_client, second, clock, 0)
    clock[0] = 16
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}"))]
    execute(qq_client, batch)
    ingest(client, state, p, event(2, "another group", target="7789"), 20)
    assert tick(qq_client, second, clock, 25).session_id == second["session_id"]
    assert binding(state, first).icebreaker_cooldown_until == 46
    assert binding(state, second).icebreaker_cooldown_until is None
    ingest(client, state, p, event(3, "private", kind="private"), 20)
    assert freeze(state, friend, 25).trigger_kind == "private"
    assert friend["session_id"] not in state.qq.icebreaker.groups


@pytest.mark.parametrize("stage", ["media", "names", "context", "model"])
def test_other_speaker_cancels_pre_send_work_without_pausing(qq_client, clock, monkeypatch, stage):
    client, state, upstream = qq_client
    p, session, connection, batch = queued(qq_client, clock, image_input_enabled=True)
    blocked = True
    original_handle = upstream.handle
    async def scenario():
        reached = asyncio.Event()
        async def hold(*args, **kwargs):
            reached.set()
            await asyncio.Event().wait()
        if stage == "media":
            monkeypatch.setattr(state.qq.media, "wait_batch", hold)
        elif stage == "names":
            monkeypatch.setattr(state.qq.names, "project", hold)
        elif stage == "context":
            monkeypatch.setattr(state.chat_runner, "_build_context", hold)
        else:
            async def handle(request):
                if blocked:
                    await hold()
                return await original_handle(request)
            monkeypatch.setattr(upstream, "handle", handle)
        worker = asyncio.create_task(state.qq.execute(batch))
        await asyncio.wait_for(reached.wait(), 5)
        assert binding(state, session).icebreaker_cooldown_until == (46 if stage == "model" else None)
        await state.qq.ingest(p["id"], event(2, "joined", sender="8888"), now=17)
        await asyncio.wait_for(worker, 5)
    client.portal.call(scenario)
    current = state.qq.store.get(QQBatch, batch.id)
    assert current.status == "cancelled" and current.error_code == "QQ_ICEBREAKER_CANCELLED"
    assert not binding(state, session).paused and connection.calls == []
    assert state.qq.store.page(QQDelivery, session["session_id"])["items"] == []
    if current.run_id:
        assert state.runs.get_run(current.run_id).status == "CANCELLED"
    # A regular reply still works after automatic cancellation.
    blocked = False
    monkeypatch.undo()
    clock[0] = 20
    ingest(client, state, p, event(3, "bot"), 20)
    normal = tick(qq_client, session, clock, 25)
    reply(upstream)
    assert execute(qq_client, normal)[0].status == "done"


def test_send_boundary_does_not_retract_or_cancel_a_submitted_message(qq_client, clock):
    client, state, upstream = qq_client
    p, session, connection, batch = queued(qq_client, clock)
    original = connection.call
    async def while_sending(action, params):
        await state.qq.ingest(p["id"], event(2, "another person", sender="8888"), now=17)
        return await original(action, params)
    connection.call = while_sending
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "already submitted"}))]
    assert execute(qq_client, batch)[0].status == "done"
    assert len(connection.calls) == 1 and not binding(state, session).paused
    assert binding(state, session).icebreaker_cooldown_until == 46


@pytest.mark.parametrize("change", ["pause", "disconnect", "enabled", "cold", "wait", "cooldown", "connection"])
def test_lifecycle_discards_queue_restarts_clock_and_keeps_cooldown(qq_client, clock, change):
    client, state, _ = qq_client
    p, session, connection, batch = queued(qq_client, clock)
    state.qq.store.start_icebreaker_cooldown(session["session_id"], 20)
    clock[0] = 17
    url = f"/api/projects/{p['id']}"
    if change == "pause":
        ok(client.post(f"/api/qq/sessions/{session['session_id']}/control", json={"action": "pause"}))
        ok(client.post(f"/api/qq/sessions/{session['session_id']}/control", json={"action": "resume"}))
    elif change == "disconnect":
        connection.ready = False
        tick(qq_client, session, clock, 17)
        connection.ready = True
        tick(qq_client, session, clock, 17)
    else:
        field = "connection_enabled" if change == "connection" else f"icebreaker_{change}" if change == "enabled" else f"icebreaker_{change}_seconds"
        value = False if change in {"enabled", "connection"} else {"cold": 12, "wait": 6, "cooldown": 40}[change]
        ok(client.patch(url, json={field: value}))
        if change in {"enabled", "connection"}:
            ok(client.patch(url, json={field: True}))
    assert state.qq.store.get(QQBatch, batch.id).status == "cancelled"
    assert binding(state, session).icebreaker_cooldown_until == 20
    ingest(client, state, p, event(2, "too soon after restoring"), 21)
    assert tick(qq_client, session, clock, 28) is None
    ingest(client, state, p, event(3, "fresh quiet period"), 35)
    assert tick(qq_client, session, clock, 41).trigger_kind == "icebreaker"


@pytest.mark.parametrize("running,send_intent", [(False, False), (True, False), (True, True)])
def test_recovery_cancels_unsent_attempts_but_preserves_uncertain_delivery_policy(qq_client, clock, running, send_intent):
    _, state, _ = qq_client
    _, session, _, batch = queued(qq_client, clock)
    state.qq.store.start_icebreaker_cooldown(session["session_id"], 46)
    if running:
        batch.status, batch.run_id = "running", "interrupted-run"
        state.qq.store.save(batch)
    if send_intent:
        state.qq.store.save(QQDelivery(session_id=session["session_id"], run_id=batch.run_id, tool_call_id="one",
            text="uncertain", status="sending", created_at=17))
    state.qq.store.recover()
    state.qq.icebreaker = QQIcebreaker(state.qq.store)
    current = state.qq.store.get(QQBatch, batch.id)
    assert current.status == ("interrupted" if send_intent else "cancelled")
    assert binding(state, session).paused == send_intent
    assert binding(state, session).icebreaker_cooldown_until == 46
    assert state.qq.store.next_batch(session["project_id"]) is None
    if send_intent:
        assert state.qq.store.page(QQDelivery, session["session_id"])["items"][0]["status"] == "unknown"


@pytest.mark.parametrize("frozen", [False, True])
def test_deleting_all_input_cancels_without_rewinding_activity(qq_client, clock, frozen):
    client, state, _ = qq_client
    p, session, _ = setup(qq_client, clock)
    ingest(client, state, p, event(1, "remove this"), 11)
    if frozen:
        tick(qq_client, session, clock, 16)
    message_id = state.qq.icebreaker.groups[session["session_id"]].first_message_id
    ok(client.delete(f"/api/qq/sessions/{session['session_id']}/messages/{message_id}"))
    assert tick(qq_client, session, clock, 16) is None
    assert state.qq.icebreaker.groups[session["session_id"]].last_activity == 11
    assert binding(state, session).icebreaker_cooldown_until is None


def test_failure_after_model_start_retains_cooldown_and_existing_pause(qq_client, clock):
    _, state, upstream = qq_client
    _, session, _, batch = queued(qq_client, clock)
    upstream.turns = [completion(content="No tool decision")]
    batch, run = execute(qq_client, batch)
    assert batch.status == "failed" and run.error_code == "QQ_REPLY_REQUIRED"
    assert binding(state, session).paused and binding(state, session).icebreaker_cooldown_until == 46


def test_generated_image_shares_the_one_reply_limit(qq_client, clock, image_provider, isolated_attachments):
    _, state, upstream = qq_client
    _, session, connection, batch = queued(qq_client, clock, image_generation_model_profile_id=image_provider.profile["id"])
    upstream.turns = [completion(draw(), tool_call("qq_send_message", {"text": "extra"}, "extra"))]
    batch, run = execute(qq_client, batch)
    assert batch.status == "done" and run.metadata["qq_reply"]["sent_count"] == 1
    assert len(connection.calls) == len(image_provider.calls) == 1
    assert state.qq.store.page(QQDelivery, session["session_id"])["items"][0]["kind"] == "generated_image"
    assert participant(state, session).expires_at == 76


def test_other_speaker_cancels_image_generation_and_releases_assets(qq_client, clock, image_provider, isolated_attachments):
    client, state, upstream = qq_client
    p, session, connection, batch = queued(qq_client, clock, image_generation_model_profile_id=image_provider.profile["id"])
    upstream.turns = [completion(draw())]
    async def scenario():
        reached = asyncio.Event()
        async def hold():
            reached.set()
            await asyncio.Event().wait()
        image_provider.before_return = hold
        worker = asyncio.create_task(state.qq.execute(batch))
        await asyncio.wait_for(reached.wait(), 5)
        await state.qq.ingest(p["id"], event(2, "joined", sender="8888"), now=17)
        await asyncio.wait_for(worker, 5)
    client.portal.call(scenario)
    assert state.qq.store.get(QQBatch, batch.id).status == "cancelled"
    assert binding(state, session).icebreaker_cooldown_until == 46
    assert not binding(state, session).paused and connection.calls == []
    assert assets(state) == [] and attachment_files() == []


@pytest.mark.parametrize("image", [False, True])
def test_last_send_check_cancels_before_intent_and_cleans_prepared_images(
        qq_client, clock, image_provider, isolated_attachments, monkeypatch, image):
    client, state, upstream = qq_client
    p, session, connection, batch = queued(qq_client, clock, image_generation_model_profile_id=image_provider.profile["id"])
    upstream.turns = [completion(draw() if image else tool_call("qq_send_message", {"text": "stale"}))]
    original = state.qq.deliver
    async def before_send(*args, **kwargs):
        await state.qq.ingest(p["id"], event(2, "joined just before sending", sender="8888"), now=17)
        return await original(*args, **kwargs)
    monkeypatch.setattr(state.qq, "deliver", before_send)
    batch, run = execute(qq_client, batch)
    assert batch.status == "cancelled" and run.status == "CANCELLED"
    assert not binding(state, session).paused and binding(state, session).icebreaker_cooldown_until == 46
    assert connection.calls == [] and assets(state) == [] and attachment_files() == []
    assert state.qq.store.page(QQDelivery, session["session_id"])["items"] == []


@pytest.mark.parametrize("arrival,eligible", [(75.99, True), (76, False)])
def test_confirmed_icebreaker_grant_has_an_exact_sixty_second_boundary(qq_client, clock, arrival, eligible):
    client, state, upstream = qq_client
    p, session, _, batch = queued(qq_client, clock)
    reply(upstream)
    execute(qq_client, batch)
    ok(client.patch(f"/api/projects/{p['id']}", json={"icebreaker_enabled": False}))
    ingest(client, state, p, event(2, "a different person", sender="8888"), 17)
    assert freeze(state, session, 22) is None
    ingest(client, state, p, event(3, "the original speaker continues"), arrival)
    followup = freeze(state, session, arrival + 5)
    assert (followup is not None) == eligible
    if eligible:
        assert followup.trigger_kind == "followup" and set(followup.participants) == {"9999"}


def test_icebreaker_followup_renews_and_skip_ends_the_grant(qq_client, clock):
    client, state, upstream = qq_client
    p, session, _, batch = queued(qq_client, clock)
    reply(upstream)
    execute(qq_client, batch)
    ingest(client, state, p, event(2, "continue during cooldown"), 30)
    followup = tick(qq_client, session, clock, 35)
    assert followup.trigger_kind == "followup"
    clock[0] = 70
    reply(upstream)
    execute(qq_client, followup)
    assert participant(state, session).expires_at == 115
    ingest(client, state, p, event(3, "one more thought"), 100)
    followup = tick(qq_client, session, clock, 105)
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}"))]
    execute(qq_client, followup)
    assert participant(state, session).expires_at == 105
    ingest(client, state, p, event(4, "after the skip"), 106)
    assert binding(state, session).deadline is None


@pytest.mark.parametrize("failure,status", [
    (TimeoutError(), "unknown"),
    (ToolExecutionError("QQ_ACTION_FAILED", "rejected"), "failed"),
])
def test_unconfirmed_icebreaker_send_does_not_grant_eligibility(qq_client, clock, failure, status):
    _, state, upstream = qq_client
    _, session, connection, batch = queued(qq_client, clock)
    connection.failure = failure
    reply(upstream)
    execute(qq_client, batch)
    assert participant(state, session) is None
    assert state.qq.store.page(QQDelivery, session["session_id"])["items"][0]["status"] == status


def test_icebreaker_confirmation_preserves_a_newer_keyword_epoch(qq_client, clock):
    _, state, upstream = qq_client
    p, session, connection, batch = queued(qq_client, clock)
    original = connection.call
    async def confirm(action, params):
        clock[0] = 20
        await state.qq.ingest(p["id"], event(2, "@12345"), now=20)
        clock[0] = 30
        return await original(action, params)
    connection.call = confirm
    reply(upstream)
    execute(qq_client, batch)
    grant = participant(state, session)
    assert grant.grant_message_id > batch.participants["9999"]
    assert grant.expires_at == 90 and binding(state, session).deadline == 25
    stale = QQBatch(session_id=session["session_id"], project_id=p["id"], text="old decision", created_at=16,
        trigger_kind="followup", participants_json=json.dumps(batch.participants))
    state.qq.store.skip_participants(stale, 31)
    assert participant(state, session).expires_at == 90


def test_repeated_receipts_and_recovery_do_not_extend_icebreaker_grants(qq_client, clock, monkeypatch):
    client, state, upstream = qq_client
    p, session, connection, batch = queued(qq_client, clock)
    original = state.qq.send
    async def repeated(arguments, context):
        receipt = await original(arguments, context)
        clock[0] = 40
        assert await original(arguments, context) == receipt
        return receipt
    monkeypatch.setattr(state.qq, "send", repeated)
    reply(upstream)
    execute(qq_client, batch)
    assert len(connection.calls) == 1 and participant(state, session).expires_at == 76
    ingest(client, state, p, {**event(1001, "echo", sender="12345"), "post_type": "message_sent"}, 50)
    state.qq.store.recover()
    assert participant(state, session).expires_at == 76
    assert participant(state, session).grant_message_id == batch.participants["9999"]


def test_icebreaker_waits_for_prior_nickname_decision_before_sending(qq_client, clock, monkeypatch):
    client, state, upstream = qq_client
    p, session, connection, batch = queued(qq_client, clock, keywords=["buddy"])
    reply(upstream)
    original = state.qq.deliver
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def lookup(action, params):
            assert action == "get_group_member_info"
            entered.set()
            await release.wait()
            return {"user_id": params["user_id"], "card": "Buddy"}
        connection.call = lookup
        async def before_send(text, context, **options):
            await state.qq.ingest(p["id"], {**event(2), "message": "[CQ:at,qq=7777]"}, now=17)
            return await original(text, context, **options)
        monkeypatch.setattr(state.qq, "deliver", before_send)
        task = asyncio.create_task(state.qq.execute(batch))
        await asyncio.wait_for(entered.wait(), 2)
        assert state.qq.store.page(QQDelivery, session["session_id"])["items"] == []
        release.set()
        await asyncio.wait_for(task, 2)
        current = state.qq.store.get(QQBatch, batch.id)
        assert current.error_code == "QQ_ICEBREAKER_CANCELLED"
        assert state.qq.store.page(QQDelivery, session["session_id"])["items"] == []
        assert participant(state, session).expires_at == 77  # Only the incoming nickname granted eligibility.
    client.portal.call(scenario)


@pytest.mark.parametrize("icebreaker", [False, True])
def test_deferred_arrivals_cannot_use_a_later_send_to_gain_eligibility(qq_client, clock, icebreaker):
    client, state, upstream = qq_client
    p, session, connection, batch = queued(qq_client, clock) if icebreaker else followup(qq_client, clock)
    reply(upstream)
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def call(action, params):
            if action == "get_group_member_info":
                entered.set()
                await release.wait()
                return {"user_id": params["user_id"], "card": "Unrelated member"}
            clock[0] = 70
            await state.qq.ingest(p["id"], {**event(9), "message": "[CQ:at,qq=7777]"}, now=70)
            await asyncio.wait_for(entered.wait(), 1)
            clock[0] = 71
            return {"message_id": 1099}
        connection.call = call
        await state.qq.execute(batch)
        assert participant(state, session).expires_at == (131 if icebreaker else 116)
        release.set()
        await state.qq.wait_ingress(session["session_id"])
        assert binding(state, session).deadline is None
        await state.qq.ingest(p["id"], event(10, "received after confirmation"), now=72)
        assert freeze(state, session, 77).trigger_kind == "followup"
    client.portal.call(scenario)
