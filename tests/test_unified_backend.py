"""Unified backend configuration, release integrity and maintenance boundaries."""
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
from ai_workbench.core.models.runtimes.catalog import CATALOG_ROOT, catalog, worker_digest
from ai_workbench.core.models.schema import BackendProfile, ChatRequest, ModelProfile
from ai_workbench.core.models.store import BackendProfileStore, ModelProfileStore, ModelSettingsStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.db.models import (
    AppMetadataRecord, BackendProfileRecord, KnowledgeBaseRecord, KnowledgeSettingsRecord,
    MessageRecord, PersonaKnowledgeBindingRecord, RunRecord, SessionRecord,
)
from ai_workbench.workers.tts_catalog import language_model
from tests.model_fixtures import MockOpenAI, configure_model
from tests.test_phase2a_manager import ControlledAdapter
from tests.test_phase2b_runtime import installed_worker
from tests.test_tts import language_tree


@pytest.mark.parametrize('memory', [True, False])
def test_single_local_backend_and_nested_secret_updates(tmp_path, memory):
    app = create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'app.db'}", adapter_factory=MockOpenAI().factory)
    with TestClient(app) as client:
        local = client.get('/api/models/backends').json()
        assert len(local) == 1 and local[0]['id'] == 'local' and local[0]['type'] == 'local'
        assert local[0]['connection'] is None
        assert client.post('/api/models/backends', json={'type': 'local', 'name': 'Duplicate'}).status_code == 409
        assert client.delete('/api/models/backends/local').status_code == 409
        assert client.patch('/api/models/backends/local', json={'id': 'renamed'}).status_code == 422
        assert client.patch('/api/models/backends/local', json={'type': 'openai_compatible'}).status_code == 409
        assert client.patch('/api/models/backends/local', json={'connection': {'base_url': 'http://invalid/v1'}}).status_code == 422
        assert client.patch('/api/models/backends/local', json={'download': {'http_proxy': 'http://127.0.0.1:8080'}}).status_code == 200
        assert client.patch('/api/models/backends/local', json={'download': {'pypi_index_url': 'https://pypi.org/simple'}}).json()['download']['http_proxy'].endswith(':8080')
        model = configure_model(client)
        path = '/api/models/backends/' + model['backend_profile_id']
        assert client.get(path).json()['connection']['has_api_key']
        assert 'provider-private-key' not in client.get(path).text
        assert client.patch(path, json={'connection': {'timeout_seconds': 20}}).status_code == 200
        assert app.state.runtime_state.backend_profiles.get(model['backend_profile_id']).connection.api_key == 'provider-private-key'
        assert client.patch(path, json={'connection': {'api_key': ''}}).json()['connection']['has_api_key'] is False
        assert client.patch(path, json={'download': {}}).status_code == 422
        assert client.patch(path, json={'type': 'local'}).status_code == 409
        assert client.delete(path).status_code == 409
        assert client.get(path + '/models').json()['models'] == ['embed', 'fake', 'other']
        assert client.get('/api/models/backends/local/models').status_code == 422
        assert client.patch('/api/models/backends/local', json={'enabled': False}).json()['enabled'] is False
        profile = client.post('/api/models/profiles', json={'name': 'Local', 'alias': 'managed', 'kind': 'llm',
            'model_ref': 'llms/weights.gguf', 'backend_profile_id': 'local'}).json()
        assert client.post(f"/api/models/profiles/{profile['id']}/load").json()['error']['code'] == 'MODEL_UNAVAILABLE'


@pytest.mark.parametrize('field,value', [('provider_profile_id', None), ('runtime_id', 'llama-server'),
    ('runtime_variant', 'cpu'), ('runtime_options', {})])
def test_removed_model_fields_are_rejected_on_create_and_patch(tmp_path, field, value):
    with TestClient(create_app(root=tmp_path, use_memory=True)) as client:
        payload = {'name': 'Draft', 'alias': 'draft', 'kind': 'llm', 'model_ref': 'llms/model.gguf'}
        draft = client.post('/api/models/profiles', json=payload).json()
        assert client.post('/api/models/profiles', json={**payload, field: value}).status_code == 422
        assert client.patch(f"/api/models/profiles/{draft['id']}", json={field: value}).status_code == 422
        assert client.get(f"/api/models/profiles/{draft['id']}").json()['backend_profile_id'] is None


def test_removed_routes_and_single_release_catalog(tmp_path):
    with TestClient(create_app(root=tmp_path, use_memory=True)) as client:
        for method, path in [('get', '/providers'), ('post', '/providers'), ('get', '/runtime/settings'),
            ('patch', '/runtime/settings'), ('get', '/runtimes'), ('get', '/runtimes/catalog'),
            ('get', '/runtimes/llama-server/cpu'), ('post', '/runtimes/python-worker/onnx-cpu/install')]:
            assert client.request(method, '/api/models' + path).status_code == 404
        release = client.get('/api/models/backends/local/runtime/catalog').json()
        assert {item['engine'] for item in release['engines']} == {'llama-server', 'transformers', 'kokoro', 'chatterbox', 'qwen3tts'}
        assert 'whisper' not in str(release)
        assert client.get('/api/models/backends/local/runtime').json()['backend_profile_id'] == 'local'
        for kind in ('asr', 'tts'):
            assert client.post('/api/models/profiles', json={'name': 'Private', 'alias': 'private',
                'kind': kind, 'model_ref': 'asr/whisper', 'backend_profile_id': 'local',
                'parameters': {'architecture': 'whisper'}}).status_code == 422


@pytest.mark.parametrize('kind,ref,parameters,device', [
    ('llm', 'llms/model.gguf', {}, 'cuda'), ('llm', 'llms/model', {}, 'cuda'),
    ('tts', 'tts/kokoro', {'architecture': 'kokoro'}, 'cpu'),
    ('tts', 'tts/chatterbox', {'architecture': 'chatterbox'}, 'cuda'),
    ('tts', 'tts/qwen', {'architecture': 'qwen3tts'}, 'cuda'),
])
def test_execution_defaults_follow_model_engine(kind, ref, parameters, device):
    profile = ModelProfile(name='Local', alias='local', kind=kind, model_ref=ref, parameters=parameters, backend_profile_id='local')
    assert profile.execution_options['device'] == device and profile.lifecycle.unload == 'manual'
    if ref.endswith('.gguf'):
        assert profile.execution_options['gpu_layers'] == 'auto'
        cpu = ModelProfile(**{**profile.model_dump(), 'execution_options': {'device': 'cpu'}})
        assert cpu.execution_options['gpu_layers'] == 0


@pytest.mark.parametrize('kind', ['embedding', 'reranker', 'image_embedding', 'vision'])
def test_deferred_local_kinds_cannot_bind_but_unbound_profiles_can_be_saved(kind):
    values = dict(name='Deferred', alias='deferred', kind=kind, model_ref='local/model')
    assert ModelProfile(**values).backend_profile_id is None
    with pytest.raises(ValidationError):
        ModelProfile(**values, backend_profile_id='local')


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
        backend = manager.backends.create(BackendProfile(name='External', type='openai_compatible', connection={'base_url': 'http://external.test/v1'}))
        external = manager.profiles.create(ModelProfile(name='External', alias='external', kind='llm', model_ref='weights', backend_profile_id=backend.id))
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
        backend = manager.backends.create(BackendProfile(name='External', type='openai_compatible',
            connection={'base_url': 'http://external.test/v1'}))
        external = manager.profiles.create(ModelProfile(name='External', alias='external', kind='llm',
            model_ref='weights', backend_profile_id=backend.id))
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
    migrations.upgrade(engine, migrations.RUNTIME_FAMILIES_REVISION)
    with engine.begin() as db:
        for profile_id, kind in [('chat', 'llm'), ('embed', 'embedding')]:
            db.execute(text("""INSERT INTO model_profiles
                (id, alias, name, kind, model_ref, capabilities_json, parameters_json, lifecycle_json,
                 enabled, external_enabled, created_at, updated_at, runtime_options_json)
                VALUES (:id,:id,:id,:kind,'old/ref','{}','{}','{}',1,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'{}')"""), {'id': profile_id, 'kind': kind})
        db.exec_driver_sql("INSERT INTO runtime_installations (id,runtime_id,variant,version,state,updated_at) VALUES ('old','llama-server','cpu','old','installed',CURRENT_TIMESTAMP)")
    persona = '00000000-0000-4000-8000-000000000001'
    with Session(engine) as db:
        db.add(AppMetadataRecord(key='runtime_settings', value='{}'))
        db.add(AppMetadataRecord(key='model_settings', value=json.dumps({'default_model_profile_id': 'chat', 'utility_model_profile_id': 'chat'})))
        db.add(KnowledgeBaseRecord(id='kb', name='Dependent', embedding_model_profile_id='embed'))
        db.add(PersonaKnowledgeBindingRecord(persona_id=persona, knowledge_base_id='kb'))
        db.add(KnowledgeSettingsRecord(id=1, reranker_model_profile_id='embed'))
        db.add(SessionRecord(session_id='s', current_persona_id=persona, model_profile_id='chat', waiting_run_id='active', context_policy_json='{}'))
        for run_id, state in [('active','WAITING_APPROVAL'), ('finished','DONE')]:
            db.add(RunRecord(run_id=run_id, kind='chat', persona_id=persona, session_id='s', status=state, config_snapshot_json='{"model_profile_id":"chat"}'))
            db.add(MessageRecord(message_id=run_id, session_id='s', role='assistant', run_id=run_id))
        db.commit()
    paths = [tmp_path / 'data' / folder / 'keep' for folder in ('models','attachments','runtimes','knowledge','logs')]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'protected')
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    init_db(engine)
    init_db(engine)
    assert ModelProfileStore(engine).list() == []
    assert [backend.id for backend in BackendProfileStore(engine).list()] == ['local']
    assert ModelSettingsStore(engine).get().default_model_profile_id is None
    with Session(engine) as db:
        assert db.get(KnowledgeBaseRecord, 'kb') is None
        assert db.get(KnowledgeSettingsRecord, 1).reranker_model_profile_id is None
        assert db.get(SessionRecord, 's').model_profile_id is None and db.get(SessionRecord, 's').waiting_run_id is None
        assert db.get(RunRecord, 'active') is None and db.get(MessageRecord, 'active') is None
        assert db.get(RunRecord, 'finished') is not None and db.get(MessageRecord, 'finished') is not None
        assert db.get(AppMetadataRecord, 'runtime_settings') is None
        assert db.exec(text('SELECT count(*) FROM runtime_installations')).scalar() == 0
        with pytest.raises(IntegrityError):
            db.add(BackendProfileRecord(id='second', name='Invalid', type='local'))
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
    for name in release.worker_files:
        (tmp_path / name).write_text(name)
    before = worker_digest(release.worker_files, tmp_path)
    (tmp_path / 'tts_engine.py').write_text('changed')
    assert worker_digest(release.worker_files, tmp_path) != before
