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
from ai_workbench.core.models.runtimes.catalog import catalog
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.schema import ChatChunk, ChatRequest, ModelProfile
from ai_workbench.core.models.store import LocalRuntimeSettingsStore, ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import KnowledgeBaseRecord, KnowledgeSettingsRecord, SessionRecord
from ai_workbench.workers.common import WorkerError, local_model
from ai_workbench.workers.transformers_engine import StopFilter
from ai_workbench.workers.transformers_server import build_app, chat_request, options_request
from tests.model_fixtures import resolve_local_profile, write_local_model


def profile(**values):
    return ModelProfile(**{**dict(name='Transformers', alias='transformers', kind='llm', model_ref='llms/local', capabilities={'streaming': True, 'tools': True}, source={'type': 'local'}), **values})


@pytest.mark.parametrize("patch", [
    {"runtime_variant": "torch-cpu"}, {"runtime_variant": "torch-cu128"},
    {"kind": "embedding"}, {"source": {"type": "local", "execution_options": {"device": "auto"}}},
    {"source": {"type": "local", "execution_options": {"intraop_threads": True}}},
    {"source": {"type": "local", "execution_options": {"dtype": "float16"}}},
    {"capabilities": {"json_schema": True}},
    {"parameters": {"presence_penalty": 0.1}}, {"parameters": {"frequency_penalty": -0.1}},
])
def test_transformers_profile_rejects_unimplemented_combinations(tmp_path, patch):
    write_local_model(tmp_path, "llms/local", "transformers")
    with pytest.raises((ValidationError, ModelError)):
        resolve_local_profile(tmp_path, profile(**patch))


def test_alias_identity_devices_and_request_limits(tmp_path):
    write_local_model(tmp_path, "llms/local", "transformers")
    supervisor = RuntimeSupervisor(tmp_path, RuntimeStore(), LocalRuntimeSettingsStore())
    manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=supervisor)
    first, alias = resolve_local_profile(tmp_path, profile()), profile(alias="alias")
    cpu = profile(alias="cpu", source={"type": "local", "execution_options": {"device": "cpu"}})
    assert manager.execution_key(first) == manager.execution_key(alias)
    assert manager._key(first) == manager._key(alias)
    assert manager.execution_key(first) != manager.execution_key(cpu)
    assert first.source.execution_options == {"device": "cuda", "intraop_threads": 4}
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
        metadata = {"protocol_version": 1, "device_name": "CPU", "tool_calls": True, "vision": False}
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
        assert client.get("/v1/models", headers=headers).json()["data"] == [
            {"id": "managed", "object": "model", "owned_by": "cogita"}]
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


def test_transformers_stream_closure_stops_process_before_returning(tmp_path):
    write_local_model(tmp_path, "llms/local", "transformers")
    async def scenario():
        entry = catalog("windows", "x86_64")
        adapter = TransformersServerAdapter(SimpleNamespace(root=tmp_path, release=entry), profile(), lambda: None)
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
