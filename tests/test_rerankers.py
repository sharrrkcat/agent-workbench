"""CrossEncoder metadata, schemas and native processing without inference dependencies."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import text

from ai_workbench.api.main import create_app
from ai_workbench.core.models.inspection import inspect_reranker
from ai_workbench.core.models.inventory import inventory
from ai_workbench.core.models.schema import ModelProfile, RerankRequest
from ai_workbench.core.models.store import ModelProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.workers import reranker_engine
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers.reranker_catalog import load_configuration
from ai_workbench.workers.reranker_server import RerankerWorker
from tests.test_text_embeddings import write_json

REF = "rerankers/representative-pair-model"
OPTIONS = {"device": "cuda", "intraop_threads": 4, "max_batch_size": 1}


def model_tree(root, *, model_type="future-backbone", kind="logit", nested=False, tokens=(7, 3), ref=REF):
    path = root / "data/models" / ref
    path.mkdir(parents=True, exist_ok=True)
    backbone = path / "0_Transformer" if nested else path
    config = {"model_type": model_type, "max_position_embeddings": 64, "vocab_size": 128,
              "architectures": ["ArbitraryForCausalLM" if kind == "logit" else "ArbitraryForSequenceClassification"]}
    if kind != "logit":
        config["id2label"] = {"0": "relevance"}
    write_json(backbone / "config.json", config)
    write_json(backbone / "tokenizer_config.json", {"model_max_length": 10**30})
    (backbone / "model.safetensors").write_bytes(b"synthetic checkpoint")
    write_json(path / "config_sentence_transformers.json", {"model_type": "CrossEncoder", "prompts": {}, "default_prompt_name": None})
    if kind == "plain":
        return path
    modules = [{"idx": 0, "name": "0", "path": "0_Transformer" if nested else "",
                "type": "sentence_transformers.base.modules.transformer.Transformer"}]
    write_json(backbone / "sentence_bert_config.json", {"transformer_task": "text-generation" if kind == "logit" else "sequence-classification"})
    if kind == "logit":
        (backbone / "chat_template.jinja").write_text("query: {{ messages[0].content }} document: {{ messages[1].content }}", encoding="utf-8")
        modules.append({"idx": 1, "name": "1", "path": "1_Score",
                        "type": "sentence_transformers.cross_encoder.modules.logit_score.LogitScore"})
        write_json(path / "1_Score/config.json", {"true_token_id": tokens[0], "false_token_id": tokens[1]})
    write_json(path / "modules.json", modules)
    return path


def profile(**values):
    return ModelProfile(**{"name": "Reranker", "alias": "rerank", "kind": "reranker", "model_ref": REF,
        "source": {"type": "local"}, "external_enabled": True, **values})


@pytest.mark.parametrize("kind,model_type,nested,tokens", [
    ("logit", "qwen2", False, (16, 15)), ("logit", "future-backbone", True, (27, None)),
    ("classification", "bert", True, (7, 3)), ("plain", "another-backbone", False, (7, 3)),
])
def test_native_metadata_is_independent_of_checkpoint_backbone_and_tokens(tmp_path, kind, model_type, nested, tokens):
    path = model_tree(tmp_path, kind=kind, model_type=model_type, nested=nested, tokens=tokens)
    information = inspect_reranker(tmp_path, REF)
    assert not information.diagnostics
    assert information.architecture == "cross-encoder" and information.model_type == model_type
    assert information.scoring.method == ("logit_score" if kind == "logit" else "sequence_classification")
    assert information.scoring.activation.endswith("Sigmoid") and information.max_seq_length == 64
    assert information.has_chat_template == (kind == "logit")
    assert [item["model_ref"] for item in inventory(tmp_path, "reranker")] == [REF]
    assert load_configuration(tmp_path / "data/models", REF)[0] == path


def test_single_score_projection_and_declared_native_activation(tmp_path):
    path = model_tree(tmp_path, kind="classification")
    write_json(path / "sentence_bert_config.json", {"transformer_task": "feature-extraction"})
    modules = json.loads((path / "modules.json").read_text())
    for name in ("Pooling", "Dense"):
        modules.append({"idx": len(modules), "name": name, "path": name, "type": "sentence_transformers.models." + name})
    write_json(path / "modules.json", modules)
    write_json(path / "Pooling/config.json", {"pooling_mode": "cls", "word_embedding_dimension": 8})
    write_json(path / "Dense/config.json", {"in_features": 8, "out_features": 1, "module_output_name": "scores"})
    write_json(path / "config_sentence_transformers.json", {"model_type": "CrossEncoder", "activation_fn": "torch.nn.Identity"})
    information = inspect_reranker(tmp_path, REF)
    assert not information.diagnostics and information.scoring.method == "dense"
    assert information.scoring.activation == "torch.nn.Identity"


def test_native_processing_limit_precedence_and_embedded_template(tmp_path):
    path = model_tree(tmp_path)
    (path / "chat_template.jinja").unlink()
    write_json(path / "sentence_bert_config.json", {"transformer_task": "text-generation",
        "processor_kwargs": {"chat_template": "query: {{ messages[0].content }} document: {{ messages[1].content }}"},
        "processing_kwargs": {"common": {"max_length": 16}, "text": {"max_length": 32}}})
    information = inspect_reranker(tmp_path, REF)
    assert not information.diagnostics and information.max_seq_length == 32 and information.has_chat_template


def test_inventory_inspection_and_resource_validation_never_read_or_hash_weights(tmp_path, monkeypatch):
    model_tree(tmp_path, nested=True)
    original = Path.open
    def config_only(path, *args, **kwargs):
        assert path.suffix in {".json", ".jinja"}, f"Unexpected model content read: {path}"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", config_only)
    monkeypatch.setattr(hashlib, "sha256", lambda *_args, **_kwargs: pytest.fail("Model hashes are forbidden"))
    assert not inspect_reranker(tmp_path, REF).diagnostics
    assert len(inventory(tmp_path, "reranker")) == 1
    assert load_configuration(tmp_path / "data/models", REF)[1]["scoring"]["method"] == "logit_score"
    assert not {"torch", "transformers", "sentence_transformers"} & sys.modules.keys()


@pytest.mark.parametrize("mutation,code", [
    (lambda path: (path / "modules.json").unlink(), "missing_scoring"),
    (lambda path: write_json(path / "1_Score/config.json", {}), "missing_scoring"),
    (lambda path: write_json(path / "1_Score/config.json", {"true_token_id": 200}), "missing_scoring"),
    (lambda path: (path / "chat_template.jinja").unlink(), "missing_template"),
    (lambda path: write_json(path / "modules.json", []), "unsupported_configuration"),
    (lambda path: write_json(path / "config_sentence_transformers.json", {"model_type": "MultiVectorEncoder"}), "unsupported_configuration"),
    (lambda path: write_json(path / "config_sentence_transformers.json", {"activation_fn": "custom.Score"}), "remote_code"),
    (lambda path: write_json(path / "config_sentence_transformers.json", {"activation_fn": False}), "remote_code"),
    (lambda path: write_json(path / "sentence_bert_config.json", {"transformer_task": "retrieval"}), "unsupported_configuration"),
    (lambda path: write_json(path / "sentence_bert_config.json", {"transformer_task": "text-generation", "processing_kwargs": {"text": {"max_length": 128}}}), "unsupported_configuration"),
    (lambda path: write_json(path / "config.json", {"model_type": "another-model", "architectures": ["AnotherForCausalLM"]}), "missing_token_limit"),
])
def test_incomplete_or_unsupported_semantics_fail_before_engine_creation(tmp_path, mutation, code):
    path = model_tree(tmp_path)
    mutation(path)
    assert code in {item.code for item in inspect_reranker(tmp_path, REF).diagnostics}
    worker = RerankerWorker(tmp_path / "data/models", lambda *_args: pytest.fail("Invalid metadata must not create an engine"))
    with pytest.raises(WorkerError, match="UNSUPPORTED_CAPABILITY"):
        worker.dispatch("/load", {"profile_id": "fixture", "kind": "reranker", "model_ref": REF, "parameters": {}, "options": OPTIONS})


def test_multiclass_scores_are_not_reinterpreted_as_relevance(tmp_path):
    path = model_tree(tmp_path, kind="plain")
    config = json.loads((path / "config.json").read_text())
    write_json(path / "config.json", {**config, "id2label": {"0": "negative", "1": "positive"}})
    with pytest.raises(WorkerError, match="UNSUPPORTED_CAPABILITY"):
        load_configuration(tmp_path / "data/models", REF)


@pytest.mark.parametrize("reference", ["../escape", "/absolute", "rerankers/../escape", "C:/outside", "rerankers\\outside"])
def test_unsafe_references_are_rejected(tmp_path, reference):
    with pytest.raises(WorkerError, match="INVALID_REQUEST"):
        load_configuration(tmp_path / "data/models", reference)


def test_module_paths_and_checkpoint_shards_stay_inside_package(tmp_path):
    path = model_tree(tmp_path)
    modules = json.loads((path / "modules.json").read_text())
    modules[1]["path"] = "../outside"
    write_json(path / "modules.json", modules)
    with pytest.raises(WorkerError, match="INVALID_REQUEST"):
        load_configuration(tmp_path / "data/models", REF)
    model_tree(tmp_path)
    write_json(path / "model.safetensors.index.json", {"weight_map": {"weight": "../outside.safetensors"}})
    with pytest.raises(WorkerError):
        load_configuration(tmp_path / "data/models", REF)


@pytest.mark.parametrize("memory", [True, False])
def test_profiles_inspection_and_invalid_directory_drafts(tmp_path, memory):
    model_tree(tmp_path)
    with TestClient(create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'app.db'}")) as client:
        response = client.post("/api/models/profiles", json=profile().model_dump(mode="json", exclude={"id", "created_at", "updated_at"}))
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["parameters"] == {} and saved["source"]["execution_options"] == OPTIONS
        assert saved["source"]["lifecycle"]["unload"] == "manual"
        result = client.get("/api/models/inspect", params={"kind": "reranker", "model_ref": REF})
        assert result.status_code == 200 and result.json()["architecture"] == "cross-encoder"
        assert client.get("/api/models/inspect", params={"kind": "reranker", "model_ref": REF, "query_prompt_name": "query"}).status_code == 422
        route = "/api/models/profiles/" + saved["id"]
        assert client.patch(route, json={"model_ref": "rerankers/not-present"}).status_code == 200
        assert client.patch(route, json={"source": None}).json()["source"] is None
        for patch in ({"parameters": {"batch_size": 16}}, {"parameters": {"architecture": "qwen2"}},
                {"source": {"type": "local", "execution_options": {"max_batch_size": 17}}},
                {"source": {"type": "provider", "provider_profile_id": "missing"}}):
            assert client.patch(route, json=patch).status_code == 422


@pytest.mark.parametrize("patch", [{"query": " "}, {"documents": []}, {"documents": [" "]},
    {"documents": [1]}, {"documents": [{"text": "x"}]}, {"documents": ["x"] * 2049},
    {"top_n": 0}, {"top_n": True}, {"top_n": 1.5}, {"return_documents": "true"}, {"stream": False}])
def test_request_boundary_is_strict(patch):
    with pytest.raises(ValidationError):
        RerankRequest.model_validate({"model": "rerank", "query": "query", "documents": ["text"], **patch})


def test_engine_preserves_native_pairs_scores_activation_and_device(tmp_path, monkeypatch):
    path = model_tree(tmp_path)
    information = inspect_reranker(tmp_path, REF).model_dump()
    calls, valid = [], {"shape": (2,), "finite": True}
    class Tensor:
        @property
        def shape(self): return valid["shape"]
        def float(self): return self
        def cpu(self): return self
        def tolist(self): return [-2.5, 7.0]
    class Native:
        dtype, num_labels = "native", 1
        def __init__(self, directory, **kwargs): calls.append((directory, kwargs))
        def eval(self): pass
        def predict(self, pairs, **kwargs):
            calls.append((pairs, kwargs))
            return Tensor()
    torch = SimpleNamespace(float32="float32", set_num_threads=lambda _: None, inference_mode=nullcontext,
        isfinite=lambda _: SimpleNamespace(all=lambda: SimpleNamespace(item=lambda: valid["finite"])),
        cuda=SimpleNamespace(is_available=lambda: True, get_device_name=lambda _: "Fixture CUDA"))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=Native))
    monkeypatch.setattr(reranker_engine, "require_offline", lambda: calls.append("offline"))
    for device, dtype in (("cuda", "auto"), ("cpu", "float32")):
        engine = reranker_engine.RerankerEngine(path, {**OPTIONS, "device": device, "max_batch_size": 3}, information)
        constructor = calls[-1][1]
        assert constructor["local_files_only"] and constructor["trust_remote_code"] is False
        assert constructor["model_kwargs"]["dtype"] == dtype and engine.model.max_seq_length == 64
        assert engine.rerank("query", [" first ", "second"]) == {"scores": [-2.5, 7.0]}
        assert calls[-1] == ([("query", " first "), ("query", "second")],
            {"batch_size": 3, "show_progress_bar": False, "convert_to_tensor": True})
        for shape, finite in (((2, 2), True), ((1,), True), ((2,), False)):
            valid.update(shape=shape, finite=finite)
            with pytest.raises(WorkerError, match="MODEL_UNAVAILABLE"):
                engine.rerank("query", ["first", "second"])
        valid.update(shape=(2,), finite=True)
    torch.cuda.is_available = lambda: False
    with pytest.raises(WorkerError, match="RUNTIME_DEVICE_UNAVAILABLE"):
        reranker_engine.RerankerEngine(path, OPTIONS, information)


def test_migration_resets_only_abandoned_parameters_and_preserves_model_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.TEXT_EMBEDDING_REVISION)
    saved = ModelProfileStore(engine).create(profile(source=None))
    with engine.begin() as database:
        database.execute(text("UPDATE model_profiles SET parameters_json = :value WHERE id = :id"),
            {"value": '{"batch_size": 64}', "id": saved.id})
    files = [tmp_path / name for name in ("data/models/sentinel", "data/attachments/sentinel", "data/runtimes/sentinel")]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preserve")
    init_db(engine)
    init_db(engine)
    restored = ModelProfileStore(engine).get(saved.id)
    assert restored.parameters == {} and restored.alias == saved.alias and restored.source is None
    assert migrations.current_revision(engine) == migrations.RERANKER_REVISION
    assert ModelProfileStore(engine).create(profile(alias="local")).source.type == "local"
    assert all(path.read_bytes() == b"preserve" for path in files)
    engine.dispose()
