"""Directory discovery, local drafts and derived engine configuration."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.inspection import inspect_local_directory
from ai_workbench.core.models.inventory import inventory
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.resolution import require_directory
from ai_workbench.core.models.runtimes.schema import local_engine
from ai_workbench.core.models.schema import ModelInput, ModelProfile
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import MessageRecord, RunRecord, RuntimeInstallationRecord, RuntimeJobRecord
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers.model_catalog import inspect_directory
from tests.model_fixtures import resolve_local_profile, write_local_model


def test_gguf_inventory_and_inspection_only_read_configuration(tmp_path, monkeypatch):
    path = write_local_model(tmp_path, "llms/package", "llama-server")
    (path / "MMProj-F16.GGUF").write_bytes(b"projector")
    (path / "config.json").write_text('{"model_type":"qwen3"}')
    original = Path.open

    def metadata_only(file, *args, **kwargs):
        assert file.suffix.lower() not in {".gguf", ".onnx", ".safetensors"}
        return original(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", metadata_only)
    items = inventory(tmp_path, "llm")
    assert [item["model_ref"] for item in items] == ["llms/package"]
    assert "mmproj_refs" not in items[0]
    info = inspect_local_directory(tmp_path, "llm", "llms/package")
    assert info.engine == "llama-server" and info.main_model_ref == "llms/package/model.gguf"
    assert info.mmproj_ref == "llms/package/MMProj-F16.GGUF" and not info.diagnostics


@pytest.mark.parametrize("extra,code", [
    ({"q8.gguf": b"fixture"}, "ambiguous_model"),
    ({"mmproj-f16.gguf": b"a", "mmproj-q8.gguf": b"b"}, "ambiguous_projector"),
    ({"config.json": b"{}", "model.safetensors": b"fixture"}, "ambiguous_model"),
])
def test_gguf_ambiguity_blocks_loading(tmp_path, extra, code):
    path = write_local_model(tmp_path, "llms/package", "llama-server")
    for name, content in extra.items():
        (path / name).write_bytes(content)
    info = inspect_directory(tmp_path / "data/models", "llm", "llms/package")
    assert code in [item["code"] for item in info.diagnostics]
    with pytest.raises(WorkerError):
        info.require_complete()


def test_numbered_shards_are_one_candidate_and_require_every_part(tmp_path):
    path = tmp_path / "data/models/llms/shards"
    path.mkdir(parents=True)
    for index in range(1, 4):
        (path / f"model-0000{index}-of-00003.gguf").write_bytes(b"fixture")
    info = inspect_directory(tmp_path / "data/models", "llm", "llms/shards").require_complete()
    assert info.main_model_ref.endswith("00001-of-00003.gguf") and len(info.model_files) == 3
    (path / "model-00002-of-00003.gguf").unlink()
    info = inspect_directory(tmp_path / "data/models", "llm", "llms/shards")
    assert info.main_model_ref is None and info.diagnostics[0]["code"] == "incomplete_shards"


@pytest.mark.parametrize("engine", ["kokoro", "chatterbox", "qwen3tts", "wd14", "transformers"])
def test_supported_directories_resolve_without_saved_architecture(tmp_path, engine):
    kind = "vision" if engine == "wd14" else "llm" if engine == "transformers" else "tts"
    ref = f"{kind}/{engine}"
    path = write_local_model(tmp_path, ref, engine)
    if engine == "wd14":
        (path / "config.json").write_text('{"architecture":"swinv2_base_window8_256"}')
    before = set(sys.modules)
    profile = resolve_local_profile(tmp_path, ModelProfile(name=engine, alias=engine, kind=kind,
        model_ref=ref, source={"type": "local"}))
    require_directory(profile)
    assert local_engine(profile) == engine
    assert profile.source.execution_options["device"] == ("cpu" if engine in {"wd14", "kokoro"} else "cuda")
    assert "architecture" not in profile.parameters and "_directory" not in profile.model_dump()
    assert not {"torch", "transformers", "onnxruntime", "numpy", "tokenizers"} & (set(sys.modules) - before)
    if engine == "wd14":
        info = inspect_local_directory(tmp_path, kind, ref)
        assert info.architecture == "wd14" and info.backbone == "swinv2_base_window8_256"


def test_unsupported_tts_and_optional_wd14_configuration(tmp_path):
    path = write_local_model(tmp_path, "tts/qwen", "qwen3tts")
    (path / "config.json").write_text('{"model_type":"qwen3_tts","tts_model_type":"custom_voice"}')
    assert inspect_directory(tmp_path / "data/models", "tts", "tts/qwen").engine is None
    path = write_local_model(tmp_path, "vision/tagger", "wd14")
    (path / "config.json").write_text("broken")
    info = inspect_directory(tmp_path / "data/models", "vision", "vision/tagger").require_complete()
    assert info.engine == "wd14" and not info.diagnostics[0]["blocking"]
    (path / "model.onnx").unlink()
    assert inspect_directory(tmp_path / "data/models", "vision", "vision/tagger").engine is None


@pytest.mark.parametrize("engine,missing", [("kokoro", "model.onnx"), ("chatterbox", "ve.safetensors"),
                                         ("qwen3tts", "speech_tokenizer/model.safetensors")])
def test_incomplete_tts_keeps_detected_engine_without_reading_weights(tmp_path, monkeypatch, engine, missing):
    path = write_local_model(tmp_path, "tts/model", engine)
    (path / missing).unlink()
    original = Path.open

    def metadata_only(file, *args, **kwargs):
        assert file.suffix.lower() not in {".bin", ".onnx", ".safetensors"}
        return original(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", metadata_only)
    info = inspect_directory(tmp_path / "data/models", "tts", "tts/model")
    assert info.engine == engine
    with pytest.raises(WorkerError, match="MODEL_NOT_FOUND"):
        info.require_complete()


def test_directory_links_cannot_escape_model_storage(tmp_path):
    from tests.test_runtime_maintenance import link_directory

    model = write_local_model(tmp_path, "llms/model", "llama-server")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "model.gguf").write_bytes(b"outside")
    link_directory(model.parent / "escape", outside)
    with pytest.raises(WorkerError, match="INVALID_REQUEST"):
        inspect_directory(tmp_path / "data/models", "llm", "llms/escape")


@pytest.mark.parametrize("reference", ["../outside", "/outside", "C:/model", "tts\\model"])
def test_unsafe_directory_references_are_rejected(tmp_path, reference):
    with pytest.raises(WorkerError):
        inspect_directory(tmp_path / "data/models", "tts", reference)


@pytest.mark.parametrize("memory", [True, False])
def test_crud_defaults_drafts_sources_and_removed_inputs(tmp_path, memory):
    write_local_model(tmp_path, "tts/qwen", "qwen3tts")
    with TestClient(create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'app.db'}")) as client:
        payload = {"name": "Speech", "alias": "speech", "kind": "tts", "model_ref": "tts/qwen"}
        response = client.post("/api/models/profiles", json=payload)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["source"]["type"] == "local" and saved["source"]["execution_options"]["device"] == "cuda"
        assert saved["parameters"]["max_new_tokens"] == 2048 and "architecture" not in saved["parameters"]
        route = "/api/models/profiles/" + saved["id"]
        for patch in ({"source": None}, {"source": {"type": "provider", "provider_profile_id": "absent"}},
                      {"parameters": {"architecture": "qwen3tts"}}, {"parameters": {"cfg_weight": 0.5}}):
            assert client.patch(route, json=patch).status_code == 422
        draft = client.post("/api/models/profiles", json={**payload, "alias": "draft", "model_ref": "tts/missing"})
        assert draft.status_code == 200 and draft.json()["source"]["execution_options"] == {}
        assert draft.json()["parameters"] == {"speed": 1, "response_format": "mp3"}
        assert client.get("/api/models/inspect", params={"kind": "tts", "model_ref": "tts/missing"}).status_code == 404
        for kind in ("vision", "image_embedding", "asr"):
            result = client.post("/api/models/profiles", json={**payload, "kind": kind, "alias": kind, "model_ref": f"{kind}/missing"})
            assert result.status_code == 200, result.text
            assert result.json()["source"]["type"] == "local"
            assert client.patch("/api/models/profiles/" + result.json()["id"], json={"source": None}).status_code == 422
        for kind in ("llm", "embedding", "reranker"):
            assert client.post("/api/models/profiles", json={**payload, "kind": kind, "alias": kind, "source": None}).status_code == 200


def test_gguf_profile_keys_follow_resolved_files_and_vision(tmp_path):
    path = write_local_model(tmp_path, "llms/model", "llama-server")
    (path / "mmproj.gguf").write_bytes(b"projector")
    manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(),
        runtime_supervisor=SimpleNamespace(root=tmp_path))
    value = dict(name="LLM", alias="llm", kind="llm", model_ref="llms/model", source={"type": "local"})
    text_profile = manager.validate_binding(ModelProfile(**value))
    image_profile = manager.validate_binding(ModelProfile(**{**value, "alias": "image", "capabilities": {"vision": True}}))
    assert manager.execution_key(text_profile) != manager.execution_key(image_profile)
    assert manager.execution_key(image_profile)[-1].endswith("mmproj.gguf")
    manager.profiles.create(text_profile)
    with pytest.raises(ModelError, match="identical execution options"):
        manager.validate_binding(ModelProfile(**{**value, "alias": "conflict", "source": {"type": "local", "execution_options": {"threads": 8}}}))
    for patch in ({"model_ref": "llms/model/model.gguf"},
                  {"source": {"type": "local", "execution_options": {"mmproj_ref": "llms/model/mmproj.gguf"}}}):
        with pytest.raises(ValidationError):
            ModelInput(**{**value, **patch})


def test_loaded_gguf_paths_survive_directory_changes_until_unload(tmp_path):
    from unittest.mock import AsyncMock
    from ai_workbench.core.models.runtimes.store import RuntimeStore
    from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
    from ai_workbench.core.models.store import LocalRuntimeSettingsStore

    async def scenario():
        path = write_local_model(tmp_path, "llms/model", "llama-server")
        supervisor = RuntimeSupervisor(tmp_path, RuntimeStore(), LocalRuntimeSettingsStore())
        manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=supervisor)
        profile = manager.profiles.create(ModelProfile(name="LLM", alias="llm", kind="llm", model_ref="llms/model",
            source={"type": "local", "execution_options": {"device": "cpu"}}))
        key = manager.execution_key(profile)
        adapter = manager._managed_slot(profile).adapter
        stopped = AsyncMock()
        adapter.process = SimpleNamespace(stop=stopped)
        adapter.loaded.add(profile.id)
        adapter.state = "ready"
        try:
            (path / "model.gguf").rename(path / "replacement.gguf")
            assert manager.profile(profile.id)._directory.main_model_ref == "llms/model/model.gguf"
            assert manager.execution_key(manager.profiles.get(profile.id)) == key
            await manager.unload(profile.id)
            stopped.assert_awaited_once()
            current = manager.profile(profile.id)
            assert current._directory.main_model_ref == "llms/model/replacement.gguf"
            assert manager.execution_key(current) != key
        finally:
            await manager.close()
            await supervisor.close()

    asyncio.run(scenario())


@pytest.mark.parametrize('device', ['cpu', 'cuda'])
@pytest.mark.parametrize('vision', [False, True])
def test_llama_command_uses_detected_main_and_optional_projector(tmp_path, monkeypatch, device, vision):
    from unittest.mock import AsyncMock
    from ai_workbench.core.models.runtimes import adapters
    from ai_workbench.core.models.runtimes.process import ManagedProcess
    from ai_workbench.core.models.runtimes.store import RuntimeStore
    from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
    from ai_workbench.core.models.store import LocalRuntimeSettingsStore

    async def scenario():
        path = write_local_model(tmp_path, 'llms/vision', 'llama-server')
        (path / 'mmproj.gguf').write_bytes(b'projector')
        supervisor = RuntimeSupervisor(tmp_path, RuntimeStore(), LocalRuntimeSettingsStore())
        manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=supervisor)
        profile = resolve_local_profile(tmp_path, ModelProfile(name='LLM', alias='llm', kind='llm', model_ref='llms/vision',
            capabilities={'vision': vision}, source={'type': 'local', 'execution_options': {'device': device}}))
        adapter = manager._managed_slot(profile).adapter
        monkeypatch.setattr(supervisor, 'executable', lambda *_: tmp_path / 'llama-server.exe')
        monkeypatch.setattr(adapters, 'probe_cuda_device', AsyncMock(return_value=('CUDA0', 'Fixture GPU')))
        monkeypatch.setattr(adapters, 'llama_environment', lambda *_: {})
        captured = []

        async def capture(args, **kwargs):
            captured.extend(map(str, args))
            raise ModelError('MODEL_UNAVAILABLE', 'captured command', 503)

        monkeypatch.setattr(ManagedProcess, 'start', capture)
        try:
            with pytest.raises(ModelError, match='captured command'):
                await adapter.load(profile, explicit=True)
            assert captured[captured.index('--model') + 1] == str(path / 'model.gguf')
            assert '--no-mmproj-auto' in captured
            assert ('--mmproj' in captured) == vision
            if vision:
                assert captured[captured.index('--mmproj') + 1] == str(path / 'mmproj.gguf')
                if device == 'cuda':
                    assert captured[captured.index('--mmproj-device') + 1] == 'CUDA0'
                else:
                    assert '--no-mmproj-offload' in captured
        finally:
            await manager.close()
            await supervisor.close()

    asyncio.run(scenario())


def test_migration_removes_obsolete_profiles_and_preserves_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.ASR_REVISION)
    preserved = write_local_model(tmp_path, "llms/gguf", "llama-server") / "model.gguf"
    files = [preserved, tmp_path / "data/attachments/kept.bin", tmp_path / "data/runtimes/local/kept.bin"]
    for path in files[1:]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    with engine.begin() as db:
        for identifier, kind, source, ref in [("old-gguf", "llm", "local", "llms/gguf/model.gguf"),
                ("old-tts", "tts", "local", "tts/speech"), ("old-vision", "vision", "local", "vision/tagger"),
                ("old-asr", "asr", None, "asr/whisper"), ("old-image", "image_embedding", None, "image_embeddings/draft"),
                ("keep", "llm", None, "remote-id"), ("keep-local", "llm", "local", "llms/transformers"),
                ("keep-asr", "asr", "local", "asr/whisper"), ("keep-image", "image_embedding", "local", "image_embeddings/model")]:
            db.execute(text("""INSERT INTO model_profiles
                (id,alias,name,kind,source_type,model_ref,capabilities_json,parameters_json,execution_options_json,lifecycle_json,
                 enabled,external_enabled,created_at,updated_at)
                VALUES (:id,:id,:id,:kind,:source,:ref,'{}','{}',:options,:lifecycle,1,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""),
                dict(id=identifier, kind=kind, source=source, ref=ref, options="{}" if source else None, lifecycle="{}" if source else None))
        db.execute(text("INSERT INTO appmetadatarecord (key,value,updated_at) VALUES ('model_settings',:value,CURRENT_TIMESTAMP)"),
            {"value": json.dumps({"default_model_profile_id": "old-gguf", "utility_model_profile_id": "keep"})})
    with Session(engine) as db:
        db.execute(text("INSERT INTO personas VALUES ('persona','Persona',NULL,'',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        db.add(RuntimeInstallationRecord(version="1.0.0", state="installed", job_id="kept-job", manifest_sha256="a" * 64))
        db.add(RuntimeJobRecord(id="kept-job", version="1.0.0", operation="install", state="completed", stage="completed"))
        db.commit()
        db.execute(text("""INSERT INTO sessionrecord (session_id,title,context_mode,current_persona_id,model_profile_id,waiting_run_id,
                context_policy_json,generation_json,harness_enabled,tools_allowed_json,title_generation_state,title_generation_metadata_json,created_at,updated_at)
                VALUES (:id,'','single_assistant',:persona,:model,:waiting,'{}','{}',0,'[]','pending','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""), {"id": "session", "persona": "persona", "model": "old-gguf", "waiting": "pending"})
        for identifier, status, model_id in [("pending", "RUNNING", "old-gguf"), ("completed", "DONE", "old-gguf"),
                                              ("unrelated", "RUNNING", "keep")]:
            db.add(RunRecord(run_id=identifier, kind="chat", persona_id="persona", session_id="session", status=status,
                config_snapshot_json=json.dumps({"model_profile_id": model_id})))
            db.add(MessageRecord(message_id=identifier, session_id="session", role="assistant", run_id=identifier))
        db.commit()
    runtime_tables = ("runtime_installations", "runtime_jobs")
    with engine.connect() as db:
        runtime_before = {table: list(db.execute(text(f"SELECT * FROM {table}")).mappings()) for table in runtime_tables}
    migrations.upgrade(engine, migrations.DIRECTORY_MODELS_REVISION)
    created = ModelProfileStore(engine).create(ModelProfile(name="New draft", alias="new-draft", kind="tts", model_ref="tts/new"))
    migrations.upgrade(engine, migrations.DIRECTORY_MODELS_REVISION)
    with engine.begin() as db:
        assert set(db.execute(text("SELECT id FROM model_profiles")).scalars()) == {"keep", "keep-local", "keep-asr", "keep-image", created.id}
        assert {table: list(db.execute(text(f"SELECT * FROM {table}")).mappings()) for table in runtime_tables} == runtime_before
        assert set(db.execute(text("SELECT run_id FROM runrecord")).scalars()) == {"completed", "unrelated"}
        assert set(db.execute(text("SELECT message_id FROM messagerecord")).scalars()) == {"completed", "unrelated"}
        assert db.execute(text("SELECT model_profile_id, waiting_run_id FROM sessionrecord")).one() == (None, None)
        settings = json.loads(db.execute(text("SELECT value FROM appmetadatarecord WHERE key = 'model_settings'")).scalar_one())
        assert settings == {"utility_model_profile_id": "keep"}
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE model_profiles SET kind = 'asr' WHERE id = 'keep'"))
    assert all(path.read_bytes() == b"fixture" for path in files)
