import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.models.context_budget import ChatContextBudget, configured_limits
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.adapters import LlamaServerAdapter, TransformersServerAdapter
from ai_workbench.core.models.schema import ChatRequest, ModelProfile
from ai_workbench.core.models.token_counting import estimate_input_tokens, reference_encoding
from ai_workbench.core.schema.context_budget import ContextLimits
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.context_snapshot import ContextSource, ContextTrace
from ai_workbench.core.stores import MessageStore
from tests.model_fixtures import configure_model
from tests.test_chat_presentation import presentation_client, configure, send
from tests.test_context_detail import details
from tests.tool_fixtures import completion, ok, tool_call


def local():
    return ModelProfile(name='local', alias='local', kind='llm', model_ref='llms/local', source={'type': 'local'})


def test_native_budget_keeps_whole_recent_turns_and_remaps_sources():
    async def scenario():
        store = MessageStore()
        for index in range(16):
            user = store.add_message('s', 'user', f'user-{index}', message_id=f'{index:03}-user')
            store.add_message('s', 'assistant', f'answer-{index}', run_id=f'run-{index}', parent_message_id=user.message_id, message_id=f'{index:03}-zanswer')
        built = ContextBuilder(store).build('s', 'current')
        original = deepcopy(built)
        payloads = []
        async def count(payload):
            payloads.append(payload)
            return len(payload['messages']) * 60
        adapter = SimpleNamespace(context_window=AsyncMock(return_value=512), count_input_tokens=count)
        budget = ChatContextBudget(ContextLimits(window_tokens=1024, output_tokens=60), built.trace)
        request = await budget.prepare(local(), ChatRequest(model='local', messages=built.messages, reasoning=False), adapter)
        assert [m.content for m in request.messages] == ['user-13', 'answer-13', 'user-14', 'answer-14', 'user-15', 'answer-15', 'current']
        assert budget.stats.input_tokens == budget.stats.input_budget_tokens == 420
        assert budget.stats.removed_turns == 13 and budget.stats.window_tokens == 512
        assert [s.message_index for s in budget.trace.sources] == list(range(7))
        assert len(budget.trace.exclusions) == 26
        assert len(payloads) <= 8 and payloads[-1]['chat_template_kwargs'] == {'enable_thinking': False}
        assert built == original and len(store.list_messages('s')) == 32
    asyncio.run(scenario())


@pytest.mark.parametrize('section', ['current_input', 'knowledge', 'tools', 'tool_result'])
def test_fixed_content_cannot_be_removed(section):
    async def scenario():
        trace = ContextTrace(sources=[ContextSource(id='fixed', kind=section, message_index=0)])
        budget = ChatContextBudget(ContextLimits(window_tokens=512, output_tokens=100), trace)
        adapter = SimpleNamespace(context_window=AsyncMock(return_value=512), count_input_tokens=AsyncMock(return_value=381))
        with pytest.raises(ModelError) as exc:
            await budget.prepare(local(), ChatRequest(model='local', messages=[{'role': 'user', 'content': 'fixed'}]), adapter)
        assert exc.value.code == 'CONTEXT_WINDOW_EXCEEDED'
        assert budget.stats is None and not budget.trace.exclusions
    asyncio.run(scenario())


def test_history_limits_preserve_original_turn_identity():
    store = MessageStore()
    user = store.add_message('s', 'user', 'question')
    store.add_message('s', 'assistant', 'answer', run_id='r', parent_message_id=user.message_id)
    store.add_message('s', 'assistant', 'continued', run_id='r')
    built = ContextBuilder(store).build('s', 'next', ContextPolicy(max_messages=2))
    assert {s.turn_id for s in built.trace.sources if s.kind == 'history'} == {user.message_id}
    assert ChatContextBudget(ContextLimits(), built.trace)._history_groups() == [[0, 1]]


def test_reference_vocabulary_counts_unicode_and_images_without_base64():
    assert len(reference_encoding().encode_ordinary('你好，世界！')) == 4
    payload = {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'hello'}]}]}
    text_count = estimate_input_tokens(payload)
    payload['messages'][0]['content'].append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + 'x' * 100000}})
    assert estimate_input_tokens(payload) == text_count + 4096
    payload['tools'] = [{'type': 'function', 'function': {'name': 'test', 'parameters': {'type': 'object'}}}]
    assert estimate_input_tokens(payload) > text_count + 4096


@pytest.mark.parametrize('window,output,expected', [(512, None, 128), (32768, None, 4096), (512, 400, 400)])
def test_configured_output_is_explicit_or_automatic(window, output, expected):
    profile = local().model_copy(update={'source': None, 'context_window_tokens': window, 'parameters': {} if output is None else {'max_tokens': output}})
    assert configured_limits(profile).output_tokens == expected


def test_provider_window_persistence_required_error_and_public_v1_unchanged(presentation_client):
    client, upstream = presentation_client
    profile = configure_model(client, context_window_tokens=None, request_options={'streaming': False})
    session = ok(client.post('/api/sessions', json={'model_profile_id': profile['id']}))
    result = send(client, session)
    assert result['run']['error_code'] == 'CONTEXT_WINDOW_REQUIRED' and not upstream.calls
    assert ok(client.get(f"/api/models/profiles/{profile['id']}"))['context_window_tokens'] is None
    ok(client.patch(f"/api/models/profiles/{profile['id']}", json={'context_window_tokens': 1024}))
    assert ok(client.get(f"/api/models/profiles/{profile['id']}"))['context_window_tokens'] == 1024
    result = send(client, session)
    assert result['success'] and upstream.calls[-1]['max_tokens'] == 256
    stats = details(client, result['run'])[0]['budget']
    assert stats['counting'] == 'estimated' and stats['margin_tokens'] == 128
    assert stats['input_budget_tokens'] == 640
    assert result['run']['metadata']['configuration']['context_limits'] == {'window_tokens': 1024, 'output_tokens': 256}
    ok(client.patch('/api/models/settings', json={'external_enabled': True, 'external_api_key': 'test-key'}))
    public = TestClient(client.app, client=('127.0.0.1', 12345))
    response = public.post('/v1/chat/completions', headers={'Authorization': 'Bearer test-key'},
        json={'model': profile['alias'], 'messages': [{'role': 'user', 'content': 'public'}]})
    assert response.status_code == 200, response.text
    assert 'max_tokens' not in upstream.calls[-1]


@pytest.mark.parametrize('streaming', [False, True])
def test_provider_trims_history_and_preserves_snapshot_attachment_indices(presentation_client, streaming):
    client, upstream = presentation_client
    session = configure(client, harness=False, streaming=streaming)
    ok(client.patch(f"/api/models/profiles/{session['model_profile_id']}", json={'context_window_tokens': 512}))
    state = client.app.state.runtime_state
    old = state.messages.add_message(session['session_id'], 'user', 'old ' * 600,
        metadata={'attachments': [{'id': 'old-file', 'type': 'file', 'name': 'old.txt', 'uri': 'local://attachments/old.txt'}]})
    state.messages.add_message(session['session_id'], 'assistant', 'old answer', parent_message_id=old.message_id)
    other_session = ok(client.post('/api/sessions', json={}))
    other = state.messages.add_message(other_session['session_id'], 'user', 'private-other-session')
    result = send(client, session, 'current')
    assert result['success'], result
    snapshot = details(client, result['run'])[0]
    assert snapshot['request'] == upstream.calls[-1]
    assert snapshot['budget']['removed_turns'] == 1
    assert snapshot['attachment_ids'] == []
    assert [s['message_index'] for s in snapshot['sources'] if s['kind'] == 'current_input'] == [1]
    assert any(e['reason'] == 'token_limit' and e['reference_id'] == old.message_id for e in snapshot['exclusions'])
    assert state.messages.get_message(old.message_id) and state.messages.get_message(other.message_id)
    assert snapshot['budget']['input_tokens'] + snapshot['budget']['output_tokens'] + snapshot['budget']['margin_tokens'] <= 512


def test_tool_growth_and_approval_resume_recheck_saved_limits(presentation_client, tmp_path):
    client, upstream = presentation_client
    session = configure(client, harness=True, streaming=False)
    ok(client.patch(f"/api/models/profiles/{session['model_profile_id']}", json={'context_window_tokens': 4096}))
    note = tmp_path / 'data/knowledge/large.txt'
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text('tool result ' * 5000, encoding='utf-8')
    upstream.turns = [completion(tool_call('read_file', {'path': 'data/knowledge/large.txt'})), completion(content='must not execute')]
    result = send(client, session, 'read the file')
    assert result['run']['status'] == 'WAITING_FOR_USER', result
    assert client.patch(f"/api/models/profiles/{session['model_profile_id']}", json={'context_window_tokens': 32768}).status_code == 409
    run_id = result['run']['run_id']
    response = client.post(f'/api/tools/approvals/{run_id}', json={'decision': 'approve'})
    resumed = ok(response)
    assert resumed['run']['error_code'] == 'CONTEXT_WINDOW_EXCEEDED', resumed
    assert len(upstream.calls) == 1


@pytest.mark.parametrize('adapter_type,path,body', [
    (LlamaServerAdapter, '/props', {'default_generation_settings': {'n_ctx': 2048}}),
    (TransformersServerAdapter, '/health', {'context_window_tokens': 2048}),
])
def test_native_counting_transport_validates_responses(adapter_type, path, body):
    async def scenario():
        responses = [body, {'input_tokens': 73}, {'input_tokens': True}]
        paths = []
        def handle(request):
            paths.append(request.url.path)
            return httpx.Response(200, json=responses.pop(0))
        adapter = object.__new__(adapter_type)
        async with httpx.AsyncClient(base_url='http://local.test', transport=httpx.MockTransport(handle)) as client:
            adapter.client = client
            assert await adapter.context_window() == 2048
            assert await adapter.count_input_tokens({'messages': []}) == 73
            with pytest.raises(ModelError) as exc:
                await adapter.count_input_tokens({'messages': []})
            assert exc.value.code == 'CONTEXT_COUNT_FAILED'
        assert paths == [path, '/v1/chat/completions/input_tokens', '/v1/chat/completions/input_tokens']
    asyncio.run(scenario())


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('failure', ['CONTEXT_WINDOW_EXCEEDED', 'CONTEXT_COUNT_FAILED'])
def test_budget_failure_releases_lease_without_marking_local_model_failed(tmp_path, stream, failure):
    from tests.test_phase2a_manager import local_manager_fixture, request
    async def scenario():
        manager, profile, adapter = local_manager_fixture(tmp_path, {'unload': 'manual'})
        adapter.context_window = AsyncMock(return_value=4096)
        adapter.count_input_tokens = AsyncMock(return_value=4096,
            side_effect=ModelError(failure, 'count failed', 502) if failure == 'CONTEXT_COUNT_FAILED' else None)
        budget = ChatContextBudget(configured_limits(manager.profile(profile.id)), ContextTrace())
        try:
            with pytest.raises(ModelError) as exc:
                if stream:
                    async for _ in manager.chat_stream(profile.id, request(True), budget=budget):
                        pass
                else:
                    await manager.chat(profile.id, request(), budget=budget)
            assert exc.value.code == failure
            assert manager.status(profile.id).state == 'ready'
            assert manager.status(profile.id).active == manager.status(profile.id).queued == 0
            assert adapter.loads == 1 and not adapter.started.is_set()
        finally:
            await manager.close()
    asyncio.run(scenario())
