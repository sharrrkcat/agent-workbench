"""Text embedding metadata and boundaries without installed inference dependencies."""
import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import sys

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from ai_workbench.api.main import create_app
from ai_workbench.core.models.inspection import inspect_text_embedding
from ai_workbench.core.models.inventory import inventory
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import ModelProfileStore, ProviderProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.workers import embedding_engine
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers.embedding_catalog import inspect_embedding, load_configuration
from ai_workbench.workers.embedding_server import EmbeddingWorker

REF = "embeddings/configured-model"
PARAMETERS = {"query_prompt_name": None, "document_prompt_name": None}
OPTIONS = {"device": "cuda", "intraop_threads": 4, "max_batch_size": 1}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def model_tree(root, *, model_type="unrestricted-backbone", pooling="lasttoken", dimensions=2, nested=False, normalize=True, dense=None):
    path = root / "data/models" / REF
    path.mkdir(parents=True, exist_ok=True)
    backbone = path / "0_Backbone" if nested else path
    write_json(backbone / "config.json", {"model_type": model_type, "hidden_size": dimensions, "max_position_embeddings": 32})
    write_json(backbone / "tokenizer_config.json", {"model_max_length": 10**30})
    (backbone / "model.safetensors").write_bytes(b"disposable synthetic weights")
    write_json(path / "config_sentence_transformers.json", {"prompts": {
        "web_search_query": "Retrieve documents: ", "sts_query": "Similar text: "}, "similarity_fn_name": "cosine"})
    modules = [{"idx": 0, "name": "backbone", "path": "0_Backbone" if nested else "",
                "type": "sentence_transformers.models.Transformer"},
               {"idx": 1, "name": "pool", "path": "1_Pooling", "type": "sentence_transformers.models.Pooling"}]
    write_json(path / "1_Pooling/config.json", {"embedding_dimension": dimensions, "pooling_mode": pooling, "include_prompt": False})
    if dense:
        modules.append({"idx": len(modules), "name": "projection", "path": "projection", "type": "sentence_transformers.models.Dense"})
        write_json(path / "projection/config.json", {"in_features": dimensions, "out_features": dense})
    if normalize:
        modules.append({"idx": len(modules), "name": "normalize", "path": "normalize", "type": "sentence_transformers.models.Normalize"})
    write_json(path / "modules.json", modules)
    return path


def profile(**values):
    return ModelProfile(**{"name": "Embedding", "alias": "embed", "kind": "embedding", "model_ref": REF,
        "source": {"type": "local"}, "external_enabled": True, **values})


@pytest.mark.parametrize("model_type,pooling,dimensions,nested,dense,normalize", [
    ("bert", "cls", 3, True, 5, True),
    ("qwen3", "lasttoken", 7, False, None, True),
    ("future-backbone", ["mean", "max"], 4, True, None, False),
])
def test_metadata_is_not_bound_to_a_checkpoint_or_backbone(tmp_path, model_type, pooling, dimensions, nested, dense, normalize):
    path = model_tree(tmp_path, model_type=model_type, pooling=pooling, dimensions=dimensions, nested=nested, dense=dense, normalize=normalize)
    result = inspect_text_embedding(tmp_path, REF)
    assert result.model_type == model_type and not result.diagnostics
    assert result.dimensions == (dense or dimensions * (len(pooling) if isinstance(pooling, list) else 1))
    assert result.max_seq_length == 32 and result.normalize == normalize
    assert result.query_prompt_name == "web_search_query" and result.document_prompt_name is None
    assert result.pooling[0].include_prompt is False
    assert [item["model_ref"] for item in inventory(tmp_path, "embedding")] == [REF]
    assert not (path / "normalize").exists()
    assert load_configuration(tmp_path / "data/models", REF, PARAMETERS)[0] == path


def test_inspection_reads_only_json_and_never_hashes_model_contents(tmp_path, monkeypatch):
    model_tree(tmp_path)
    original = Path.open
    def open_file(path, *args, **kwargs):
        assert path.suffix == ".json", f"Inspection opened non-configuration file: {path}"
        return original(path, *args, **kwargs)
    def hash_model(*args, **kwargs):
        pytest.fail("Embedding metadata must not calculate a model hash")
    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(hashlib, "sha256", hash_model)
    assert inspect_text_embedding(tmp_path, REF).dimensions == 2
    assert len(inventory(tmp_path, "embedding")) == 1
    assert not {"torch", "transformers", "sentence_transformers"} & sys.modules.keys()


def test_native_pooling_flags_and_effective_text_limit(tmp_path):
    path = model_tree(tmp_path)
    write_json(path / "1_Pooling/config.json", {"word_embedding_dimension": 2,
        "pooling_mode_lasttoken": True, "pooling_mode_mean_tokens": False})
    write_json(path / "sentence_bert_config.json", {"max_seq_length": 19})
    information = inspect_text_embedding(tmp_path, REF)
    assert information.max_seq_length == 19
    assert information.pooling[0].modes == ["lasttoken"]
    assert information.pooling[0].include_prompt is True


def test_native_transformer_metadata_limits_and_truncated_normalization(tmp_path):
    path = model_tree(tmp_path, dimensions=4)
    write_json(path / "sentence_roberta_config.json", {"max_seq_length": 24,
        "processing_kwargs": {"text": {"max_length": 16}}, "query_length": 12})
    write_json(path / "config_sentence_transformers.json", {"truncate_dim": 2})
    info = inspect_text_embedding(tmp_path, REF)
    assert info.max_seq_length == 16 and info.dimensions == 2 and info.normalize is False
    assert not info.diagnostics
    write_json(path / "sentence_roberta_config.json", {"processing_kwargs": {"text": {"max_length": 100}}})
    assert inspect_text_embedding(tmp_path, REF).diagnostics[0].code == "unsupported_configuration"


@pytest.mark.parametrize("mutation,code", [
    ("missing_pipeline", "missing_pipeline"), ("missing_pool", "missing_config"),
    ("default_pool", "missing_pooling"), ("unknown_pool", "unsupported_configuration"),
    ("bad_json", "invalid_config"), ("remote_code", "remote_code"),
    ("unsupported_similarity", "unsupported_configuration"), ("bad_limit", "invalid_field"),
    ("unknown_module", "unsupported_configuration"),
])
def test_incomplete_semantics_fail_before_engine_creation(tmp_path, mutation, code):
    path = model_tree(tmp_path)
    if mutation == "missing_pipeline":
        (path / "modules.json").unlink()
    elif mutation == "missing_pool":
        (path / "1_Pooling/config.json").unlink()
    elif mutation == "default_pool":
        write_json(path / "1_Pooling/config.json", {"embedding_dimension": 2})
    elif mutation == "unknown_pool":
        write_json(path / "1_Pooling/config.json", {"embedding_dimension": 2, "pooling_mode": "invented"})
    elif mutation == "bad_json":
        (path / "config.json").write_text("broken", encoding="utf-8")
    elif mutation == "remote_code":
        write_json(path / "modules.json", [{"name": "custom", "type": "custom.Model", "path": ""}])
    elif mutation == "unsupported_similarity":
        write_json(path / "config_sentence_transformers.json", {"similarity_fn_name": ["dot"]})
    elif mutation == "unknown_module":
        write_json(path / "modules.json", [{"name": "unknown", "type": "sentence_transformers.models.Uninterpreted", "path": ""}])
    else:
        write_json(path / "tokenizer_config.json", {"model_max_length": "32"})
    assert code in {item.code for item in inspect_text_embedding(tmp_path, REF).diagnostics}
    worker = EmbeddingWorker(tmp_path / "data/models", engine_factory=lambda *_: pytest.fail("Invalid metadata loaded weights"))
    with pytest.raises(WorkerError) as caught:
        worker.dispatch("/load", {"profile_id": "test", "kind": "embedding", "model_ref": REF,
                                  "parameters": PARAMETERS, "options": OPTIONS})
    assert caught.value.code == "UNSUPPORTED_CAPABILITY"


def test_prompt_resolution_and_explicit_named_selection(tmp_path):
    path = model_tree(tmp_path)
    prompts = {"sts_query": "Similar: ", "bitext_query": "Parallel: "}
    write_json(path / "config_sentence_transformers.json", {"prompts": prompts})
    assert inspect_text_embedding(tmp_path, REF).diagnostics[0].code == "ambiguous_prompt"
    information = inspect_text_embedding(tmp_path, REF, {**PARAMETERS, "query_prompt_name": "sts_query"})
    assert information.query_prompt_name == "sts_query" and not information.diagnostics
    assert inspect_text_embedding(tmp_path, REF, {**PARAMETERS, "query_prompt_name": "missing"}).diagnostics[0].code == "invalid_prompt"
    write_json(path / "config_sentence_transformers.json", {"prompts": {
        **prompts, "query": "Query: ", "web_search_query": "Search: ", "passage": "Passage: "}})
    information = inspect_text_embedding(tmp_path, REF)
    assert (information.query_prompt_name, information.document_prompt_name) == ("query", "passage")


@pytest.mark.parametrize("reference", ["../outside", "/absolute", "C:/models", "embeddings\\model"])
def test_unsafe_references_are_rejected(tmp_path, reference):
    with pytest.raises(WorkerError):
        inspect_embedding(tmp_path, reference)


def test_module_paths_and_index_shards_stay_inside_the_package(tmp_path):
    path = model_tree(tmp_path)
    write_json(path / "model.safetensors.index.json", {"weight_map": {"weight": "../outside.safetensors"}})
    with pytest.raises(WorkerError):
        load_configuration(tmp_path / "data/models", REF, PARAMETERS)
    write_json(path / "modules.json", [{"name": "escape", "path": "../other", "type": "sentence_transformers.models.Transformer"}])
    with pytest.raises(WorkerError):
        inspect_embedding(tmp_path / "data/models", REF)


@pytest.mark.parametrize("memory", [True, False])
def test_local_profile_inspection_and_unbound_drafts(tmp_path, memory):
    model_tree(tmp_path)
    with TestClient(create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'test.db'}")) as client:
        body = profile().model_dump(exclude={"id", "created_at", "updated_at"})
        response = client.post("/api/models/profiles", json=body)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["parameters"] == PARAMETERS
        assert saved["source"]["execution_options"] == OPTIONS
        endpoint = "/api/models/profiles/" + saved["id"]
        for parameters in ({"dimensions": 2}, {"normalize": False}, {"batch_size": 2}, {"query_instruction": "text"}, {"query_prompt_name": 2}):
            assert client.patch(endpoint, json={"parameters": parameters}).status_code == 422
        for size in (0, 17, True):
            assert client.patch(endpoint, json={"source": {"type": "local", "execution_options": {"max_batch_size": size}}}).status_code == 422
        information = client.get("/api/models/inspect", params={"kind": "embedding", "model_ref": REF}).json()
        assert information["dimensions"] == 2 and information["query_prompt_name"] == "web_search_query"
        changed = client.get("/api/models/inspect", params={"kind": "embedding", "model_ref": REF, "query_prompt_name": "sts_query"})
        assert changed.json()["query_prompt_name"] == "sts_query"
        assert client.get("/api/models/inspect", params={"kind": "embedding", "model_ref": "../outside"}).status_code == 422
        assert client.get("/api/models/inspect", params={"kind": "embedding", "model_ref": "embeddings/missing"}).status_code == 404
        assert client.patch(endpoint, json={"source": None}).json()["source"] is None
        assert client.post(endpoint + "/load").json()["error"]["code"] == "MODEL_NOT_CONFIGURED"
        assert client.patch(endpoint, json={"source": {"type": "local"}, "model_ref": "embeddings/incomplete"}).status_code == 200


def test_engine_uses_native_pipeline_offline_dtype_prompts_and_dimensions(tmp_path, monkeypatch):
    path = model_tree(tmp_path)
    info = inspect_embedding(tmp_path / "data/models", REF)
    calls = []
    class Check:
        def __init__(self, value): self.value = value
        def all(self): return self
        def any(self): return self
        def item(self): return self.value
        def __eq__(self, other): return Check(self.value == other)
    class Tensor:
        ndim, shape = 2, (1, 2)
        def float(self): return self
        def cpu(self): return self
        def norm(self, dim): return Check(1)
        def tolist(self): return [[0.6, 0.8]]
    class Native:
        dtype = "native"
        def __init__(self, directory, **kwargs): calls.append((directory, kwargs))
        def eval(self): pass
        def get_embedding_dimension(self): return 2
        def encode(self, values, **kwargs):
            calls.append((values, kwargs))
            return Tensor()
    torch = SimpleNamespace(float32="float32", set_num_threads=lambda _: None,
        inference_mode=nullcontext, isfinite=lambda _: Check(True),
        cuda=SimpleNamespace(is_available=lambda: True, get_device_name=lambda _: "Fixture CUDA"))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=Native))
    monkeypatch.setattr(embedding_engine, "require_offline", lambda: calls.append("offline"))
    for device, dtype in (("cuda", "auto"), ("cpu", "float32")):
        engine = embedding_engine.EmbeddingEngine(path, {**OPTIONS, "device": device}, info)
        constructor = calls[-1][1]
        assert constructor["local_files_only"] is True and constructor["trust_remote_code"] is False
        assert constructor["model_kwargs"]["dtype"] == dtype and engine.model.max_seq_length == 32
        result = engine.embed(["unchanged text"], "query", 2)
        assert result == {"vectors": [[0.6, 0.8]], "similarity": "cosine"}
        assert calls[-1][0] == ["unchanged text"]
        assert calls[-1][1]["prompt"] == "Retrieve documents: " and calls[-1][1]["task"] == "query"
        assert calls[-1][1]["normalize_embeddings"] is False
        engine.embed(["document"], "document", None)
        assert calls[-1][1]["prompt"] == ""
        with pytest.raises(WorkerError, match="EMBEDDING_DIMENSION_MISMATCH"):
            engine.embed(["text"], "document", 3)
    torch.cuda.is_available = lambda: False
    with pytest.raises(WorkerError, match="RUNTIME_DEVICE_UNAVAILABLE"):
        embedding_engine.EmbeddingEngine(path, OPTIONS, info)


def test_migration_preserves_rows_indexes_and_files(tmp_path):
    from ai_workbench.core.models.schema import ProviderProfile
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.SIGLIP_REVISION)
    provider = ProviderProfileStore(engine).create(ProviderProfile(name="Provider", connection={"base_url": "https://provider.test/v1"}))
    original = ModelProfileStore(engine).create(profile(source={"type": "provider", "provider_profile_id": provider.id}))
    before = ModelProfileStore(engine).get(original.id).model_dump()
    with engine.begin() as db:
        db.execute(text("INSERT INTO kb_embeddings (id, knowledge_base_id, source_id, chunk_id, embedding_model_profile_id, embedding_model_id_snapshot, embedding_dimension, embedding_normalize_snapshot, vector_blob, created_at) VALUES ('vector', 'base', 'source', 'chunk', :model, 'provider-model', 2, 1, :vector, '2026-09-24')"), {"model": original.id, "vector": b"preserved-vector"})
    paths = [tmp_path / name for name in ("data/models/sentinel", "data/attachments/sentinel", "data/runtimes/sentinel")]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preserve")
    init_db(engine)
    init_db(engine)
    assert migrations.current_revision(engine) == migrations.HEAD_REVISION
    assert ModelProfileStore(engine).get(original.id).model_dump() == before
    assert ProviderProfileStore(engine).get(provider.id).name == "Provider"
    local = ModelProfileStore(engine).create(profile(alias="local"))
    init_db(engine)
    assert ModelProfileStore(engine).get(local.id).source.type == "local"
    with engine.connect() as db:
        assert db.execute(text("SELECT vector_blob FROM kb_embeddings WHERE id='vector'")).scalar_one() == b"preserved-vector"
        assert "embedding_normalize_snapshot" not in {row[1] for row in db.exec_driver_sql("PRAGMA table_info(kb_embeddings)")}
    assert all(path.read_bytes() == b"preserve" for path in paths)
    engine.dispose()
