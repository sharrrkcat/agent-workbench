"""Shared QQ resources, positional image budgets and optional descriptions."""
import asyncio
import json
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pytest
from sqlmodel import Session, select

from ai_workbench.core.attachments import resolve_attachment_uri
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.db.qq_models import QQMediaAsset, QQBatch
from tests.test_qqbot import qq_client, configure_execution, child, project, event, ingest, freeze
from tests.test_qq_media import isolated_attachments, image_event, finish_pending, page, prepare_images, reply
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ok


def resources(state):
    with Session(state.qq.store.engine) as db:
        return db.exec(select(QQMediaAsset).order_by(QQMediaAsset.id)).all()


def test_shared_files_descriptions_and_last_reference_cleanup(qq_client, monkeypatch):
    client, state, _ = qq_client
    prepare_images(monkeypatch)
    first = project(client)
    second = project(client, bot_account="54321")
    sessions = [child(client, first), child(client, first, "9988", "friend"), child(client, second)]
    for number, (p, session) in enumerate(zip([first, first, second], sessions), 1):
        data = image_event(number)
        data.update(self_id=int(p["bot_account"]), message_type="private" if number == 2 else "group",
            user_id=9988 if number == 2 else 9999)
        ingest(client, state, p, data, number)
    client.portal.call(finish_pending, state)
    assert len(resources(state)) == 2
    rows = [page(client, session)[0] for session in sessions]
    ids = [[s["asset_id"] for s in row["segments"] if s["type"] == "image"] for row in rows]
    assert ids[0] == ids[1] == ids[2]
    attachments = [[s["attachment"]["id"] for s in row["segments"] if s["type"] == "image"] for row in rows]
    assert attachments[0] == attachments[1] == attachments[2]
    asset_id = ids[0][0]
    assert state.qq.store.update_description(asset_id, "红色图片") == {s["session_id"] for s in sessions}
    for session in sessions:
        assert page(client, session)[0]["segments"][1]["description"] == "红色图片"
        assert state.sessions.get_session(session["session_id"]).history_version == 1
    paths = {resolve_attachment_uri(value.uri) for asset in resources(state)
        for value in (asset.attachment, asset.model_attachment) if value}
    assert len(paths) == 3
    ok(client.delete(f"/api/qq/sessions/{sessions[0]['session_id']}/messages/{rows[0]['id']}"))
    ok(client.delete(f"/api/sessions/{sessions[1]['session_id']}"))
    assert len(resources(state)) == 2 and all(path.exists() for path in paths)
    ok(client.delete(f"/api/projects/{second['id']}"))
    assert resources(state) == [] and all(not path.exists() for path in paths)
    assert state.qq.store.update_description(asset_id, "late", only_if_empty=True) == set()


@pytest.mark.parametrize("pictures,stickers,expected", [(0, 0, []), (5, 0, list(range(5))),
    (6, 0, list(range(1, 6))), (10, 10, list(range(5, 10))), (2, 6, [0, 1, 5, 6, 7]), (0, 6, list(range(1, 6)))])
def test_current_image_priority_and_live_history_descriptions(qq_client, monkeypatch, pictures, stickers, expected):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, image_input_enabled=True)
    async def fetch(url, policy, *, max_bytes):
        output = BytesIO()
        Image.new("RGB", (12, 8), (int(url.rsplit("/", 1)[-1]), 20, 30)).save(output, "PNG")
        return output.getvalue(), url, "image/png"
    monkeypatch.setattr("ai_workbench.core.qq_media.fetch_bytes", fetch)
    segments = [{"type": "image", "data": {"url": f"https://images.test/{n}", "sub_type": int(n >= pictures)}}
        for n in range(pictures + stickers)]
    ingest(client, state, p, {**event(), "message": [{"type": "text", "data": {"text": "bot😀"}}, *segments]}, 1)
    client.portal.call(finish_pending, state)
    row = page(client, session)[0]
    media = state.qq.store.message_media([row["id"]])[row["id"]]
    for index, item in enumerate(media):
        if index % 2 == 0:
            state.qq.store.update_description(item.asset_id, f"描述{index}")
    reply(upstream)
    batch = freeze(state, session, 6)
    client.portal.call(state.qq.execute, batch)
    assert state.qq.store.get(QQBatch, batch.id).status == "done"
    selected = build_qq_context(state.qq.store, state.messages, session["session_id"], "input",
        ContextPolicy(), batch.input_message_id)
    sources = [source.reference_id for source in selected.trace.sources if source.kind == "attachment"]
    assert sources == [f"qq-media:{media[index].id}" for index in expected]
    assert len(sources) <= 5
    text = json.dumps(selected.messages, ensure_ascii=False)
    for index, item in enumerate(media):
        if index not in expected:
            label = "图片" if item.kind == "image" else "表情包"
            assert (f"[{label}：描述{index}]" if index % 2 == 0 else f"[{label}]") in text
    snapshots = [state.runs.get_context_snapshot(step.step_id) for step in state.runs.list_steps(batch.run_id) if step.kind == "model"]
    if media:
        state.qq.store.update_description(media[0].asset_id, "最新描述")
    history = build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(), None)
    assert not any(source.kind == "attachment" for source in history.trace.sources)
    assert all(isinstance(message["content"], str) for message in history.messages)
    if media:
        assert "最新描述" in history.model_dump_json()
    assert snapshots == [state.runs.get_context_snapshot(step.step_id) for step in state.runs.list_steps(batch.run_id) if step.kind == "model"]


def test_duplicate_occurrences_count_and_faces_never_wait_or_send(qq_client, monkeypatch):
    client, state, upstream = qq_client
    prepare_images(monkeypatch)
    p, session, _ = configure_execution(client, state, image_input_enabled=True)
    segments = [{"type": "image", "data": {"url": f"https://images.test/{n}"}} for n in range(7)]
    ingest(client, state, p, image_event(images=segments), 1)
    client.portal.call(finish_pending, state)
    ingest(client, state, p, image_event(2, images=[{"type": "face", "data": {"id": 0}},
        {"type": "face", "data": {"id": 999999}}]), 2)
    batch = freeze(state, session, 7)
    assert state.qq.store.pending_media(batch_id=batch.id) == []
    reply(upstream)
    client.portal.call(state.qq.execute, batch)
    assert len(resources(state)) == 1
    parts = upstream.calls[0]["messages"][-1]["content"]
    assert len([part for part in parts if part["type"] == "image_url"]) == 5
    assert len({part["image_url"]["url"] for part in parts if part["type"] == "image_url"}) == 1
    text = "".join(part["text"] for part in parts if part["type"] == "text")
    assert "[QQ表情：惊讶]" in text and "[QQ表情]" in text and "999999" not in text


def test_description_model_setting_validation_and_references(qq_client):
    client, state, _ = qq_client
    p = project(client)
    path = f"/api/projects/{p['id']}"
    assert p["image_description_model_profile_id"] is None
    model = configure_model(client)
    embedding = configure_model(client, kind="embedding", alias="embed")
    for value in ("missing", 123, [], embedding["id"]):
        assert client.patch(path, json={"image_description_model_profile_id": value}).status_code >= 400
    local = ok(client.post("/api/models/profiles", json={"kind": "llm", "name": "unbound", "alias": "unbound", "model_ref": "draft"}))
    assert client.patch(path, json={"image_description_model_profile_id": local["id"]}).status_code == 422
    ok(client.patch(path, json={"image_description_model_profile_id": model["id"]}))
    ok(client.patch(path, json={"name": "renamed"}))
    assert ok(client.get(path))["image_description_model_profile_id"] == model["id"]
    ok(client.patch("/api/models/settings", json={"default_model_profile_id": None}))
    assert client.delete(f"/api/models/profiles/{model['id']}").status_code == 409
    ok(client.patch(path, json={"image_description_model_profile_id": None}))
    ok(client.patch(f"/api/models/profiles/{model['id']}", json={"enabled": False}))
    assert client.patch(path, json={"image_description_model_profile_id": model["id"]}).status_code == 503


@pytest.mark.parametrize("outcome", ["success", "failure", "empty", "changed", "deleted", "cancelled"])
def test_description_tasks_are_optional_coalesced_and_do_not_gate_chat(qq_client, monkeypatch, outcome):
    client, state, upstream = qq_client
    prepare_images(monkeypatch)
    p, session, _ = configure_execution(client, state, image_input_enabled=True)
    caption = configure_model(client, alias="caption")
    ok(client.patch(f"/api/projects/{p['id']}", json={"image_description_model_profile_id": caption["id"]}))
    original_chat = state.model_manager.chat
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        requests = []
        async def chat(profile_id, request, **kwargs):
            if profile_id != caption["id"]:
                return await original_chat(profile_id, request, **kwargs)
            requests.append(request)
            started.set()
            await release.wait()
            if outcome == "failure":
                raise ModelError("UPSTREAM_ERROR", "fixture")
            return SimpleNamespace(message=SimpleNamespace(tool_calls=None,
                content="   " if outcome == "empty" else '"红色\n图片"'))
        monkeypatch.setattr(state.model_manager, "chat", chat)
        duplicate = [{"type": "image", "data": {"url": "https://images.test/static"}}] * 6
        await state.qq.ingest(p["id"], image_event(images=duplicate), now=1)
        await finish_pending(state)
        batch = freeze(state, session, 6)
        reply(upstream)
        await asyncio.wait_for(state.qq.execute(batch), 5)
        await asyncio.wait_for(started.wait(), 1)
        assert state.qq.store.get(QQBatch, batch.id).status == "done"
        assert len(requests) == 1 and len(state.qq.descriptions.tasks) == 1
        assert state.runs.get_config_snapshot(batch.run_id)["qq_image_description_model_profile_id"] == caption["id"]
        request = requests[0]
        assert request.stream is False and not request.tools and request.max_tokens == 64
        assert len(request.messages) == 1 and len(request.messages[0].content) == 2
        assert "QQ:9999" not in request.model_dump_json()
        context = build_qq_context(state.qq.store, state.messages, session["session_id"], "input", ContextPolicy(), batch.input_message_id)
        state.qq.descriptions.submit(caption["id"], context.trace, 10_000_000)
        assert len(state.qq.descriptions.tasks) == 1
        asset = resources(state)[0]
        if outcome == "changed":
            state.qq.store.update_description(asset.id, "人工更新")
        elif outcome == "deleted":
            state.qq.history.delete(session["session_id"], message_id=state.qq.store.batch_messages(batch.id)[0].id)
        elif outcome == "cancelled":
            await state.qq.descriptions.close()
        release.set()
        await asyncio.gather(*list(state.qq.descriptions.tasks.values()))
        await asyncio.sleep(0)
        assert not state.qq.descriptions.tasks
        saved = state.qq.store.get(QQMediaAsset, asset.id)
        if outcome == "deleted":
            assert saved is None
        else:
            assert saved.description == {"success": "红色 图片", "changed": "人工更新"}.get(outcome)
        state.qq.descriptions.submit(None, context.trace, 10_000_000)
        assert not state.qq.descriptions.tasks
        if outcome in {"failure", "empty", "cancelled"}:
            state.qq.descriptions.submit(caption["id"], context.trace, 10_000_000)
            assert len(state.qq.descriptions.tasks) == 1
            await asyncio.gather(*list(state.qq.descriptions.tasks.values()))
    client.portal.call(scenario)
