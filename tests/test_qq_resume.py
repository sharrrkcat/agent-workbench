"""Manual QQ recovery coalesces unsubmitted inputs without replaying old replies."""
import asyncio

import pytest
from sqlmodel import Session, select

from ai_workbench.core.attachments import resolve_attachment_uri
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQMessage
from tests.model_fixtures import configure_model
from tests.test_qqbot import qq_client, child, configure_execution, event, freeze, ingest
from tests.test_qq_followup import clock, execute, participant
from tests.test_qq_media import isolated_attachments, image_event, prepare_images, finish_pending
from tests.tool_fixtures import completion, ok, tool_call


def control(client, session, action):
    return ok(client.post(f"/api/qq/sessions/{session['session_id']}/control", json={"action": action}))


def messages(state, session):
    return {row["external_id"]: row for row in state.qq.store.page(QQMessage, session["session_id"], limit=100)["items"]}


@pytest.mark.parametrize("reply_limit", [1, 4])
def test_resume_merges_windows_and_uses_one_project_reply_budget(qq_client, clock, reply_limit):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=reply_limit)
    control(client, session, "pause")
    batches = []
    for number, now in ((1, 0), (2, 7), (3, 14)):
        ingest(client, state, p, event(number, f"bot input-{number}"), now)
        batches.append(freeze(state, session, now + 5))
    ingest(client, state, p, event(4, "bot input-4"), 21)
    ingest(client, state, p, event(5, "input-5"), 22)
    before = participant(state, session)
    ok(client.patch(f"/api/projects/{p['id']}", json={"batch_message_limit": 3}))
    clock[0] = 23
    binding = control(client, session, "resume")
    merged = state.qq.store.next_batch(p["id"])
    assert not binding["paused"] and binding["deadline"] is None and binding["history_version"] == 1
    assert merged.id > batches[-1].id and merged.created_at == 23 and merged.trigger_kind == "keyword"
    assert all(state.qq.store.get(QQBatch, batch.id) is None for batch in batches)
    submitted = state.qq.store.batch_messages(merged.id)
    assert [row.external_id for row in submitted] == ["3", "4", "5"]
    assert merged.text == "\n".join(f"[{row.timestamp}][{row.sender_name}]:{row.text}" for row in submitted)
    rows = messages(state, session)
    assert all(rows[str(n)]["disposition"] == "skipped" and rows[str(n)]["batch_id"] is None for n in (1, 2))
    assert rows["1"]["text"] == "bot input-1"
    assert merged.participants == {"9999": before.grant_message_id}
    after = participant(state, session)
    assert (after.grant_message_id, after.expires_at, after.in_window) == (before.grant_message_id, before.expires_at, False)
    assert control(client, session, "resume")["history_version"] == 1
    assert state.qq.store.next_batch(p["id"]).id == merged.id
    client.portal.call(state.qq.execute, batches[-1])
    assert upstream.calls == [] and connection.calls == [], "A selected old queue entry cannot execute after replacement"
    upstream.turns = [completion(*(tool_call("qq_send_message", {"text": f"reply-{n}"}, f"send_{n}")
        for n in range(reply_limit + 1)))]
    batch, run = execute(qq_client, merged)
    assert batch.status == "done"
    assert run.metadata["qq_reply"] == {"sent_count": reply_limit, "message_limit": reply_limit,
        "limit_reached": True, "skipped": False}
    assert len(connection.calls) == reply_limit and len(upstream.calls) == 1
    assert state.qq.store.next_batch(p["id"]) is None
    assert freeze(state, session, 1000) is None
    context = build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(), None).model_dump_json()
    assert "input-1" not in context and "input-2" not in context
    assert all(f"input-{n}" in context for n in (3, 4, 5))
    ingest(client, state, p, event(6, "bot fresh input"), 30)
    assert [row.external_id for row in state.qq.store.batch_messages(freeze(state, session, 35).id)] == ["6"]


@pytest.mark.parametrize("skip,new_keyword", [(False, False), (True, False), (True, True)])
def test_resume_followup_uses_only_retained_speakers_and_preserves_new_epochs(qq_client, clock, skip, new_keyword):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    ingest(client, state, p, event(1), 0)
    ingest(client, state, p, event(2, sender="8888"), 1)
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "initial reply"}))]
    execute(qq_client, freeze(state, session, 6))
    grant = participant(state, session).grant_message_id
    control(client, session, "pause")
    ingest(client, state, p, event(3, "first follow-up"), 10)
    assert freeze(state, session, 15).trigger_kind == "followup"
    ingest(client, state, p, event(4, "other participant", sender="8888"), 17)
    assert freeze(state, session, 22).trigger_kind == "followup"
    ingest(client, state, p, event(5, "last follow-up"), 23)
    ok(client.patch(f"/api/projects/{p['id']}", json={"batch_message_limit": 1}))
    clock[0] = 100
    control(client, session, "resume")
    batch = state.qq.store.next_batch(p["id"])
    assert batch.trigger_kind == "followup" and batch.participants == {"9999": grant}
    assert participant(state, session).expires_at == 60
    assert participant(state, session, "8888").expires_at == 61
    if new_keyword:
        ingest(client, state, p, event(6, "bot new keyword"), 101)
        assert participant(state, session).grant_message_id != grant
    clock[0] = 102
    upstream.turns = [completion(tool_call("qq_skip_reply", "{}")) if skip else
        completion(tool_call("qq_send_message", {"text": "continued"}))]
    batch, run = execute(qq_client, batch)
    assert batch.status == "done" and run.metadata["qq_reply"]["skipped"] == skip
    assert len(connection.calls) == (1 if skip else 2)
    assert participant(state, session).expires_at == (161 if new_keyword else 102 if skip else 147)
    assert participant(state, session, "8888").expires_at == 61
    if new_keyword:
        assert freeze(state, session, 106).trigger_kind == "keyword"
    else:
        assert freeze(state, session, 200) is None


@pytest.mark.parametrize("private", [False, True])
def test_resume_mandatory_policy_survives_keyword_truncation(qq_client, clock, private):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, batch_message_limit=1, reply_message_limit=1)
    if private:
        session = child(client, p, "9999", "friend")
    kind = "private" if private else "group"
    control(client, session, "pause")
    ingest(client, state, p, event(1, "bot keyword", kind=kind), 0)
    first = freeze(state, session, 5)
    ingest(client, state, p, event(2, "latest context", kind=kind, sender="9999" if private else "8888"), 10)
    clock[0] = 11
    control(client, session, "resume")
    batch = state.qq.store.next_batch(p["id"])
    assert batch.trigger_kind == ("private" if private else "keyword")
    assert [row.external_id for row in state.qq.store.batch_messages(batch.id)] == ["2"]
    assert batch.participants == {} and state.qq.store.get(QQBatch, first.id) is None
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "one reply"}))]
    _, run = execute(qq_client, batch)
    assert run.status == "DONE"
    assert "qq_skip_reply" not in {tool["function"]["name"] for tool in upstream.calls[0]["tools"]}


def test_resume_without_trigger_or_with_deleted_window_does_not_create_work(qq_client, clock):
    client, state, _ = qq_client
    p, session, _ = configure_execution(client, state)
    control(client, session, "pause")
    ingest(client, state, p, event(1, "ordinary group conversation", sender="8888"), 0)
    assert control(client, session, "resume")["history_version"] == 0
    assert state.qq.store.next_batch(p["id"]) is None
    assert messages(state, session)["1"]["disposition"] == "pending"
    control(client, session, "pause")
    ingest(client, state, p, event(2), 10)
    for row in messages(state, session).values():
        ok(client.delete(f"/api/qq/sessions/{session['session_id']}/messages/{row['id']}"))
    clock[0] = 11
    result = control(client, session, "resume")
    assert result["deadline"] is None and result["history_version"] == 2
    assert not participant(state, session).in_window
    assert state.qq.store.page(QQBatch, session["session_id"])["items"] == []
    control(client, session, "pause")
    ingest(client, state, p, event(3, "bot previously truncated"), 20)
    ingest(client, state, p, event(4, "retained context"), 21)
    freeze(state, session, 26, limit=1)
    control(client, session, "resume")
    batch = state.qq.store.next_batch(p["id"])
    assert [row.external_id for row in state.qq.store.batch_messages(batch.id)] == ["4"]
    assert messages(state, session)["3"]["disposition"] == "skipped"


def test_resume_requeues_only_the_paused_session_at_the_project_tail(qq_client, clock):
    client, state, _ = qq_client
    p, session, _ = configure_execution(client, state)
    other = child(client, p, "6677")
    control(client, session, "pause")
    ingest(client, state, p, event(1), 0)
    first = freeze(state, session, 5)
    ingest(client, state, p, event(2, target="6677"), 7)
    untouched = freeze(state, other, 12)
    assert control(client, other, "resume")["history_version"] == 0
    assert state.qq.store.get(QQBatch, untouched.id).model_dump() == untouched.model_dump()
    control(client, session, "resume")
    assert state.qq.store.get(QQBatch, first.id) is None
    assert state.qq.store.next_batch(p["id"]).id == untouched.id
    with Session(state.qq.store.engine) as db:
        ids = db.exec(select(QQBatch.id).where(QQBatch.status == "queued").order_by(QQBatch.id)).all()
    assert len(ids) == 2 and ids[0] == untouched.id
    assert state.qq.store.get(QQBatch, ids[1]).session_id == session["session_id"]


def test_resume_waits_for_existing_nicknames_but_not_later_arrivals(qq_client, clock):
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, keywords=["buddy"])
    sid = session["session_id"]
    control(client, session, "pause")

    async def scenario():
        old_entered, old_release = asyncio.Event(), asyncio.Event()
        new_entered, new_release = asyncio.Event(), asyncio.Event()

        async def lookup(action, params):
            entered, release = (old_entered, old_release) if params["user_id"] == 7777 else (new_entered, new_release)
            entered.set()
            await release.wait()
            return {"user_id": params["user_id"], "card": "Buddy"}

        connection.call = lookup
        await state.qq.ingest(p["id"], {**event(1), "message": "[CQ:at,qq=7777]"}, now=0)
        await asyncio.wait_for(old_entered.wait(), 1)
        await state.qq.ingest(p["id"], event(2, "old bystander", sender="8888"), now=7)
        resume = asyncio.create_task(state.qq.control(sid, "resume"))
        repeated = asyncio.create_task(state.qq.control(sid, "resume"))
        await asyncio.sleep(0)
        assert not resume.done() and state.qq.store.get(QQBinding, sid).paused
        await state.qq.ingest(p["id"], {**event(3), "message": "[CQ:at,qq=6666]"}, now=20)
        await asyncio.wait_for(new_entered.wait(), 1)
        await state.qq.ingest(p["id"], event(4, "later continuation"), now=21)
        old_release.set()
        bindings = await asyncio.wait_for(asyncio.gather(resume, repeated), 1)
        assert all(not binding.paused for binding in bindings)
        assert not new_release.is_set() and state.qq.pending_ingress[sid][0].message.external_id == "3"
        merged = state.qq.store.next_batch(p["id"])
        assert [row.external_id for row in state.qq.store.batch_messages(merged.id)] == ["1", "2"]
        assert state.sessions.get_session(sid).history_version == 1, "Concurrent resumes replace backlog only once"
        assert all(messages(state, session)[key]["batch_id"] is None for key in ("3", "4"))
        assert freeze(state, session, 100) is None
        new_release.set()
        await state.qq.wait_ingress(sid)
        fresh = freeze(state, session, 26)
        assert fresh.id > merged.id
        assert [row.external_id for row in state.qq.store.batch_messages(fresh.id)] == ["3", "4"]
        assert [row.external_id for row in state.qq.store.batch_messages(merged.id)] == ["1", "2"]

    client.portal.call(scenario)


def test_resume_lookup_timeout_and_late_names_do_not_retrigger(qq_client, monkeypatch):
    import ai_workbench.core.qq_names as names

    monkeypatch.setattr(names, "LOOKUP_SECONDS", 0.02)
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, keywords=["buddy"])
    sid = session["session_id"]
    control(client, session, "pause")

    async def scenario():
        async def lookup(action, params):
            await asyncio.Event().wait()

        connection.call = lookup
        await state.qq.ingest(p["id"], {**event(1), "message": "[CQ:at,qq=7777]"}, now=0)
        binding = await asyncio.wait_for(state.qq.control(sid, "resume"), 1)
        assert not binding.paused and binding.deadline is None
        assert not state.qq.pending_ingress and participant(state, session) is None
        state.qq.names._remember(p["id"], (sid, "7777"), "Buddy")
        assert freeze(state, session, 100) is None
        assert state.qq.store.next_batch(p["id"]) is None
        await state.qq.ingest(p["id"], {**event(2), "message": "[CQ:at,qq=7777]"}, now=101)
        assert freeze(state, session, 106).trigger_kind == "keyword"
        assert participant(state, session).grant_message_id == messages(state, session)["2"]["id"]

    client.portal.call(scenario)


def test_connection_change_discards_nickname_decisions_during_resume(qq_client):
    from ai_workbench.api.routes.projects import update_project

    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, keywords=["buddy"])
    sid = session["session_id"]
    control(client, session, "pause")
    ingest(client, state, p, event(1, "buddy"), 0)
    original = freeze(state, session, 5)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def lookup(action, params):
            entered.set()
            await release.wait()
            return {"user_id": params["user_id"], "card": "Buddy"}

        connection.call = lookup
        await state.qq.ingest(p["id"], {**event(2, sender="8888"), "message": "[CQ:at,qq=7777]"}, now=10)
        await asyncio.wait_for(entered.wait(), 1)
        resume = asyncio.create_task(state.qq.control(sid, "resume"))
        await asyncio.sleep(0)
        await update_project(p["id"], {"connection_enabled": False}, state)
        binding = await asyncio.wait_for(resume, 1)
        assert not binding.paused and not state.qq.pending_ingress
        merged = state.qq.store.next_batch(p["id"])
        assert merged.id > original.id and merged.trigger_kind == "keyword"
        assert state.qq.store.get(QQBatch, original.id) is None
        assert participant(state, session, "8888") is None
        release.set()
        await asyncio.gather(*state.qq.names.inflight.values())
        assert participant(state, session, "8888") is None and freeze(state, session, 100) is None
        await state.qq.execute(merged)
        assert state.qq.store.get(QQBatch, merged.id).status == "queued", "A disabled connection cannot dispatch the merged input"

    client.portal.call(scenario)


@pytest.mark.parametrize("keep_generation_keyword", [False, True])
def test_resume_generation_uses_retained_input_and_preserves_overflow_media(qq_client, monkeypatch, keep_generation_keyword):
    client, state, upstream = qq_client
    model = configure_model(client, kind="image_generation", alias="draw")
    p, session, _ = configure_execution(client, state, reply_message_limit=1,
        image_generation_model_profile_id=model["id"])
    control(client, session, "pause")
    prepare_images(monkeypatch)
    ingest(client, state, p, image_event(1, text="bot 画旧图"), 0)
    old = freeze(state, session, 5)
    client.portal.call(finish_pending, state)
    old_message = state.qq.store.batch_messages(old.id)[0]
    media = state.qq.store.message_media([old_message.id])[old_message.id]
    attachments = [resolve_attachment_uri(item.attachment.uri) for item in media]
    ingest(client, state, p, event(2, "bot 画新图" if keep_generation_keyword else "bot latest input"), 10)
    ingest(client, state, p, event(3, "画已删除的消息"), 11)
    source = freeze(state, session, 16)
    deleted_id = messages(state, session)["3"]["id"]
    ok(client.delete(f"/api/qq/sessions/{session['session_id']}/messages/{deleted_id}"))
    ok(client.patch(f"/api/projects/{p['id']}", json={"batch_message_limit": 1}))
    control(client, session, "resume")
    merged = state.qq.store.next_batch(p["id"])
    assert [row.external_id for row in state.qq.store.batch_messages(merged.id)] == ["2"]
    assert state.qq.store.get(QQBatch, source.id) is None
    deleted = state.qq.store.get(QQMessage, deleted_id)
    assert deleted.deleted and deleted.batch_id is None
    assert messages(state, session)["1"]["disposition"] == "skipped"
    assert [item.id for item in state.qq.store.message_media([old_message.id])[old_message.id]] == [item.id for item in media]
    assert len(attachments) == 2 and all(path.exists() for path in attachments)
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "reply"}))]
    _, run = execute(qq_client, merged)
    assert run.status == "DONE"
    assert state.runs.get_config_snapshot(run.run_id)["qq_image_generation_allowed"] == keep_generation_keyword
    assert ("qq_generate_image" in {tool["function"]["name"] for tool in upstream.calls[0]["tools"]}) == keep_generation_keyword


def test_failed_resume_transaction_preserves_pause_queue_and_window(qq_client, monkeypatch):
    client, state, _ = qq_client
    p, session, _ = configure_execution(client, state)
    control(client, session, "pause")
    ingest(client, state, p, event(1), 0)
    batch = freeze(state, session, 5)
    ingest(client, state, p, event(2), 10)
    before_binding = state.qq.store.get(QQBinding, session["session_id"]).model_dump()
    before_messages = messages(state, session)
    before_participant = participant(state, session).model_dump()

    def fail_history(db, sessions):
        raise RuntimeError("history update failed")

    monkeypatch.setattr(state.qq.store, "advance_history", fail_history)
    with pytest.raises(RuntimeError, match="history update failed"):
        control(client, session, "resume")
    assert state.qq.store.get(QQBinding, session["session_id"]).model_dump() == before_binding
    assert messages(state, session) == before_messages
    assert participant(state, session).model_dump() == before_participant
    assert state.qq.store.get(QQBatch, batch.id).model_dump() == batch.model_dump()
    assert len(state.qq.store.page(QQBatch, session["session_id"])["items"]) == 1
    assert state.sessions.get_session(session["session_id"]).history_version == 0
