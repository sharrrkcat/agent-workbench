import asyncio
from contextlib import aclosing
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlmodel import Session

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes.adapters import TransformersServerAdapter
from ai_workbench.core.models.runtimes.catalog import catalog, worker_digest
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.schema import ChatChunk, ChatRequest, ModelProfile
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import KnowledgeBaseRecord, KnowledgeSettingsRecord, SessionRecord
from ai_workbench.workers.common import WorkerError, local_model
from ai_workbench.workers.transformers_engine import StopFilter
from ai_workbench.workers.transformers_server import build_app, chat_request, options_request


def profile(**values):
    return ModelProfile(**{**dict(name="Transformers", alias="transformers", kind="llm",
        runtime_id="python-worker", runtime_variant="transformers-cuda", model_ref="llms/local",
        capabilities={"streaming": True, "tools": True}), **values})


def test_family_catalog_pins_complete_windows_release_and_isolates_sources(tmp_path):
    entries = {entry.variant: entry for entry in catalog("windows", "x86_64")}
    entry = entries["transformers-cuda"]
    assert entry.supported and entry.python_version == "3.12.11"
    assert entry.python_artifact.sha256 and entry.python_key == "cpython-3.12.11-windows-x86_64-none"
    assert entry.pytorch_index_url == "https://download.pytorch.org/whl/cu128"
    assert entry.worker_entrypoint == "transformers_server.py"
    assert not {"tts_engine.py", "engines.py"} & set(entry.worker_files)
    assert "transformers_engine.py" not in entries["onnx-cpu"].worker_files
    assert not next(e for e in catalog("linux", "x86_64") if e.variant == "transformers-cuda").supported
    for name in entry.worker_files:
        (tmp_path / name).write_text(name)
    before = worker_digest(entry.worker_files, tmp_path)
    (tmp_path / "tts_engine.py").write_text("unrelated")
    assert worker_digest(entry.worker_files, tmp_path) == before
    (tmp_path / "transformers_engine.py").write_text("changed")
    assert worker_digest(entry.worker_files, tmp_path) != before


@pytest.mark.parametrize("patch", [
    {"runtime_variant": "torch-cpu"}, {"runtime_variant": "torch-cu128"},
    {"kind": "embedding"}, {"runtime_options": {"device": "auto"}},
    {"runtime_options": {"intraop_threads": True}}, {"runtime_options": {"dtype": "float16"}},
    {"capabilities": {"vision": True}}, {"capabilities": {"json_schema": True}},
    {"parameters": {"presence_penalty": 0.1}}, {"parameters": {"frequency_penalty": -0.1}},
])
def test_transformers_profile_rejects_unimplemented_combinations(patch):
    with pytest.raises(ValidationError):
        profile(**patch)


def test_alias_identity_devices_and_request_limits(tmp_path):
    supervisor = RuntimeSupervisor(tmp_path, RuntimeStore())
    manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=supervisor)
    first, alias = profile(), profile(alias="alias")
    cpu = profile(alias="cpu", runtime_options={"device": "cpu"})
    assert manager.backend_key(first) == manager.backend_key(alias)
    assert manager._key(first) == manager._key(alias)
    assert manager.backend_key(first) != manager.backend_key(cpu)
    assert first.runtime_options == {"device": "cuda", "intraop_threads": 4}
    request = ChatRequest(model=first.alias, messages=[{"role": "user", "content": "hello"}])
    manager.validate_chat(first, request)
    for values in ({"presence_penalty": 0.2}, {"frequency_penalty": -0.1},
                   {"tool_choice": "required"}, {"parallel_tool_calls": False}):
        with pytest.raises(ModelError, match="explicit tool-call controls"):
            manager.validate_chat(first, request.model_copy(update=values))


def test_local_sharded_checkpoint_requires_all_shards(tmp_path):
    path = tmp_path / "llms/model@local"
    path.mkdir(parents=True)
    (path / "config.json").write_text("{}")
    (path / "model-00001.safetensors").write_bytes(b"fixture")
    (path / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"a": "model-00001.safetensors", "b": "model-00002.safetensors"}}))
    with pytest.raises(WorkerError) as missing:
        local_model(tmp_path, "llms/model@local")
    assert missing.value.code == "MODEL_NOT_FOUND"
    (path / "model-00002.safetensors").write_bytes(b"fixture")
    assert local_model(tmp_path, "llms/model@local") == path


def test_stop_sequence_split_across_deltas_never_leaks_and_partial_suffix_flushes():
    filter_ = StopFilter(["<END>", "stop"])
    assert filter_.feed("answer <EN") == "answer "
    assert filter_.feed("D>hidden tail") == ""
    assert filter_.feed("more", final=True) == "" and filter_.stopped
    partial = StopFilter(["<END>"])
    assert partial.feed("value <E") == "value "
    assert partial.feed(final=True) == "<E"


def test_private_server_authentication_and_local_text_boundary():
    calls = []

    class Engine:
        metadata = {"protocol_version": 1, "device_name": "CPU", "tool_calls": True}
        closed = False

        async def chat(self, body, request_id):
            calls.append(body)
            return JSONResponse({"accepted": request_id})

        def close(self):
            self.closed = True

    engine = Engine()
    with TestClient(build_app(engine, "test-token")) as client:
        assert client.get("/health").status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        assert client.get("/v1/models", headers=headers).json()["data"][0]["id"] == "managed"
        base = {"model": "managed", "messages": [{"role": "user", "content": "hello"}]}
        assert client.post("/v1/chat/completions", headers=headers, json=base).status_code == 200
        for patch in ({"model": "another/local/path"}, {"response_format": {"type": "json_object"}},
                      {"tool_choice": "required"}, {"parallel_tool_calls": True}, {"presence_penalty": 1},
                      {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.test/image"}}]}]}):
            assert client.post("/v1/chat/completions", headers=headers, json={**base, **patch}).status_code == 422
        assert len(calls) == 1
        assert client.post("/load_model", headers=headers, json={"model": "remote/name"}).status_code == 404
    assert engine.closed
    assert options_request({"device": "cpu", "intraop_threads": 4})["device"] == "cpu"
    assert "frequency_penalty" not in chat_request({**base, "frequency_penalty": 0})


def test_transformers_stream_closure_stops_process_before_returning():
    async def scenario():
        entry = next(e for e in catalog("windows", "x86_64") if e.variant == "transformers-cuda")
        adapter = TransformersServerAdapter(SimpleNamespace(entry=lambda *_: entry), profile(), lambda: None)
        stopped = asyncio.Event()
        adapter._stop = AsyncMock(side_effect=lambda: stopped.set())
        adapter.tool_calls_supported = True

        class Upstream:
            async def chat_stream(self, *_):
                yield ChatChunk(delta={"content": "partial"})
                await asyncio.Event().wait()

        adapter.openai = Upstream()
        request = ChatRequest(model="transformers", messages=[{"role": "user", "content": "hello"}], stream=True)
        async with aclosing(adapter.chat_stream(profile(), request)) as stream:
            assert (await anext(stream)).delta.content == "partial"
        assert stopped.is_set()
        adapter._stop.assert_awaited_once()
    asyncio.run(scenario())


def test_runtime_migration_discards_only_excluded_configuration_and_preserves_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.TTS_REVISION)
    profiles = ModelProfileStore(engine)
    removed = profiles.create(ModelProfile(name="Old", alias="old", kind="embedding", model_ref="embeddings/old"))
    kept = profiles.create(ModelProfile(name="Kept", alias="kept", kind="llm", model_ref="external"))
    settings = ModelSettingsStore(engine)
    settings.patch({"default_model_profile_id": removed.id, "utility_model_profile_id": kept.id})
    with Session(engine) as db:
        db.add(KnowledgeBaseRecord(id="old-base", name="Old", embedding_model_profile_id=removed.id))
        db.add(KnowledgeSettingsRecord(id=1, reranker_model_profile_id=removed.id))
        db.add(SessionRecord(session_id="session", current_persona_id="00000000-0000-4000-8000-000000000001",
                             model_profile_id=removed.id, context_policy_json='{"mode":"session"}'))
        db.exec(text("UPDATE model_profiles SET runtime_id='python-worker',runtime_variant='torch-cpu' WHERE id=:id").bindparams(id=removed.id))
        db.commit()
    protected = []
    for directory in ("models", "attachments", "runtimes"):
        path = tmp_path / "data" / directory / "keep.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"protected")
        protected.append((path, path.stat().st_mtime_ns))
    migrations.upgrade(engine)
    assert [p.id for p in profiles.list()] == [kept.id]
    assert settings.get().default_model_profile_id is None and settings.get().utility_model_profile_id == kept.id
    with Session(engine) as db:
        assert db.get(KnowledgeBaseRecord, "old-base") is None
        assert db.get(KnowledgeSettingsRecord, 1).reranker_model_profile_id is None
        assert db.get(SessionRecord, "session").model_profile_id is None
    assert all(path.read_bytes() == b"protected" and path.stat().st_mtime_ns == stamp for path, stamp in protected)
    migrations.upgrade(engine)
    assert profiles.get(kept.id).alias == "kept"
    engine.dispose()
