"""QQ generation uses model admission, confirmed delivery and shared image ownership."""
import asyncio
import base64
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlmodel import Session, select

from ai_workbench.core.attachments import attachments_root, resolve_attachment_uri
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQDelivery, QQMediaAsset
from tests.model_fixtures import configure_model
from tests.test_qqbot import qq_client, child, configure_execution, event, freeze, ingest, project
from tests.test_qq_media import isolated_attachments, image_bytes, image_event, finish_pending
from tests.test_qq_reply_policy import execute_batch
from tests.test_qq_followup import clock, followup, participant, execute
from tests.tool_fixtures import completion, ok, tool_call


@pytest.fixture
def image_provider(qq_client, monkeypatch):
    client, state, upstream = qq_client
    image = image_bytes()
    fixture = SimpleNamespace(calls=[], image=image, response={"data": [{"b64_json": base64.b64encode(image).decode(),
        "revised_prompt": "Provider rewrite"}]}, failure=None, before_return=None)
    original = upstream.handle

    async def handle(request):
        if not request.url.path.endswith("/images/generations"):
            return await original(request)
        fixture.calls.append(json.loads(request.content))
        if fixture.before_return:
            await fixture.before_return()
        if fixture.failure:
            raise fixture.failure
        return httpx.Response(200, json=fixture.response)

    monkeypatch.setattr(upstream, "handle", handle)
    fixture.profile = configure_model(client, kind="image_generation", alias="draw", parameters={"n": 3, "quality": "high"})
    return fixture


def assets(state):
    with Session(state.qq.store.engine) as db:
        return db.exec(select(QQMediaAsset)).all()


def attachment_files():
    return [path for path in attachments_root().rglob('*') if path.is_file()]


def deliveries(client, session):
    return ok(client.get(f"/api/qq/sessions/{session['session_id']}/deliveries"))["items"]


def draw(prompt="A red bird", call_id="draw"):
    return tool_call("qq_generate_image", {"prompt": prompt}, call_id)


def test_settings_validation_visibility_and_model_references(qq_client, image_provider):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state)
    assert p["image_generation_model_profile_id"] is None
    assert p["image_generation_options"] == {"size": None, "quality": None, "style": None}
    assert "qq_generate_image" not in state.chat_service.tools_for_run(state.chat_service.resolve(state.sessions.get_session(session['session_id'])))
    url = f"/api/projects/{p['id']}"
    assert client.patch(url, json={"image_generation_model_profile_id": p["model_profile_id"]}).status_code == 400
    for fields in ({"image_generation_options": None}, {"image_generation_options": {"n": 2}},
                   {"image_generation_options": {"size": "0x4"}}, {"image_generation_options": {"quality": "best"}}):
        assert client.patch(url, json=fields).status_code == 422
    model_id = image_provider.profile["id"]
    ok(client.patch(url, json={"image_generation_model_profile_id": model_id,
        "image_generation_options": {"size": "1024x1024", "quality": "low", "style": "vivid"}}))
    assert client.delete(f"/api/models/profiles/{model_id}").status_code == 409
    assert "qq_generate_image" not in {tool['name'] for tool in ok(client.get('/api/tools'))}
    response = client.post('/api/tools/qq_generate_image/call', json={"session_id": session['session_id'], "arguments": {"prompt": "test"}})
    assert response.status_code >= 400
    ok(client.patch(url, json={"name": "Renamed"}))
    assert ok(client.get(url))["image_generation_options"]["style"] == "vivid"
    changed = ok(client.patch(url, json={"image_generation_options": {"quality": None}}))
    assert changed['image_generation_options'] == {'size': '1024x1024', 'quality': None, 'style': 'vivid'}
    ok(client.patch(url, json={"image_generation_model_profile_id": None}))
    assert ok(client.get(url))["image_generation_options"]["size"] == "1024x1024"
    ok(client.patch(f"/api/models/profiles/{model_id}", json={"enabled": False}))
    assert client.patch(url, json={"image_generation_model_profile_id": model_id}).status_code == 503


@pytest.mark.parametrize("format", ["url", "b64_json"])
@pytest.mark.parametrize("private,streaming", [(False, False), (True, True)])
def test_generate_send_store_and_text_only_history(qq_client, image_provider, monkeypatch, format, private, streaming):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, streaming=streaming, reply_message_limit=1,
        image_generation_model_profile_id=image_provider.profile["id"],
        image_generation_options={"size": "1024x1024", "style": "vivid"})
    if private:
        session = child(client, p, "9999", "friend")
    if format == "url":
        image_provider.response = {"data": [{"url": "https://image.test/generated.png"}]}
        async def download(url, policy, *, max_bytes):
            assert url == "https://image.test/generated.png" and max_bytes == 10 * 1024 * 1024
            return image_provider.image, url, "image/png"
        monkeypatch.setattr("ai_workbench.core.qq_generation.fetch_bytes", download)
    original = connection.call
    async def send(action, params):
        assert assets(state) == []
        assert params["message"] == [{"type": "image", "data": {"file": "base64://" + base64.b64encode(image_provider.image).decode()}}]
        return await original(action, params)
    connection.call = send
    prompt = "A red bird\n枝头的一只红鸟"
    upstream.turns = [completion(draw(prompt))]
    _, run = execute_batch(client, state, p, session, private=private)
    assert run.status == "DONE", run.error_message
    assert run.metadata["qq_reply"] == {"sent_count": 1, "message_limit": 1, "limit_reached": True, "skipped": False}
    assert len(upstream.calls) == len(image_provider.calls) == len(connection.calls) == 1
    assert connection.calls[0][0] == ("send_private_msg" if private else "send_group_msg")
    assert image_provider.calls[0] == {"model": "embed", "prompt": prompt, "n": 1, "size": "1024x1024", "quality": "high", "style": "vivid"}
    delivery, = deliveries(client, session)
    asset, = assets(state)
    assert delivery["kind"] == "generated_image" and delivery["asset_id"] == asset.id
    assert delivery["prompt"] == delivery["description"] == asset.description == prompt
    assert resolve_attachment_uri(delivery["attachment"]["uri"]).read_bytes() == image_provider.image
    context = build_qq_context(state.qq.store, state.messages, session['session_id'], "next", ContextPolicy(include_attachments="explicit"), None)
    history = context.model_dump_json()
    assert "[生成的图片:" in history and "枝头的一只红鸟" in history
    assert "Provider rewrite" not in history and "base64" not in history and "image_url" not in history and "attachment_image" not in history
    call = context.messages[1]["tool_calls"][0]
    assert call.function.name == "qq_generate_image" and json.loads(call.function.arguments) == {"prompt": prompt}
    snapshot = state.runs.get_config_snapshot(run.run_id)
    assert snapshot["qq_image_generation_options"]["style"] == "vivid"


def test_mixed_limit_rejects_generation_before_it_starts(qq_client, image_provider):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=2,
        image_generation_model_profile_id=image_provider.profile["id"])
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "Hello"}, "text"), draw(),
        draw("Must not generate", "excess"), tool_call("qq_send_message", {"text": "excess"}, "excess_text"))]
    _, run = execute_batch(client, state, p, session)
    assert run.status == "DONE" and run.metadata["qq_reply"]["sent_count"] == 2
    assert len(image_provider.calls) == 1 and len(connection.calls) == 2
    assert [d["kind"] for d in deliveries(client, session)] == ["generated_image", "text"]
    results = [part for message in state.messages.messages_for_run(run.run_id) for part in message.parts if part["type"] == "tool_result"]
    assert sum("QQ_REPLY_LIMIT_REACHED" in json.dumps(part) for part in results) == 2


def test_image_followup_renews_participant_and_removes_skip(qq_client, image_provider, clock):
    client, state, upstream = qq_client
    p, session, connection, batch = followup(qq_client, clock,
        image_generation_model_profile_id=image_provider.profile['id'])
    clock[0] = 100
    upstream.turns = [completion(draw(), tool_call('qq_skip_reply', '{}', 'skip')), completion(content='done')]
    _, run = execute(qq_client, batch)
    assert run.status == 'DONE' and run.metadata['qq_reply']['sent_count'] == 1
    assert not run.metadata['qq_reply']['skipped'] and participant(state, session).expires_at == 145
    assert 'qq_skip_reply' not in {tool['function']['name'] for tool in upstream.calls[-1]['tools']}


def test_failed_image_still_requires_mandatory_reply(qq_client, image_provider):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, image_generation_model_profile_id=image_provider.profile['id'])
    image_provider.response = {'error': {'message': 'Generation failed'}}
    upstream.turns = [completion(draw()), completion(content='No tool reply')]
    _, run = execute_batch(client, state, p, session)
    assert run.error_code == 'QQ_REPLY_REQUIRED' and run.metadata['qq_reply']['sent_count'] == 0
    assert connection.calls == [] and state.qq.store.get(QQBinding, session['session_id']).paused


@pytest.mark.parametrize("failure", ["provider", "timeout", "invalid", "oversize", "private_url"])
def test_generation_failure_returns_to_model_without_delivery(qq_client, image_provider, failure):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1,
        image_generation_model_profile_id=image_provider.profile["id"])
    if failure == "provider":
        image_provider.response = {"error": {"message": "private provider error"}}
    elif failure == "timeout":
        image_provider.failure = httpx.ReadTimeout("private timeout")
    elif failure == "invalid":
        image_provider.response = {"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]}
    elif failure == "oversize":
        state.app_settings.patch({"max_image_size_mb": 1})
        image_provider.response = {"data": [{"b64_json": base64.b64encode(b"x" * (1024 * 1024 + 1)).decode()}]}
    else:
        image_provider.response = {"data": [{"url": "http://127.0.0.1/private.png"}]}
    upstream.turns = [completion(draw()), completion(tool_call("qq_send_message", {"text": "Could not draw"}, "text"))]
    _, run = execute_batch(client, state, p, session)
    assert run.status == "DONE" and run.metadata["qq_reply"]["sent_count"] == 1
    result = json.loads(upstream.calls[1]["messages"][-1]["content"])
    assert result["error_code"] == "QQ_IMAGE_GENERATION_FAILED"
    assert "private provider" not in str(result) and "private timeout" not in str(result)
    assert len(connection.calls) == len(deliveries(client, session)) == 1
    assert assets(state) == [] and attachment_files() == []
    assert not state.qq.store.get(QQBinding, session['session_id']).paused


@pytest.mark.parametrize("failure,status", [(ToolExecutionError("QQ_ACTION_FAILED", "Rejected"), "failed"), (TimeoutError(), "unknown")])
def test_delivery_failure_pauses_and_discards_staged_image(qq_client, image_provider, failure, status):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state,
        image_generation_model_profile_id=image_provider.profile["id"])
    connection.failure = failure
    upstream.turns = [completion(draw()), completion(tool_call("qq_send_message", {"text": "Must not send"}))]
    _, run = execute_batch(client, state, p, session)
    assert run.status == "FAILED" and run.metadata['qq_reply']['sent_count'] == 0
    assert state.qq.store.get(QQBinding, session['session_id']).paused
    delivery, = deliveries(client, session)
    assert delivery['status'] == status and delivery['asset_id'] is None
    assert len(upstream.calls) == len(image_provider.calls) == len(connection.calls) == 1
    assert assets(state) == [] and attachment_files() == []


def test_wait_excludes_generation_from_harness_budget_and_freezes_settings(qq_client, image_provider, monkeypatch):
    from ai_workbench.core.harness import agent_loop
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state,
        image_generation_model_profile_id=image_provider.profile["id"], image_generation_options={"size": "512x512"})
    clock = [0.0]
    monkeypatch.setattr(agent_loop, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    budget_type = agent_loop._Budget
    monkeypatch.setattr(agent_loop, '_Budget', lambda spent: budget_type(spent, started=clock[0]))
    async def wait():
        clock[0] += 600
        state.project_service.update(p['id'], {'image_generation_model_profile_id': None, 'image_generation_options': {'size': 'auto'}})
        await asyncio.sleep(.04)
    image_provider.before_return = wait
    monkeypatch.setattr(agent_loop, 'TOOL_TIMEOUT_SECONDS', .01)
    upstream.turns = [completion(draw()), completion(draw('Second image', 'second')), completion(content='done')]
    _, run = execute_batch(client, state, p, session)
    assert run.status == 'DONE' and run.metadata['qq_reply']['sent_count'] == 2
    assert [call['size'] for call in image_provider.calls] == ['512x512', '512x512']
    assert len(connection.calls) == 2


def test_stop_cancels_generation_without_sending_and_keeps_new_batches(qq_client, image_provider):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, image_generation_model_profile_id=image_provider.profile['id'])
    upstream.turns = [completion(draw())]
    async def scenario():
        generating, cancelled = asyncio.Event(), asyncio.Event()
        async def wait():
            generating.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        image_provider.before_return = wait
        await state.qq.ingest(p['id'], event(1), now=0)
        batch = freeze(state, session, 5)
        task = asyncio.create_task(state.qq.execute(batch))
        state.qq.workers[p['id']] = task
        await asyncio.wait_for(generating.wait(), 5)
        await state.qq.ingest(p['id'], event(2), now=7)
        queued = freeze(state, session, 12)
        assert state.qq.store.next_batch(p['id']).id == queued.id
        state.qq.control(session['session_id'], 'stop')
        await asyncio.wait_for(task, 5)
        assert cancelled.is_set()
        assert state.qq.store.get(QQBatch, batch.id).status == 'cancelled'
        assert state.qq.store.get(QQBatch, queued.id).status == 'queued'
    client.portal.call(scenario)
    assert connection.calls == [] and deliveries(client, session) == [] and assets(state) == []


def test_deduplication_keeps_each_prompt_and_releases_last_reference(qq_client, image_provider, monkeypatch):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1,
        image_generation_model_profile_id=image_provider.profile['id'])
    upstream.turns = [completion(draw('First prompt'))]
    _, first = execute_batch(client, state, p, session)
    first_delivery, = deliveries(client, session)
    path = resolve_attachment_uri(first_delivery['attachment']['uri'])
    upstream.turns = [completion(draw('Second prompt'))]
    _, second = execute_batch(client, state, p, session, 2)
    second_delivery = deliveries(client, session)[0]
    assert len(assets(state)) == 1 and len(attachment_files()) == 1
    assert first_delivery['asset_id'] == second_delivery['asset_id']
    assert assets(state)[0].description == 'Second prompt'
    history = build_qq_context(state.qq.store, state.messages, session['session_id'], 'next', ContextPolicy(), None).model_dump_json()
    assert '[生成的图片:First prompt]' in history and '[生成的图片:Second prompt]' in history
    other = child(client, p, '8877')
    incoming = image_event(3, images=[{'type': 'image', 'data': {'url': 'https://image.test/generated'}}])
    incoming['group_id'] = 8877
    async def download(*args, **kwargs):
        return image_provider.image, '', 'image/png'
    monkeypatch.setattr('ai_workbench.core.qq_media.fetch_bytes', download)
    ingest(client, state, p, incoming, 30)
    client.portal.call(finish_pending, state)
    assert len(assets(state)) == 1
    ok(client.delete(f"/api/qq/sessions/{session['session_id']}/deliveries/{first_delivery['id']}"))
    ok(client.delete(f"/api/runs/{second.run_id}"))
    assert len(assets(state)) == 1 and path.exists()
    ok(client.delete(f"/api/sessions/{other['session_id']}"))
    assert assets(state) == [] and not path.exists()


def test_migration_adds_image_delivery_without_touching_files(tmp_path):
    from ai_workbench.db.database import get_engine
    from ai_workbench.db import migrations
    engine = get_engine(f"sqlite:///{tmp_path / 'images.db'}")
    migrations.upgrade(engine, migrations.QQ_MEDIA_ASSETS_REVISION)
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO qq_deliveries (session_id,run_id,tool_call_id,text,status,created_at,echoed,deleted) VALUES ('s','r','c','text','sent',1,0,0)")
    files = [tmp_path / 'data' / name / 'keep.bin' for name in ('models', 'attachments', 'runtimes')]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b'keep')
    try:
        migrations.upgrade(engine, migrations.QQ_IMAGE_GENERATION_REVISION)
        with engine.connect() as db:
            assert db.exec_driver_sql('SELECT kind,prompt,asset_id,text FROM qq_deliveries').one() == ('text', None, None, 'text')
        assert migrations.current_revision(engine) == migrations.QQ_IMAGE_GENERATION_REVISION
        assert all(path.read_bytes() == b'keep' for path in files)
    finally:
        engine.dispose()
