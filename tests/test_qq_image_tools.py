"""Favorite-image delivery and immutable, text-only generation permissions."""
import asyncio
import base64
import hashlib
import json

import pytest
from ai_workbench.core.attachments import resolve_attachment_uri, save_attachment_from_upload
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.qq_media import decode_image
from ai_workbench.core.qq_protocol import normalize
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.qq import QQImageAttachment
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQMediaAsset
from tests.test_qqbot import qq_client, child, configure_execution, event, freeze, ingest, project, FakeConnection
from tests.test_qq_followup import clock, followup, participant, execute
from tests.test_qq_icebreaker import queued
from tests.test_qq_image_generation import image_provider, draw, assets, deliveries
from tests.test_qq_media import isolated_attachments, image_bytes
from tests.test_qq_reply_policy import execute_batch
from tests.tool_fixtures import completion, ok, tool_call


def favorite(state, *, description="Celebration, cheers", starred=True, format="GIF"):
    data = image_bytes(format, animated=True)
    mime, suffix, width, height, frame = decode_image(data)
    def save(data, mime, suffix):
        value = save_attachment_from_upload("favorite" + suffix, mime, data, state.app_settings.get())
        return QQImageAttachment(id=value['uri'].removeprefix('local://attachments/'), width=width, height=height,
            **{key: value[key] for key in ('name', 'mime_type', 'size', 'uri')}).model_dump_json()
    return state.qq.store.save(QQMediaAsset(sha256=hashlib.sha256(data).hexdigest(),
        attachment_json=save(data, mime, suffix), model_attachment_json=save(frame, 'image/png', '.png'),
        description=description, is_favorite=starred, description_manual=True)), data


def send_image(asset_id, call_id="favorite"):
    return tool_call('qq_send_image', {'asset_id': asset_id}, call_id)


def tool_names(request):
    return {tool['function']['name'] for tool in request['tools']}


@pytest.mark.parametrize('private,format', [(False, 'GIF'), (True, 'WEBP')])
def test_original_animation_delivery_and_stable_text_history(qq_client, private, format):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    asset, data = favorite(state, format=format)
    if private:
        session = child(client, p, '9999', 'friend')
    upstream.turns = [completion(send_image(asset.id))]
    _, run = execute_batch(client, state, p, session, private=private)
    assert run.status == 'DONE', run.error_message
    assert run.metadata['qq_reply']['sent_count'] == 1
    assert connection.calls == [('send_private_msg' if private else 'send_group_msg', {
        'user_id' if private else 'group_id': 9999 if private else 7788,
        'message': [{'type': 'image', 'data': {'file': 'base64://' + base64.b64encode(data).decode()}}]})]
    delivery, = deliveries(client, session)
    assert (delivery['kind'], delivery['asset_id'], delivery['prompt']) == ('resource_image', asset.id, None)
    assert delivery['attachment']['mime_type'] == ('image/gif' if format == 'GIF' else 'image/webp')
    assert len(assets(state)) == 1 and assets(state)[0].description == asset.description
    snapshot = state.runs.get_config_snapshot(run.run_id)
    assert snapshot['qq_image_candidates'] == [{'asset_id': asset.id, 'description': asset.description}]
    assert not snapshot['qq_image_generation_allowed']
    system = upstream.calls[0]['messages'][0]['content']
    assert 'Favorite image candidates:' in system and asset.description in system
    assert 'local://' not in system and 'base64://' not in system
    state.qq.resources.update(asset.id, {'description': 'New shared description'})
    context = build_qq_context(state.qq.store, state.messages, session['session_id'], 'next', ContextPolicy(), None)
    call = context.messages[1]['tool_calls'][0]
    assert call.function.name == 'qq_send_image' and json.loads(call.function.arguments) == {'asset_id': asset.id}
    assert f'[图片:{asset.description}]' in context.model_dump_json()
    assert 'New shared description' not in context.model_dump_json() and 'attachment_image' not in context.model_dump_json()
    state.qq.resources.delete(asset.id)
    context = build_qq_context(state.qq.store, state.messages, session['session_id'], 'next', ContextPolicy(), None)
    assert 'qq_send_image' not in context.model_dump_json() and asset.description not in context.model_dump_json()
    assert any(m.get('content') == '[图片]' for m in context.messages)
    assert state.runs.get_config_snapshot(run.run_id) == snapshot


def test_candidates_filter_snapshot_and_next_batch(qq_client):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, reply_message_limit=2)
    first, _ = favorite(state)
    hidden, _ = favorite(state, format='WEBP', starred=False)
    empty, _ = favorite(state, format='PNG', description=' \t\n')
    def change_after_snapshot(request):
        state.qq.resources.update(first.id, {'description': 'Changed'})
        hidden.is_favorite = True
        state.qq.store.save(hidden)
        return completion(send_image(first.id))
    upstream.turns = [change_after_snapshot, completion(tool_call('qq_send_message', {'text': 'done'}, 'text'))]
    _, run = execute_batch(client, state, p, session)
    assert run.status == 'DONE'
    for request in upstream.calls:
        candidates = json.loads(request['messages'][0]['content'].split('Favorite image candidates: ')[1].split('\n')[0])
        assert candidates == [{'asset_id': first.id, 'description': first.description}]
    assert deliveries(client, session)[-1]['text'] == '[图片:Changed]'
    upstream.turns = [completion(send_image(hidden.id)), completion(content='done')]
    _, next_run = execute_batch(client, state, p, session, 2)
    assert next_run.status == 'DONE'
    assert [c['asset_id'] for c in state.runs.get_config_snapshot(next_run.run_id)['qq_image_candidates']] == [first.id, hidden.id]
    public = ok(client.get(f"/api/sessions/{session['session_id']}"))['effective']
    assert 'qq_image_candidates' not in public and 'qq_image_generation_allowed' not in public


@pytest.mark.parametrize('failure', ['unfavorite', 'description', 'delete', 'file', 'path', 'outside'])
def test_unavailable_favorite_recovers_without_intent_or_slot(qq_client, monkeypatch, failure):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    asset, _ = favorite(state)
    def invalidate(request):
        if failure == 'delete':
            state.qq.resources.delete(asset.id)
        elif failure == 'file':
            resolve_attachment_uri(asset.attachment.uri).unlink()
        elif failure == 'path':
            def invalid_path(uri):
                raise ValueError('Attachment path is outside the attachment directory.')
            monkeypatch.setattr('ai_workbench.core.qq_service.resolve_attachment_uri', invalid_path)
        elif failure != 'outside':
            # Simulate an edit after this batch's candidate snapshot.
            saved = state.qq.store.get(QQMediaAsset, asset.id)
            if failure == 'unfavorite':
                saved.is_favorite = False
            else:
                saved.description = None
            state.qq.store.save(saved)
        return completion(send_image(asset.id + 1 if failure == 'outside' else asset.id))
    upstream.turns = [invalidate, completion(tool_call('qq_send_message', {'text': 'fallback'}, 'text'))]
    _, run = execute_batch(client, state, p, session)
    assert run.status == 'DONE' and run.metadata['qq_reply']['sent_count'] == 1
    assert not state.qq.store.get(QQBinding, session['session_id']).paused
    assert json.loads(upstream.calls[1]['messages'][-1]['content'])['error_code'] == 'QQ_IMAGE_RESOURCE_UNAVAILABLE'
    assert [d['kind'] for d in deliveries(client, session)] == ['text'] and len(connection.calls) == 1


@pytest.mark.parametrize('value', [True, 0, -1, 1.0, '1', None])
def test_asset_id_is_strict_and_tool_is_qq_only(qq_client, value):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=1)
    favorite(state)
    assert 'qq_send_image' not in {t['name'] for t in ok(client.get('/api/tools'))}
    assert client.post('/api/tools/qq_send_image/call', json={'session_id': session['session_id'], 'arguments': {'asset_id': 1}}).status_code >= 400
    ordinary = ok(client.post('/api/sessions', json={}))
    assert client.patch(f"/api/sessions/{ordinary['session_id']}", json={'tools_allowed': ['qq_send_image']}).status_code == 422
    upstream.turns = [completion(send_image(value)), completion(tool_call('qq_send_message', {'text': 'fallback'}, 'text'))]
    _, run = execute_batch(client, state, p, session)
    assert run.status == 'DONE' and len(connection.calls) == 1
    assert json.loads(upstream.calls[1]['messages'][-1]['content'])['error_code'] == 'TOOL_INVALID_ARGUMENTS'


def test_no_candidates_hides_tool_and_prompt(qq_client):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, reply_message_limit=1, system_prompt='Custom prompt')
    favorite(state, description=None)
    upstream.turns = [completion(tool_call('qq_send_message', {'text': 'reply'}))]
    _, run = execute_batch(client, state, p, session)
    assert run.status == 'DONE'
    assert tool_names(upstream.calls[0]) == {'qq_send_message'}
    assert 'Favorite image candidates:' not in upstream.calls[0]['messages'][0]['content']
    assert state.projects.get(p['id']).system_prompt == 'Custom prompt'


def test_text_resource_and_generation_share_limit(qq_client, image_provider):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=3,
        image_generation_model_profile_id=image_provider.profile['id'])
    asset, _ = favorite(state)
    upstream.turns = [completion(tool_call('qq_send_message', {'text': 'reply'}, 'text'), send_image(asset.id),
        draw(), send_image(asset.id, 'excess'))]
    _, run = execute_batch(client, state, p, session, text='bot 生成图片')
    assert run.status == 'DONE' and run.metadata['qq_reply']['sent_count'] == 3
    assert len(connection.calls) == 3 and len(image_provider.calls) == 1
    assert {d['kind'] for d in deliveries(client, session)} == {'text', 'resource_image', 'generated_image'}


def test_shared_resource_retention_across_projects_and_session_deletion(qq_client):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, reply_message_limit=2)
    asset, _ = favorite(state)
    other = project(client, bot_account='54321', model_profile_id=p['model_profile_id'],
        keywords=['bot'], connection_enabled=True, reply_message_limit=1)
    second = child(client, other)
    state.qq.connections[other['id']] = FakeConnection()
    upstream.turns = [completion(send_image(asset.id), send_image(asset.id, 'second'))]
    _, run = execute_batch(client, state, p, session)
    assert run.status == 'DONE' and run.metadata['qq_reply']['sent_count'] == 2
    upstream.turns = [completion(send_image(asset.id))]
    ingest(client, state, other, {**event(1), 'self_id': 54321}, 0)
    _, second_run = execute(qq_client, freeze(state, second, 5))
    assert second_run.status == 'DONE' and len(assets(state)) == 1
    path = resolve_attachment_uri(asset.attachment.uri)
    ok(client.delete(f"/api/projects/{p['id']}"))
    assert path.exists() and deliveries(client, second)[0]['asset_id'] == asset.id
    state.qq.resources.update(asset.id, {'is_favorite': False})
    ok(client.delete(f"/api/sessions/{second['session_id']}"))
    assert state.qq.store.get(QQMediaAsset, asset.id) is None and not path.exists()


def test_stop_during_resource_send_protects_intent_and_restart_never_resends(qq_client):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    asset, _ = favorite(state)
    upstream.turns = [completion(send_image(asset.id))]
    async def scenario():
        sending = asyncio.Event()
        async def hold(action, params):
            connection.calls.append((action, params))
            sending.set()
            await asyncio.Event().wait()
        connection.call = hold
        await state.qq.ingest(p['id'], event(1), now=0)
        batch = freeze(state, session, 5)
        task = asyncio.create_task(state.qq.execute(batch))
        state.qq.workers[p['id']] = task
        await asyncio.wait_for(sending.wait(), 5)
        assert state.qq.resources.page(1, 30, 'created_at', 'desc', 'all')['items'][0]['has_references']
        with pytest.raises(ChatError) as error:
            state.qq.resources.delete(asset.id)
        assert error.value.code == 'SESSION_BUSY'
        state.qq.control(session['session_id'], 'stop')
        await asyncio.wait_for(task, 5)
        state.qq.store.recover()
        state.qq.control(session['session_id'], 'resume')
        await state.qq.execute(batch)
    client.portal.call(scenario)
    delivery, = deliveries(client, session)
    assert delivery['status'] == 'unknown' and delivery['asset_id'] == asset.id
    assert len(connection.calls) == 1 and resolve_attachment_uri(asset.attachment.uri).exists()


@pytest.mark.parametrize('icebreaker', [False, True])
def test_resource_renews_eligibility_and_obeys_optional_limits(qq_client, clock, icebreaker):
    client, state, upstream = qq_client
    p, session, connection, batch = (queued if icebreaker else followup)(qq_client, clock)
    asset, _ = favorite(state)
    clock[0] = 17 if icebreaker else 100
    upstream.turns = [completion(send_image(asset.id), tool_call('qq_skip_reply', '{}', 'skip')), completion(content='done')]
    _, run = execute(qq_client, batch)
    assert run.status == 'DONE' and run.metadata['qq_reply']['sent_count'] == 1 and not run.metadata['qq_reply']['skipped']
    assert participant(state, session).expires_at == (77 if icebreaker else 145)
    assert run.metadata['qq_reply']['limit_reached'] == icebreaker
    if not icebreaker:
        assert 'qq_skip_reply' not in tool_names(upstream.calls[-1])


@pytest.mark.parametrize('failure,status', [(ToolExecutionError('QQ_ACTION_FAILED', 'rejected'), 'failed'), (TimeoutError(), 'unknown')])
def test_delivery_failure_protects_resource_and_never_replays(qq_client, failure, status):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    asset, _ = favorite(state)
    connection.failure = failure
    upstream.turns = [completion(send_image(asset.id))]
    batch, run = execute_batch(client, state, p, session)
    assert run.status == 'FAILED' and run.metadata['qq_reply']['sent_count'] == 0
    delivery, = deliveries(client, session)
    assert delivery['status'] == status and delivery['asset_id'] == asset.id
    state.qq.resources.update(asset.id, {'is_favorite': False})
    state.qq.media.cleanup({asset.attachment.id, asset.model_attachment.id})
    assert resolve_attachment_uri(asset.attachment.uri).exists()
    state.qq.store.recover()
    client.portal.call(state.qq.execute, batch)
    assert len(connection.calls) == 1
    ok(client.delete(f"/api/qq/sessions/{session['session_id']}/deliveries/{delivery['id']}"))
    assert state.qq.store.get(QQMediaAsset, asset.id) is None
    assert not resolve_attachment_uri(asset.attachment.uri).exists()


@pytest.mark.parametrize('source,expected', [('生成图片', True), ('画一张', True), ('再来一张', False), ('hello', False)])
def test_generation_gate_uses_batch_text(qq_client, image_provider, source, expected):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, reply_message_limit=1, system_prompt='Custom',
        image_generation_model_profile_id=image_provider.profile['id'])
    upstream.turns = [completion(draw() if expected else tool_call('qq_send_message', {'text': 'reply'}))]
    _, run = execute_batch(client, state, p, session, text='bot ' + source)
    assert run.status == 'DONE'
    assert ('qq_generate_image' in tool_names(upstream.calls[0])) == expected
    assert ('qq_generate_image' in upstream.calls[0]['messages'][0]['content']) == expected
    assert state.runs.get_config_snapshot(run.run_id)['qq_image_generation_allowed'] == expected
    assert len(image_provider.calls) == int(expected)
    assert 'image_generation_keyword' not in ok(client.get(f"/api/qq/sessions/{session['session_id']}/messages"))['items'][0]


@pytest.mark.parametrize('kind', ['at', 'reply', 'share', 'json', 'lightapp', 'image'])
def test_synthetic_text_and_names_never_enable_generation(kind):
    data = event(text='bot')
    data['sender'] = {'nickname': '生成', 'card': '画'}
    data['message'].append({'type': kind, 'data': {'qq': '画', 'name': '生成', 'id': '生成', 'title': '生成',
        'url': 'https://test/画', 'file': '生成.png', 'data': json.dumps({'prompt': '画', 'app': 'com.tencent.miniapp', 'meta': {}})}})
    assert normalize(data)[0]['image_generation_keyword'] is False
    data['message'] = '[CQ:share,title=生成,url=https://test/画]'
    assert normalize(data)[0]['image_generation_keyword'] is False


@pytest.mark.parametrize('exclude', ['limit', 'delete', 'restart'])
def test_generation_gate_uses_only_submitted_messages_after_queueing(qq_client, image_provider, exclude):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, reply_message_limit=1,
        image_generation_model_profile_id=image_provider.profile['id'])
    ingest(client, state, p, event(1, 'bot 画一张'), 0)
    ingest(client, state, p, event(2, 'tail'), 1)
    batch = freeze(state, session, 6, limit=1 if exclude == 'limit' else 20)
    if exclude == 'delete':
        first = state.qq.store.batch_messages(batch.id)[0]
        ok(client.delete(f"/api/qq/sessions/{session['session_id']}/messages/{first.id}"))
    if exclude == 'restart':
        state.qq.store.recover()
    upstream.turns = [completion(tool_call('qq_send_message', {'text': 'reply'}))]
    _, run = execute(qq_client, batch)
    assert run.status == 'DONE'
    assert ('qq_generate_image' in tool_names(upstream.calls[0])) == (exclude == 'restart')


def test_history_model_output_and_tool_results_cannot_unlock_generation(qq_client, image_provider):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state, reply_message_limit=4,
        image_generation_model_profile_id=image_provider.profile['id'])
    asset, _ = favorite(state, description='生成 画')
    upstream.turns = [completion(draw()), completion(content='done')]
    execute_batch(client, state, p, session, text='bot 画一张')
    upstream.turns = [completion(send_image(asset.id), content='生成 画'), completion(draw('forged', 'forged')),
        completion(tool_call('qq_send_message', {'text': 'fallback'}, 'text')), completion(content='done')]
    _, run = execute_batch(client, state, p, session, 2, text='bot 再来一张')
    assert run.status == 'DONE' and len(image_provider.calls) == 1
    assert all('qq_generate_image' not in tool_names(request) for request in upstream.calls[-4:])
    assert json.loads(upstream.calls[-2]['messages'][-1]['content'])['error_code'] == 'TOOL_NOT_ALLOWED'


def test_handler_rechecks_disabled_generation_permission(qq_client, image_provider, monkeypatch):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, image_generation_model_profile_id=image_provider.profile['id'])
    monkeypatch.setattr(state.chat_runner.harness_loop, 'allowed_tools', lambda _: ['qq_generate_image', 'qq_send_message'])
    upstream.turns = [completion(draw())]
    _, run = execute_batch(client, state, p, session)
    assert run.status == 'FAILED' and run.error_code == 'TOOL_NOT_ALLOWED'
    assert image_provider.calls == []


def test_keyword_migration_defaults_false_without_reading_display_text(tmp_path):
    from ai_workbench.db.database import get_engine
    from ai_workbench.db import migrations
    engine = get_engine(f"sqlite:///{tmp_path / 'keywords.db'}")
    try:
        migrations.upgrade(engine, migrations.QQ_TRIGGER_GRANTS_REVISION)
        with engine.begin() as db:
            db.exec_driver_sql("INSERT INTO qq_messages (session_id,external_id,sender_id,sender_name,timestamp,text,references_json,disposition,deleted) VALUES ('s','1','u','画','now','生成','[]','pending',0)")
        files = [tmp_path / name / 'retained.bin' for name in ('models', 'attachments', 'runtimes')]
        for path in files:
            path.parent.mkdir()
            path.write_bytes(b'keep')
        migrations.upgrade(engine)
        with engine.begin() as db:
            assert db.exec_driver_sql('SELECT image_generation_keyword FROM qq_messages').scalar_one() == 0
            db.exec_driver_sql('UPDATE qq_messages SET image_generation_keyword=1')
        migrations.upgrade(engine)
        with engine.connect() as db:
            assert db.exec_driver_sql('SELECT image_generation_keyword FROM qq_messages').scalar_one() == 1
        assert all(path.read_bytes() == b'keep' for path in files)
    finally:
        engine.dispose()
