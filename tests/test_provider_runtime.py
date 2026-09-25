"""Provider and local runtime configuration, release integrity and maintenance boundaries."""
import asyncio
import base64
import csv
from email.parser import BytesParser
import hashlib
from io import StringIO
import json
from pathlib import Path
import threading
from unittest.mock import AsyncMock
import zipfile

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.catalog import CATALOG_ROOT, catalog
from ai_workbench.core.models.schema import ProviderProfile, ChatRequest, ModelProfile
from ai_workbench.core.models.store import ProviderProfileStore, ModelProfileStore, ModelSettingsStore, LocalRuntimeSettingsStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.db.models import (
    AppMetadataRecord, ModelProfileRecord, RuntimeInstallationRecord, KnowledgeBaseRecord, KnowledgeSettingsRecord,
    MessageRecord, PersonaKnowledgeBindingRecord, RunRecord, SessionRecord,
)
from ai_workbench.workers.tts_catalog import language_model
from tests.model_fixtures import MockOpenAI, configure_model, resolve_local_profile, write_local_model
from tests.test_phase2a_manager import ControlledAdapter
from tests.test_phase2b_runtime import installed_worker
from tests.test_tts import language_tree


@pytest.mark.parametrize('memory', [True, False])
def test_providers_and_local_settings_have_separate_ownership(tmp_path, memory):
    write_local_model(tmp_path, 'llms/weights', 'llama-server')
    app = create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'app.db'}", adapter_factory=MockOpenAI().factory)
    with TestClient(app) as client:
        assert client.get('/api/models/providers').json() == []
        local_path = '/api/models/local-runtime/settings'
        local = client.get(local_path).json()
        assert set(local) == {'enabled', 'download'} and local['enabled']
        for values in ({'id': 'local'}, {'name': 'Local'}, {'connection': {}}, {'type': 'local'}):
            assert client.patch(local_path, json=values).status_code == 422
        assert client.patch(local_path, json={'download': {'http_proxy': 'http://127.0.0.1:8080'}}).status_code == 200
        assert client.patch(local_path, json={'download': {'pypi_index_url': 'https://pypi.org/simple'}}).json()['download']['http_proxy'].endswith(':8080')
        assert client.patch(local_path, json={'download': {'http_proxy': ''}}).json()['download']['http_proxy'] is None
        model = configure_model(client)
        provider_id = model['source']['provider_profile_id']
        path = '/api/models/providers/' + provider_id
        assert client.get(path).json()['connection']['has_api_key']
        assert 'provider-private-key' not in client.get(path).text
        assert client.patch(path, json={'connection': {'timeout_seconds': 20}}).status_code == 200
        assert app.state.runtime_state.provider_profiles.get(provider_id).connection.api_key == 'provider-private-key'
        assert client.patch(path, json={'connection': {'api_key': ''}}).json()['connection']['has_api_key'] is False
        for values in ({'download': {}}, {'type': 'local'}, {'connection': None}):
            assert client.patch(path, json=values).status_code == 422
        assert client.delete(path).status_code == 409
        assert client.get(path + '/models').json()['models'] == ['embed', 'fake', 'other']
        assert client.patch(local_path, json={'enabled': False}).json()['enabled'] is False
        profile = client.post('/api/models/profiles', json={'name': 'Local', 'alias': 'managed', 'kind': 'llm',
            'model_ref': 'llms/weights', 'source': {'type': 'local'}}).json()
        assert client.post(f"/api/models/profiles/{profile['id']}/load").json()['error']['code'] == 'MODEL_UNAVAILABLE'


@pytest.mark.parametrize('field,value', [('backend_profile_id', 'local'), ('execution_options', {}), ('lifecycle', {}),
    ('provider_profile_id', None), ('runtime_id', 'llama-server'), ('runtime_variant', 'cpu'), ('runtime_options', {})])
def test_removed_model_fields_are_rejected_on_create_and_patch(tmp_path, field, value):
    with TestClient(create_app(root=tmp_path, use_memory=True)) as client:
        payload = {'name': 'Draft', 'alias': 'draft', 'kind': 'llm', 'model_ref': 'llms/gguf'}
        draft = client.post('/api/models/profiles', json=payload).json()
        assert client.post('/api/models/profiles', json={**payload, field: value}).status_code == 422
        assert client.patch(f"/api/models/profiles/{draft['id']}", json={field: value}).status_code == 422
        assert client.get(f"/api/models/profiles/{draft['id']}").json()['source'] is None


@pytest.mark.parametrize('memory', [True, False])
def test_source_roundtrip_and_atomic_patch(tmp_path, memory):
    write_local_model(tmp_path, 'llms/gguf', 'llama-server')
    app = create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'app.db'}")
    with TestClient(app) as client:
        provider = client.post('/api/models/providers', json={'name': 'Cloud', 'connection': {'base_url': 'https://example.test/v1'}}).json()
        binding = {'type': 'provider', 'provider_profile_id': provider['id']}
        draft = client.post('/api/models/profiles', json={'name': 'Draft', 'alias': 'draft', 'kind': 'llm', 'model_ref': 'llms/gguf'}).json()
        path = '/api/models/profiles/' + draft['id']
        assert draft['source'] is None
        local = client.patch(path, json={'source': {'type': 'local', 'lifecycle': {'unload': 'idle'}}})
        assert local.status_code == 200, local.text
        assert local.json()['source']['lifecycle'] == {'unload': 'idle', 'idle_seconds': 300}
        assert local.json()['source']['execution_options']['gpu_layers'] == 'auto'
        assert client.patch(path, json={'source': binding}).json()['source'] == binding
        assert client.patch(path, json={'name': 'Renamed'}).json()['source'] == binding
        for invalid in ({**binding, 'execution_options': {}}, {**binding, 'lifecycle': {}},
                        {'type': 'local', 'provider_profile_id': provider['id']}, {'provider_profile_id': provider['id']}, {}):
            assert client.patch(path, json={'source': invalid}).status_code == 422
            assert client.get(path).json()['source'] == binding
        assert client.patch(path, json={'source': None}).json()['source'] is None
        assert client.get(path).json()['model_ref'] == draft['model_ref']
        local = client.patch(path, json={'source': {'type': 'local'}}).json()['source']
        assert local['lifecycle']['unload'] == 'manual'
        assert client.delete('/api/models/providers/' + provider['id']).status_code == 200


def test_database_rejects_inconsistent_source_columns(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'sources.db'}")
    init_db(engine)
    provider = ProviderProfileStore(engine).create(ProviderProfile(name='Provider', connection={'base_url': 'https://provider.test/v1'}))
    invalid = [
        {'source_type': 'other'}, {'provider_profile_id': provider.id}, {'execution_options_json': '{}'},
        {'source_type': 'provider'}, {'source_type': 'provider', 'provider_profile_id': provider.id, 'lifecycle_json': '{}'},
        {'source_type': 'provider', 'provider_profile_id': provider.id, 'kind': 'tts'},
        {'source_type': 'local', 'execution_options_json': '{}'},
        {'source_type': 'local', 'execution_options_json': '{}', 'lifecycle_json': '{}', 'provider_profile_id': provider.id},
        {'source_type': 'provider', 'provider_profile_id': provider.id, 'kind': 'reranker'},
    ]
    try:
        for index, values in enumerate(invalid):
            with Session(engine) as db, pytest.raises(IntegrityError):
                db.add(ModelProfileRecord(**{'id': str(index), 'name': 'Invalid', 'alias': str(index), 'kind': 'llm', 'model_ref': 'weights', **values}))
                db.commit()
    finally:
        engine.dispose()


def test_provider_and_source_edits_reject_active_requests(tmp_path):
    adapter = ControlledAdapter()
    with TestClient(create_app(root=tmp_path, use_memory=True, adapter_factory=lambda _: adapter)) as client:
        profile = configure_model(client)
        manager = client.app.state.runtime_state.model_manager
        task = client.portal.start_task_soon(manager.chat, profile['id'], ChatRequest(
            model=profile['alias'], messages=[{'role': 'user', 'content': 'hello'}]))
        client.portal.call(adapter.started.wait)
        try:
            for path, patch in (
                ('/api/models/providers/' + profile['source']['provider_profile_id'], {'name': 'Changed'}),
                ('/api/models/profiles/' + profile['id'], {'source': None}),
            ):
                response = client.patch(path, json=patch)
                assert response.status_code == 409 and response.json()['error']['code'] == 'MODEL_BUSY'
        finally:
            client.portal.call(adapter.release.set)
            task.result(timeout=5)
        assert client.patch('/api/models/profiles/' + profile['id'], json={'source': None}).status_code == 200


def test_removed_routes_and_single_release_catalog(tmp_path):
    with TestClient(create_app(root=tmp_path, use_memory=True)) as client:
        for method, path in [('get', '/backends'), ('post', '/backends'), ('patch', '/backends/local'),
            ('get', '/backends/local/runtime'), ('get', '/backends/local/runtime/catalog'),
            ('get', '/runtimes/jobs'), ('get', '/runtimes/storage'), ('post', '/runtimes/cache/cleanup'),
            ('get', '/runtime/settings'), ('get', '/runtimes'), ('get', '/runtimes/catalog')]:
            assert client.request(method, '/api/models' + path).status_code == 404
        release = client.get('/api/models/local-runtime/catalog').json()
        assert {item['engine'] for item in release['engines']} == {'llama-server', 'transformers', 'kokoro', 'wd14', 'chatterbox', 'qwen3tts', 'siglip2', 'sentence-transformers', 'cross-encoder', 'whisper'}
        assert 'backend_profile_id' not in client.get('/api/models/local-runtime').json()
        for kind in ('asr', 'tts'):
            assert client.post('/api/models/profiles', json={'name': 'Private', 'alias': 'private',
                'kind': kind, 'model_ref': 'asr/whisper', 'source': {'type': 'local'},
                'parameters': {'architecture': 'whisper'}}).status_code == 422


@pytest.mark.parametrize('kind,ref,engine,device', [
    ('llm', 'llms/gguf', 'llama-server', 'cuda'), ('llm', 'llms/model', 'transformers', 'cuda'),
    ('tts', 'tts/kokoro', 'kokoro', 'cpu'),
    ('vision', 'vision/tagger', 'wd14', 'cpu'),
    ('tts', 'tts/chatterbox', 'chatterbox', 'cuda'),
    ('tts', 'tts/qwen', 'qwen3tts', 'cuda'),
])
def test_execution_defaults_follow_model_engine(tmp_path, kind, ref, engine, device):
    write_local_model(tmp_path, ref, engine)
    profile = resolve_local_profile(tmp_path, ModelProfile(name='Local', alias='local', kind=kind, model_ref=ref, source={'type': 'local'}))
    assert profile.source.execution_options['device'] == device and profile.source.lifecycle.unload == 'manual'
    if engine == 'llama-server':
        assert profile.source.execution_options['gpu_layers'] == 'auto'
        cpu = resolve_local_profile(tmp_path, ModelProfile(**{**profile.model_dump(), 'source': {'type': 'local', 'execution_options': {'device': 'cpu'}}}))
        assert cpu.source.execution_options['gpu_layers'] == 0


@pytest.mark.parametrize('kind', ['embedding', 'reranker'])
def test_local_embedding_and_reranker_binding_with_unbound_drafts(kind):
    values = dict(name='Local model', alias='local-model', kind=kind, model_ref='local/model')
    assert ModelProfile(**values).source is None
    local = ModelProfile(**values, source={'type': 'local'})
    assert local.parameters == ({'query_prompt_name': None, 'document_prompt_name': None} if kind == 'embedding' else {})
    assert local.source.execution_options == {'device': 'cuda', 'intraop_threads': 4, 'max_batch_size': 1}


@pytest.mark.parametrize('metadata', [[], {}, {'lang': 'en', 'version': '3.7.2'}])
def test_kokoro_corrupt_manual_pipeline_fails_before_engine_import(tmp_path, metadata, monkeypatch):
    from ai_workbench.workers.tts_engine import TTSEngine
    from ai_workbench.workers.common import WorkerError
    path = language_tree(tmp_path)
    (path / 'meta.json').write_text(json.dumps(metadata))
    monkeypatch.setattr('ai_workbench.workers.tts_engine.require_offline', lambda: None)
    with pytest.raises(WorkerError) as error:
        TTSEngine(tmp_path, 'tts', {}, {}, models_root=tmp_path / 'data/models')
    assert error.value.code == 'MODEL_NOT_FOUND'
    assert not (tmp_path / 'data/runtimes').exists()


def test_maintenance_blocks_new_local_requests_and_preserves_external_inference(tmp_path):
    async def scenario():
        supervisor, manager, local = await installed_worker(tmp_path)
        external_adapter = ControlledAdapter()
        manager.adapter_factory = lambda _: external_adapter
        backend = manager.providers.create(ProviderProfile(name='External', connection={'base_url': 'http://external.test/v1'}))
        external = manager.profiles.create(ModelProfile(name='External', alias='external', kind='llm', model_ref='weights', source={'type': 'provider', 'provider_profile_id': backend.id}))
        request = asyncio.create_task(manager.chat(external.id, ChatRequest(model='external', messages=[{'role': 'user', 'content': 'Hello'}])))
        await external_adapter.started.wait()
        install_started, finish_install = asyncio.Event(), asyncio.Event()
        install = supervisor._install_python
        async def paused_install(*args):
            install_started.set()
            await finish_install.wait()
            await install(*args)
        supervisor._install_python = paused_install
        try:
            job = await supervisor.submit('repair')
            await install_started.wait()
            with pytest.raises(ModelError) as error:
                await manager.load(local.id)
            assert error.value.code == 'RUNTIME_INSTALLING'
            assert not external_adapter.closed and manager.status(external.id).active == 1
            external_adapter.release.set()
            assert (await request).message.content == 'reply'
            finish_install.set()
            await supervisor.task
            assert supervisor.store.job(job.id).state == 'completed'
        finally:
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
            await manager.close()
            await supervisor.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('operation', ['repair', 'uninstall'])
def test_slow_maintenance_filesystem_keeps_external_request_responsive(tmp_path, monkeypatch, operation):
    from ai_workbench.core.models.runtimes import supervisor as runtime_module

    async def scenario():
        supervisor, manager, _ = await installed_worker(tmp_path)
        external_adapter = ControlledAdapter()
        manager.adapter_factory = lambda _: external_adapter
        backend = manager.providers.create(ProviderProfile(name='External', connection={'base_url': 'http://external.test/v1'}))
        external = manager.profiles.create(ModelProfile(name='External', alias='external', kind='llm', model_ref='weights', source={'type': 'provider', 'provider_profile_id': backend.id}))
        entered, release, expired = threading.Event(), threading.Event(), threading.Event()
        function = 'extract_archive' if operation == 'repair' else 'remove_owned'
        original = getattr(runtime_module, function)

        def slow_filesystem(*args):
            entered.set()
            if not release.wait(5):
                expired.set()
            return original(*args)

        monkeypatch.setattr(runtime_module, function, slow_filesystem)
        request = asyncio.create_task(manager.chat(external.id,
            ChatRequest(model='external', messages=[{'role': 'user', 'content': 'Hello'}])))
        try:
            await external_adapter.started.wait()
            job = await supervisor.submit(operation)
            assert await asyncio.to_thread(entered.wait, 2)
            external_adapter.release.set()
            assert (await request).message.content == 'reply'
            assert not supervisor.task.done() and not release.is_set() and not expired.is_set()
            release.set()
            await supervisor.task
            assert supervisor.store.job(job.id).state == 'completed'
        finally:
            release.set()
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
            if supervisor.task:
                await supervisor.task
            await manager.close()
            await supervisor.close()
    asyncio.run(scenario())


def test_database_revision_resets_bindings_without_converting_or_removing_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.UNIFIED_BACKEND_REVISION)
    with engine.begin() as db:
        for profile_id, kind in [('chat', 'llm'), ('embed', 'embedding')]:
            db.execute(text("""INSERT INTO model_profiles
                (id, alias, name, kind, model_ref, capabilities_json, parameters_json, lifecycle_json,
                 enabled, external_enabled, created_at, updated_at, execution_options_json)
                VALUES (:id,:id,:id,:kind,'old/ref','{}','{}','{}',1,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'{}')"""), {'id': profile_id, 'kind': kind})
        db.execute(text("""INSERT INTO runtime_installations
            (backend_profile_id,version,state,job_id,manifest_sha256,updated_at)
            VALUES ('local','1.0.0','installed','installed-job',:digest,'2026-09-21 12:34:56.123456')"""), {'digest': 'a' * 64})
        for job_id, version, operation, backend in [('installed-job', '1.0.0', 'install', 'local'), ('cache-job', None, 'cache_clean', None)]:
            db.execute(text("""INSERT INTO runtime_jobs
                (id,backend_profile_id,version,operation,state,stage,progress_current,cancel_requested,log_path,revision,created_at,updated_at,finished_at,result_json)
                VALUES (:id,:backend,:version,:operation,'completed','completed',1,0,:log,9,
                    '2026-09-21 12:34:56.123456','2026-09-21 12:34:56.123456','2026-09-21 12:34:56.123456',:result)"""),
                {'id': job_id, 'backend': backend, 'version': version, 'operation': operation, 'log': f'logs/{job_id}.log',
                 'result': '{"before":null,"after":null}' if version is None else None})
        old_installation = dict(db.execute(text('SELECT * FROM runtime_installations')).mappings().one())
        old_jobs = [dict(row) for row in db.execute(text('SELECT * FROM runtime_jobs ORDER BY id')).mappings()]
    persona = '00000000-0000-4000-8000-000000000001'
    with Session(engine) as db:
        db.add(AppMetadataRecord(key='local_runtime_settings', value='{"enabled":false}'))
        db.add(AppMetadataRecord(key='unrelated', value='{"keep":true}'))
        db.add(AppMetadataRecord(key='model_settings', value=json.dumps({'default_model_profile_id': 'chat', 'utility_model_profile_id': 'chat', 'external_api_key': 'retained', 'max_request_mb': 7})))
        db.add(KnowledgeBaseRecord(id='kb', name='Dependent', embedding_model_profile_id='embed'))
        db.add(PersonaKnowledgeBindingRecord(persona_id=persona, knowledge_base_id='kb'))
        db.add(KnowledgeSettingsRecord(id=1, reranker_model_profile_id='embed'))
        db.add(SessionRecord(session_id='s', current_persona_id=persona, model_profile_id='chat', waiting_run_id='active', context_policy_json='{}'))
        for run_id, state in [('active','WAITING_APPROVAL'), ('finished','DONE')]:
            db.add(RunRecord(run_id=run_id, kind='chat', persona_id=persona, session_id='s', status=state, config_snapshot_json='{"model_profile_id":"chat"}'))
            db.add(MessageRecord(message_id=run_id, session_id='s', role='assistant', run_id=run_id))
        db.commit()
    paths = [tmp_path / 'data' / folder / 'keep' for folder in ('models','attachments','runtimes','knowledge','logs','cache')]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'protected')
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    init_db(engine)
    init_db(engine)
    assert ModelProfileStore(engine).list() == []
    assert ProviderProfileStore(engine).list() == []
    assert LocalRuntimeSettingsStore(engine).get().enabled
    assert ModelSettingsStore(engine).get().external_api_key == 'retained'
    assert ModelSettingsStore(engine).get().max_request_mb == 7
    assert ModelSettingsStore(engine).get().default_model_profile_id is None
    with Session(engine) as db:
        assert db.get(KnowledgeBaseRecord, 'kb') is None
        assert db.get(KnowledgeSettingsRecord, 1).reranker_model_profile_id is None
        assert db.get(SessionRecord, 's').model_profile_id is None and db.get(SessionRecord, 's').waiting_run_id is None
        assert db.get(RunRecord, 'active') is None and db.get(MessageRecord, 'active') is None
        assert db.get(RunRecord, 'finished') is not None and db.get(MessageRecord, 'finished') is not None
        assert db.get(AppMetadataRecord, 'local_runtime_settings') is None
        assert db.get(AppMetadataRecord, 'unrelated').value == '{"keep":true}'
        expected_installation = {**old_installation, 'id': old_installation['backend_profile_id']}
        del expected_installation['backend_profile_id']
        assert dict(db.exec(text('SELECT * FROM runtime_installations')).mappings().one()) == expected_installation
        for job in old_jobs:
            del job['backend_profile_id']
        assert [dict(row) for row in db.exec(text('SELECT * FROM runtime_jobs ORDER BY id')).mappings()] == old_jobs
        with pytest.raises(IntegrityError):
            db.add(RuntimeInstallationRecord(id='second', version='1', state='installed'))
            db.commit()
        db.rollback()
        assert db.exec(text('PRAGMA foreign_key_check')).all() == []
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == before
    engine.dispose()


def test_full_dependency_lock_and_all_three_wheels_are_auditable(tmp_path):
    from scripts.build_runtime_wheels import SPECS
    release = catalog('windows', 'x86_64')
    packages, current = {}, None
    for line in (CATALOG_ROOT / release.requirements).read_text().splitlines():
        if not line or line.lstrip().startswith('#'):
            continue
        if line[0].isspace():
            assert line.strip().startswith('--hash=sha256:')
            packages[current][1].append(line.strip().removeprefix('--hash=sha256:').rstrip(' \\'))
        else:
            current, version = line.rstrip(' \\').split('==')
            packages[current] = (version, [])
    expected = {'torch': '2.11.0+cu128', 'torchaudio': '2.11.0+cu128', 'torchvision': '0.26.0+cu128',
        'transformers': '5.16.1', 'numpy': '1.26.4', 'onnxruntime': '1.23.2', 'spacy': '3.7.5', 'thinc': '8.2.5',
        'tokenizers': '0.23.2', 'jaconv': '0.5.0', 'lameenc': '1.8.1'}
    assert {name: packages[name][0] for name in expected} == expected
    assert all(hashes and all(len(value) == 64 for value in hashes) for _, hashes in packages.values())
    for name, spec in SPECS.items():
        version = spec['patched_version']
        wheel = CATALOG_ROOT / 'wheels' / f'{name}-{version}-py3-none-any.whl'
        assert hashlib.sha256(wheel.read_bytes()).hexdigest() in packages[name.replace('_','-')][1]
        with zipfile.ZipFile(wheel) as archive:
            info = f'{name}-{version}.dist-info'
            metadata = BytesParser().parsebytes(archive.read(info + '/METADATA'))
            assert metadata['Version'] == version
            assert set(spec['requirements'].values()) <= set(metadata.get_all('Requires-Dist'))
            patch = json.loads(archive.read(info + '/WORKBENCH_PATCH.json'))
            assert patch['upstream_sha256'] == spec['sha256'] and patch['source_changes'] == spec.get('source_changes', [])
            for file, digest, size in csv.reader(StringIO(archive.read(info + '/RECORD').decode())):
                if digest:
                    data = archive.read(file)
                    assert len(data) == int(size)
                    assert digest == 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
