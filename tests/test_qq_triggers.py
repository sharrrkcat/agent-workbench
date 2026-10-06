"""Nickname triggers keep receipt ordering without blocking OneBot responses."""
import asyncio
import json

import pytest

from ai_workbench.core.qq_protocol import OneBotConnection
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQMessage, QQParticipant
from tests.test_qqbot import qq_client, child, configure_execution, event, freeze, ingest, project


@pytest.mark.parametrize("message,expected", [
    ([{"type": "at", "data": {"qq": "12345"}}], True),
    ("[CQ:at,qq=12345]", True),
    ([{"type": "at", "data": {"qq": "12345"}}, {"type": "text", "data": {"text": "6"}}], True),
    ("please @12345 reply", True),
    ("12345", False),
    ("@123456", False),
    ("[CQ:at,qq=123456]", False),
    ("[CQ:at,qq=123]45", False),
    ("@123[CQ:image,file=picture]45", False),
    ([{"type": "text", "data": {"text": "@123"}}, {"type": "text", "data": {"text": "45"}}], True),
    ([{"type": "text", "data": {"text": "@12345"}}, {"type": "text", "data": {"text": "6"}}], False),
    ("@012345", False),
    ("[CQ:at,qq=all]", False),
    ("[CQ:reply,id=@12345][CQ:image,file=@12345]", False),
])
def test_builtin_account_trigger_is_complete_and_independent_of_keywords(qq_client, message, expected):
    client, state, _ = qq_client
    p = project(client)
    session = child(client, p)
    ingest(client, state, p, {**event(), "message": message}, 0)
    batch = freeze(state, session, 5)
    assert (batch is not None) == expected
    assert state.projects.get(p["id"]).keywords == []
    if expected:
        assert batch.trigger_kind == "keyword"
        assert state.qq.store.get(QQParticipant, (session["session_id"], "9999")).expires_at == 60


@pytest.mark.parametrize("cq", [False, True])
@pytest.mark.parametrize("card,nickname,expected", [
    ("Our BuDdY", "Account", True),
    ("", "Buddy account", True),
    ("Other card", "Buddy account", False),
    ("QQ", "Buddy account", False),
])
def test_real_mentions_match_group_card_before_nickname(qq_client, cq, card, nickname, expected):
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, keywords=["buddy"])
    calls = []
    async def lookup(action, params):
        calls.append((action, params))
        return {"user_id": params["user_id"], "card": card, "nickname": nickname}
    connection.call = lookup
    message = "[CQ:at,qq=7777]" if cq else [{"type": "at", "data": {"qq": "7777"}}]
    ingest(client, state, p, {**event(), "message": message}, 0)
    client.portal.call(state.qq.wait_ingress, session["session_id"])
    batch = freeze(state, session, 5)
    assert (batch is not None) == expected
    assert calls == [("get_group_member_info", {"user_id": 7777, "group_id": 7788})]
    row, = state.qq.store.page(QQMessage, session["session_id"])["items"]
    assert row["text"] == "@7777" and not json.loads(row["references_json"])[0]["frozen"]


def test_pending_names_preserve_silence_and_other_groups_progress(qq_client):
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, keywords=["buddy"])
    other = child(client, p, "6677")
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def lookup(action, params):
            entered.set()
            await release.wait()
            return {"user_id": params["user_id"], "card": "Buddy"}
        connection.call = lookup
        await state.qq.ingest(p["id"], event(1, "buddy"), now=0)
        await state.qq.ingest(p["id"], {**event(2), "message": "[CQ:at,qq=7777]"}, now=4)
        await asyncio.wait_for(entered.wait(), 1)
        await state.qq.ingest(p["id"], event(3, "a supplement"), now=6)
        await state.qq.ingest(p["id"], event(4, "a bystander", sender="8888"), now=7)
        state.qq.tick_binding(state.projects.get(p["id"]), state.qq.store.get(QQBinding, session["session_id"]), 10)
        assert state.qq.store.next_batch(p["id"]) is None
        assert len(state.qq.store.page(QQMessage, session["session_id"])["items"]) == 4
        await state.qq.ingest(p["id"], event(5, "buddy", target="6677"), now=1)
        state.qq.tick_binding(state.projects.get(p["id"]), state.qq.store.get(QQBinding, other["session_id"]), 6)
        assert state.qq.store.next_batch(p["id"]).session_id == other["session_id"]
        release.set()
        await state.qq.wait_ingress(session["session_id"])
        binding = state.qq.store.get(QQBinding, session["session_id"])
        assert binding.deadline == 11
        state.qq.tick_binding(state.projects.get(p["id"]), binding, 11)
        batch, = state.qq.store.page(QQBatch, session["session_id"])["items"]
        assert batch["trigger_kind"] == "keyword"
        assert [row.external_id for row in state.qq.store.batch_messages(batch["id"])] == ["1", "2", "3", "4"]
        assert state.qq.store.get(QQParticipant, (session["session_id"], "9999")).expires_at == 64
    client.portal.call(scenario)


def test_exact_deadline_excludes_later_recorded_but_unclassified_inputs(qq_client):
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, keywords=["buddy"])
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def lookup(action, params):
            calls.append(params)
            entered.set()
            await release.wait()
            return {"user_id": params["user_id"], "card": "Buddy"}
        connection.call = lookup
        first = {**event(1), "message": "[CQ:at,qq=7777]"}
        await state.qq.ingest(p["id"], first, now=0)
        await asyncio.wait_for(entered.wait(), 1)
        await state.qq.ingest(p["id"], first, now=4)  # Duplicate cannot move the original receipt.
        await state.qq.ingest(p["id"], event(2, "at the deadline"), now=5)
        release.set()
        await state.qq.wait_ingress(session["session_id"])
        first_batch = state.qq.store.next_batch(p["id"])
        assert first_batch.trigger_kind == "keyword"
        assert [row.external_id for row in state.qq.store.batch_messages(first_batch.id)] == ["1"]
        second_batch = freeze(state, session, 10)
        assert second_batch.trigger_kind == "followup"
        assert [row.external_id for row in state.qq.store.batch_messages(second_batch.id)] == ["2"]
        assert len(calls) == 1
    client.portal.call(scenario)


def test_lookup_timeout_finishes_once_and_later_names_only_affect_new_messages(qq_client, monkeypatch):
    import ai_workbench.core.qq_names as names_module
    monkeypatch.setattr(names_module, "LOOKUP_SECONDS", 0.02)
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, keywords=["buddy"])
    async def scenario():
        async def lookup(action, params):
            await asyncio.Event().wait()
        connection.call = lookup
        await state.qq.ingest(p["id"], {**event(1), "message": "[CQ:at,qq=7777]"}, now=0)
        await asyncio.wait_for(state.qq.wait_ingress(session["session_id"]), 1)
        state.qq.names._remember(p["id"], (session["session_id"], "7777"), "Buddy")
        state.qq.tick_binding(state.projects.get(p["id"]), state.qq.store.get(QQBinding, session["session_id"]), 50)
        assert state.qq.store.next_batch(p["id"]) is None
        assert not state.qq.store.get(QQBinding, session["session_id"]).paused
        await state.qq.ingest(p["id"], {**event(2), "message": "[CQ:at,qq=7777]"}, now=51)
        assert freeze(state, session, 56).trigger_kind == "keyword"
    client.portal.call(scenario)


def test_connection_changes_discard_unfinished_trigger_decisions(qq_client):
    from ai_workbench.api.routes.projects import update_project
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, keywords=["buddy"])
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def lookup(action, params):
            entered.set()
            await release.wait()
            return {"user_id": params["user_id"], "card": "Buddy"}
        connection.call = lookup
        await state.qq.ingest(p["id"], {**event(1), "message": "[CQ:at,qq=7777]"}, now=0)
        await asyncio.wait_for(entered.wait(), 1)
        await update_project(p["id"], {"connection_enabled": False}, state)
        release.set()
        await asyncio.gather(*state.qq.names.inflight.values())
        assert not state.qq.pending_ingress
        assert state.qq.store.get(QQParticipant, (session["session_id"], "9999")) is None
        assert freeze(state, session, 100) is None
        assert len(state.qq.store.page(QQMessage, session["session_id"])["items"]) == 1
    client.portal.call(scenario)


def test_pending_lookup_cannot_restore_disabled_icebreaker_settings(qq_client):
    from ai_workbench.api.routes.projects import update_project
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state, keywords=["buddy"], icebreaker_enabled=True)
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def lookup(action, params):
            entered.set()
            await release.wait()
            return {"user_id": params["user_id"], "card": "Other member"}
        connection.call = lookup
        await state.qq.ingest(p["id"], {**event(1), "message": "[CQ:at,qq=7777]"}, now=0)
        await asyncio.wait_for(entered.wait(), 1)
        await update_project(p["id"], {"icebreaker_enabled": False}, state)
        release.set()
        await state.qq.wait_ingress(session["session_id"])
        assert session["session_id"] not in state.qq.icebreaker.groups
        assert freeze(state, session, 100) is None
    client.portal.call(scenario)


def test_nickname_only_ingress_does_not_block_member_or_send_receipts(qq_client):
    from websockets.asyncio.server import serve
    client, state, _ = qq_client
    p, session, _ = configure_execution(client, state, keywords=["buddy"])
    async def scenario():
        querying = asyncio.Event()
        async def server(socket):
            member = None
            async for raw in socket:
                request = json.loads(raw)
                if request["action"] == "get_login_info":
                    await socket.send(json.dumps({"status": "ok", "retcode": 0,
                        "data": {"user_id": 12345, "nickname": "Bot"}, "echo": request["echo"]}))
                    await socket.send(json.dumps({**event(1), "message": "[CQ:at,qq=7777]"}))
                elif request["action"] == "get_group_member_info":
                    member = request
                    querying.set()
                else:
                    await socket.send(json.dumps(event(2, "a supplement")))
                    await socket.send(json.dumps({"status": "ok", "retcode": 0,
                        "data": {"message_id": 1001}, "echo": request["echo"]}))
                    await socket.send(json.dumps({"status": "ok", "retcode": 0,
                        "data": {"user_id": 7777, "card": "Buddy"}, "echo": member["echo"]}))
        async def receive(value):
            await state.qq.ingest(p["id"], value, now=0 if value["message_id"] == 1 else 4)
        async with serve(server, "127.0.0.1", 0) as host:
            config = state.projects.get(p["id"]).model_copy(update={
                "websocket_url": f"ws://127.0.0.1:{host.sockets[0].getsockname()[1]}"})
            connection = OneBotConnection(config, receive)
            state.qq.connections[p["id"]] = connection
            task = asyncio.create_task(connection.run())
            try:
                await asyncio.wait_for(querying.wait(), 2)
                receipt = await asyncio.wait_for(connection.call("send_group_msg", {"group_id": 7788, "message": []}), 2)
                assert receipt == {"message_id": 1001}
                await asyncio.wait_for(state.qq.wait_ingress(session["session_id"]), 2)
                batch = freeze(state, session, 9)
                assert [row.external_id for row in state.qq.store.batch_messages(batch.id)] == ["1", "2"]
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    client.portal.call(scenario)
