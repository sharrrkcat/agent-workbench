"""OneBot mention identity, immutable inputs and bounded asynchronous enrichment."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from ai_workbench.core.qq_names import QQNames, render_mentions, references_adapter
from ai_workbench.core.qq_protocol import normalize, OneBotConnection
from ai_workbench.db.qq_models import QQBinding, QQBatch, QQMessage
from tests.test_qqbot import qq_client, configure_execution, event, ingest, freeze, child
from tests.tool_fixtures import completion, tool_call, ok


@pytest.mark.parametrize("cq", [False, True])
def test_mentions_share_display_and_frozen_model_identity(qq_client, cq):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    sid = session["session_id"]
    ingest(client, state, p, {**event(1, "context", sender="8888"), "sender": {"card": "小明"}}, 0)
    original, queries = connection.call, []
    async def call(action, params):
        if action.startswith("send_"):
            return await original(action, params)
        queries.append((action, params))
        return {"user_id": params["user_id"], "card": "哈基米" if params["user_id"] == 12345 else "小明", "nickname": "Nickname"}
    connection.call = call
    data = event(2)
    data["message"] = ("😀正文 @12345 [CQ:at,qq=12345] &amp; [CQ:at,qq=8888][CQ:at,qq=7777][CQ:at,qq=12345][CQ:at,qq=all][CQ:reply,id=77] bot"
        if cq else [{"type": "text", "data": {"text": "😀正文 @12345 "}}, {"type": "at", "data": {"qq": "12345"}},
            {"type": "text", "data": {"text": " & "}}, *[{"type": "at", "data": {"qq": uid}} for uid in ["8888", "7777", "12345", "all"]],
            {"type": "reply", "data": {"id": "77"}}, {"type": "text", "data": {"text": " bot"}}])
    ingest(client, state, p, data, 1)
    before = state.qq.store.get(QQBinding, sid).deadline
    page = ok(client.get(f"/api/qq/sessions/{sid}/messages"))
    row = page["items"][0]
    assert row["text"] == "😀正文 @12345 @哈基米 & @小明@小明@哈基米@全体成员[引用:77] bot"
    assert row["references"][0] == {"type": "at", "id": "12345", "name": "哈基米", "is_self": True}
    assert len(queries) == 2 and all(q[0] == "get_group_member_info" for q in queries)
    assert state.qq.store.get(QQBinding, sid).deadline == before
    batch = freeze(state, session, 6)
    frozen_original = batch.text
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "reply"})), completion(content="")]
    client.portal.call(state.qq.execute, batch)
    batch = state.qq.store.get(QQBatch, batch.id)
    assert batch.status == "done" and batch.text == frozen_original
    sent_input = upstream.calls[0]["messages"][-1]["content"]
    assert "[Group name（QQ:9999）]" in sent_input
    assert "😀正文 @12345 @哈基米（QQ:12345，你）" in sent_input
    assert "@小明（QQ:8888）@小明（QQ:7777）" in sent_input
    state.qq.names.cache.clear()
    page = ok(client.get(f"/api/qq/sessions/{sid}/messages"))
    assert page["items"][0]["text"] == row["text"] and len(queries) == 2
    assert all(ref.frozen for ref in references_adapter.validate_json(state.qq.store.batch_messages(batch.id)[1].references_json) if ref.type == "at")


def test_names_are_conversation_scoped_and_private_uses_nickname(qq_client):
    client, state, _ = qq_client
    p, group, connection = configure_execution(client, state)
    other = child(client, p, "6677")
    private = child(client, p, "9999", "friend")
    calls = []
    async def lookup(action, params):
        calls.append((action, params))
        return {"user_id": params["user_id"], "card": "Other card", "nickname": "Private name"}
    connection.call = lookup
    ingest(client, state, p, {**event(1, sender="8888"), "sender": {"card": "First card"}}, 0)
    for i, session in enumerate([group, other, private], 2):
        data = event(i, target=session["target_id"], kind="private" if session == private else "group")
        data["message"] = "[CQ:at,qq=8888]"
        ingest(client, state, p, data, 1)
    values = [ok(client.get(f"/api/qq/sessions/{s['session_id']}/messages"))["items"][0]["text"] for s in [group, other, private]]
    assert values == ["@First card", "@Other card", "@Private name"]
    assert calls == [("get_group_member_info", {"user_id": 8888, "group_id": 6677}), ("get_stranger_info", {"user_id": 8888})]


def test_settings_are_snapshotted_before_name_lookup(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, system_prompt="Initial project prompt", reply_message_limit=2)
    original = connection.call
    async def lookup(action, params):
        if action.startswith("send_"):
            return await original(action, params)
        state.project_service.update(p["id"], {"system_prompt": "Changed project prompt", "reply_message_limit": 1})
        return {"user_id": params["user_id"], "nickname": "Bot"}
    connection.call = lookup
    ingest(client, state, p, {**event(1), "message": "bot[CQ:at,qq=12345]"}, 0)
    batch = freeze(state, session, 5)
    upstream.turns = [completion(tool_call("qq_send_message", {"text": str(n)}, f"call{n}")) for n in range(2)]
    client.portal.call(state.qq.execute, batch)
    run = state.runs.get_run(state.qq.store.get(QQBatch, batch.id).run_id)
    assert run.status == "DONE" and run.metadata["qq_reply"]["sent_count"] == 2
    snapshot = state.runs.get_config_snapshot(run.run_id)
    assert snapshot["project_system_prompt"] == "Initial project prompt" and snapshot["qq_reply_message_limit"] == 2
    assert all("Initial project prompt" in call["messages"][0]["content"] for call in upstream.calls)
    assert state.projects.get(p["id"]).reply_message_limit == 1


def test_raw_text_and_unlocated_historical_mentions_are_not_guessed():
    value, keywords, media, _ = normalize(event(1, "@12345 [CQ:at,qq=12345]"))
    assert not json.loads(value["references_json"])  # A OneBot text segment is literal.
    refs = references_adapter.validate_python([{"type": "at", "id": "12345"}])
    assert render_mentions("@12345", refs, for_model=True) == "@12345"


def test_query_sharing_cache_expiry_and_capacity(monkeypatch):
    import ai_workbench.core.qq_names as module
    clock = [0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    async def scenario():
        calls, release = [], asyncio.Event()
        async def lookup(action, params):
            calls.append(params)
            await release.wait()
            return {"user_id": params["user_id"], "card": "Name"}
        names = QQNames({"p": SimpleNamespace(ready=True, call=lookup)})
        binding = SimpleNamespace(project_id="p", session_id="s", target_kind="group", target_id="77")
        first = asyncio.create_task(names._name(binding, "1", "2"))
        second = asyncio.create_task(names._name(binding, "1", "2"))
        while not calls:
            await asyncio.sleep(0)
        release.set()
        assert await first == await second == "Name" and len(calls) == 1
        clock[0] = 599
        assert await names._name(binding, "1", "2") == "Name" and len(calls) == 1
        clock[0] = 600
        await names._name(binding, "1", "2")
        assert len(calls) == 2
        for number in range(1025):
            names.observe(binding, str(number), "Observed")
        assert len(names.cache["p"]) == 1024 and ("s", "0") not in names.cache["p"]
        names.retain_projects(set())
        assert not names.cache
        await names.close()
    asyncio.run(scenario())


def test_lookup_timeout_concurrency_and_negative_cache(monkeypatch):
    import ai_workbench.core.qq_names as module
    monkeypatch.setattr(module, "LOOKUP_SECONDS", .03)
    async def scenario():
        active = peak = calls = 0
        async def lookup(action, params):
            nonlocal active, peak, calls
            calls += 1
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1
        connection = SimpleNamespace(ready=True, call=lookup, login_name="Self")
        names = QQNames({"p": connection})
        binding = SimpleNamespace(project_id="p", session_id="s", target_kind="group", target_id="77")
        values, _, media, _ = normalize({**event(), "message": "".join(f"[CQ:at,qq={n}]" for n in range(1, 21))})
        row = await names.project(binding, "1", [dict(values)], for_model=True)
        await asyncio.gather(*list(names.inflight.values()))
        assert peak == 4 and calls == 4 and active == 0
        assert "（你）" in row[0]["text"] or "@Self（QQ:1，你）" in row[0]["text"]
        assert await names._name(binding, "1", "2") is None and calls == 4
        names.cache["p"][("s", "2")] = (0, None)
        connection.ready = False
        assert await names._name(binding, "1", "2") is None and calls == 4
        await names.close()
    asyncio.run(scenario())


def test_member_queries_do_not_block_ingress_or_receipt_deadlines(qq_client):
    from websockets.asyncio.server import serve
    client, state, _ = qq_client
    p, session, _ = configure_execution(client, state)
    sid = session["session_id"]
    async def scenario():
        received = asyncio.Event()
        async def server(socket):
            async for raw in socket:
                request = json.loads(raw)
                if request["action"] == "get_login_info":
                    data = {"user_id": 12345, "nickname": "Bot"}
                else:
                    await socket.send(json.dumps(event(2, "bot next")))
                    data = {"user_id": 12345, "card": "Bot card"}
                await socket.send(json.dumps({"status": "ok", "retcode": 0, "data": data, "echo": request["echo"]}))
                if request["action"] == "get_login_info":
                    await socket.send(json.dumps({**event(1), "message": "bot[CQ:at,qq=12345]"}))
        async def receive(value):
            await state.qq.ingest(p["id"], value, now=0 if value["message_id"] == 1 else 5)
            received.set()
        async with serve(server, "127.0.0.1", 0) as host:
            project = state.projects.get(p["id"]).model_copy(update={"websocket_url": f"ws://127.0.0.1:{host.sockets[0].getsockname()[1]}"})
            connection = OneBotConnection(project, receive)
            state.qq.connections[p["id"]] = connection
            task = asyncio.create_task(connection.run())
            try:
                await asyncio.wait_for(received.wait(), 5)
                binding = state.qq.store.get(QQBinding, sid)
                rows = state.qq.store.page(QQMessage, sid)["items"]
                projected = await state.qq.names.project(binding, p["bot_account"], rows)
                assert projected[0]["text"] == "bot@Bot card"
                batch = state.qq.store.next_batch(p["id"])
                assert [r.external_id for r in state.qq.store.batch_messages(batch.id)] == ["1"]
                assert state.qq.store.get(QQBinding, sid).deadline == 10
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    client.portal.call(scenario)


@pytest.mark.parametrize("response", [{"user_id": 444, "card": "Wrong account"}, {"nickname": "Missing id"}])
def test_unusable_lookup_retains_ids_and_never_pauses(qq_client, response):
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state)
    calls = []
    async def lookup(action, params):
        calls.append(params)
        return response
    connection.call = lookup
    ingest(client, state, p, {**event(1), "message": "[CQ:at,qq=12345]"}, 0)
    for _ in range(2):
        row = ok(client.get(f"/api/qq/sessions/{session['session_id']}/messages"))["items"][0]
        assert row["text"] == "@12345" and row["references"][0]["is_self"]
    assert len(calls) == 1
    binding = state.qq.store.get(QQBinding, session["session_id"])
    assert not binding.paused and binding.deadline == 5  # The built-in self mention works without a name.
