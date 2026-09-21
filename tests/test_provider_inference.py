"""Optional discovery and inference-driven provider availability."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.schema import ChatRequest, ModelProfile, ProviderProfile
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from tests.model_fixtures import MockOpenAI, configure_model


def make_manager(handler):
    providers = ProviderProfileStore()
    provider = providers.create(ProviderProfile(name='Cloud', connection={'base_url': 'https://provider.test/v1'}))
    manager = ModelManager(ModelProfileStore(), providers, ModelSettingsStore(),
        adapter_factory=lambda connection: OpenAIAdapter(connection, transport=httpx.MockTransport(handler)))
    return manager, provider


def add_model(manager, provider, mode):
    return manager.profiles.create(ModelProfile(name=mode, alias=mode, kind='embedding' if mode == 'embedding' else 'llm',
        model_ref='manually-entered', source={'type': 'provider', 'provider_profile_id': provider.id},
        capabilities={'streaming': mode == 'stream'}))


async def infer(manager, profile, mode):
    if mode == 'embedding':
        return await manager.embed(profile.id, ['hello'])
    request = ChatRequest(model=profile.alias, messages=[{'role': 'user', 'content': 'hello'}], stream=mode == 'stream')
    if mode == 'stream':
        return [chunk async for chunk in manager.chat_stream(profile.id, request)]
    return await manager.chat(profile.id, request)


@pytest.mark.parametrize('mode', ['chat', 'stream', 'embedding'])
@pytest.mark.parametrize('discovery_status,discovery_body', [
    (404, {}), (500, {'error': 'private'}), (200, {'data': []}),
    (200, {'data': [{'id': 'some-other-model'}]}), (200, {'data': [{'missing': 'id'}]}),
])
def test_manual_ids_execute_without_discovery_and_discovery_never_changes_status(mode, discovery_status, discovery_body):
    async def scenario():
        upstream = MockOpenAI()
        calls = []
        async def handle(request):
            calls.append((request.method, request.url.path))
            if request.method == 'GET':
                return httpx.Response(discovery_status, json=discovery_body)
            return await upstream.handle(request)
        manager, provider = make_manager(handle)
        profile = add_model(manager, provider, mode)
        try:
            assert manager.status(profile.id).state == 'unknown'
            await infer(manager, profile, mode)
            assert calls == [('POST', '/v1/embeddings' if mode == 'embedding' else '/v1/chat/completions')]
            status = manager.status(profile.id)
            assert (status.state, status.runtime, status.residency, status.unload_supported) == ('ready', None, 'unknown', False)
            try:
                await manager.provider_models(provider.id)
            except ModelError as error:
                assert error.code in {'PROVIDER_ERROR', 'PROVIDER_PROTOCOL_ERROR'}
                assert 'private' not in error.message
            assert manager.status(profile.id) == status
            await infer(manager, profile, mode)
            assert [method for method, _ in calls] == ['POST', 'GET', 'POST']
            assert all(call['model'] == 'manually-entered' for call in upstream.calls)
        finally:
            await manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['chat', 'stream', 'embedding'])
@pytest.mark.parametrize('failure', ['http', 'protocol'])
def test_failed_inference_can_retry_and_clear_the_error(mode, failure):
    async def scenario():
        upstream = MockOpenAI()
        broken = True
        async def handle(request):
            assert request.method == 'POST'
            if broken:
                if failure == 'http':
                    return httpx.Response(503, json={'error': {'message': 'private-upstream-details'}})
                if mode == 'stream':
                    event = {'choices': [{'index': 0, 'delta': {'content': 'partial'}, 'finish_reason': None}]}
                    return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, text='data: ' + json.dumps(event) + '\n\n')
                return httpx.Response(200, json={'data': [{'index': 0, 'embedding': []}]} if mode == 'embedding' else {'choices': []})
            return await upstream.handle(request)
        manager, provider = make_manager(handle)
        profile = add_model(manager, provider, mode)
        try:
            with pytest.raises(ModelError) as error:
                await infer(manager, profile, mode)
            failed = manager.status(profile.id)
            assert failed.state == 'failed' and failed.error_code == error.value.code
            assert failed.active == failed.queued == 0
            broken = False
            await infer(manager, profile, mode)
            assert manager.status(profile.id).state == 'ready'
            assert manager.status(profile.id).error_code is None
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_local_operations_and_unbound_execution_do_not_contact_provider(tmp_path):
    upstream = MockOpenAI()
    with TestClient(create_app(root=tmp_path, use_memory=True, adapter_factory=upstream.factory), client=('127.0.0.1', 40001)) as client:
        model = configure_model(client)
        path = '/api/models/profiles/' + model['id']
        for operation in ('health', 'load', 'unload'):
            response = client.post(path + '/' + operation)
            assert response.status_code == 422 and response.json()['error']['code'] == 'UNSUPPORTED_CAPABILITY'
        assert client.get(path + '/log').json()['error']['code'] == 'UNSUPPORTED_CAPABILITY'
        manager = client.app.state.runtime_state.model_manager
        assert manager._slots == {} and client.get(path + '/status').json()['state'] == 'unknown'
        assert client.patch(path, json={'source': None}).status_code == 200
        client.patch('/api/models/settings', json={'external_enabled': True, 'external_api_key': 'test-key'})
        result = client.post('/v1/chat/completions', headers={'Authorization': 'Bearer test-key'}, json={
            'model': model['alias'], 'messages': [{'role': 'user', 'content': 'hello'}]})
        assert result.json()['error']['code'] == 'MODEL_NOT_CONFIGURED'
        assert manager._slots == {} and upstream.calls == []


@pytest.mark.parametrize('mode', ['chat', 'stream', 'embedding'])
def test_public_inference_accepts_manual_ids_without_discovery(tmp_path, mode):
    upstream = MockOpenAI()
    calls = []
    async def handle(request):
        calls.append(request.method)
        assert request.method == 'POST', 'Inference must not discover provider models'
        return await upstream.handle(request)
    with TestClient(create_app(root=tmp_path, use_memory=True,
            adapter_factory=lambda connection: OpenAIAdapter(connection, transport=httpx.MockTransport(handle))),
            client=('127.0.0.1', 40001)) as client:
        profile = configure_model(client, kind='embedding' if mode == 'embedding' else 'llm',
            model_ref='manual-id', capabilities={'streaming': True} if mode == 'stream' else {})
        client.patch('/api/models/settings', json={'external_enabled': True, 'external_api_key': 'test-key'})
        path = '/v1/embeddings' if mode == 'embedding' else '/v1/chat/completions'
        payload = {'input': ['hello']} if mode == 'embedding' else {
            'messages': [{'role': 'user', 'content': 'hello'}], 'stream': mode == 'stream'}
        response = client.post(path, headers={'Authorization': 'Bearer test-key'}, json={'model': profile['alias'], **payload})
        assert response.status_code == 200, response.text
        assert calls == ['POST'] and upstream.calls[0]['model'] == 'manual-id'
        status_path = f"/api/models/profiles/{profile['id']}/status"
        assert client.get(status_path).json()['state'] == 'ready'
        if mode == 'stream':
            assert response.text.endswith('data: [DONE]\n\n') and '"error"' not in response.text
            client.patch(f"/api/models/profiles/{profile['id']}", json={'source': None})
            rejected = client.post(path, headers={'Authorization': 'Bearer test-key'}, json={'model': profile['alias'], **payload})
            assert rejected.status_code == 503 and rejected.json()['error']['code'] == 'MODEL_NOT_CONFIGURED'
            assert calls == ['POST']


def test_preflight_validation_and_disabled_provider_preserve_cached_availability():
    async def scenario():
        upstream = MockOpenAI()
        manager, provider = make_manager(upstream.handle)
        profile = add_model(manager, provider, 'embedding')
        profile = manager.profiles.update(profile.id, {'parameters': {'dimensions': 2}})
        try:
            await infer(manager, profile, 'embedding')
            before = manager.status(profile.id)
            for texts, dimensions in [([], None), (['valid'], 3)]:
                with pytest.raises(ModelError):
                    await manager.embed(profile.id, texts, dimensions=dimensions)
                assert manager.status(profile.id) == before
            manager.providers.update(provider.id, {'enabled': False})
            with pytest.raises(ModelError) as error:
                await infer(manager, profile, 'embedding')
            assert error.value.code == 'MODEL_UNAVAILABLE'
            manager.providers.update(provider.id, {'enabled': True})
            assert manager.status(profile.id) == before
            assert len(upstream.calls) == 1
        finally:
            await manager.close()
    asyncio.run(scenario())
