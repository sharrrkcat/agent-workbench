"""SigLIP information, identity and single-tower behavior without inference libraries."""
import asyncio
import base64
from contextlib import nullcontext
from io import BytesIO
import json
import math
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
import pytest

from ai_workbench.api.main import create_app
from ai_workbench.core.models import siglip
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.images import prepare_embedding_images, prepare_tagging_images
from ai_workbench.core.models.inspection import inspect_siglip
from ai_workbench.core.models.inventory import inventory
from ai_workbench.core.models.siglip import SiglipModelUse, model_revision
from ai_workbench.core.models.runtimes.schema import SiglipOptions
from ai_workbench.core.models.schema import InferenceTiming
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers import siglip_engine
from ai_workbench.workers.siglip_catalog import model_files
from ai_workbench.workers.siglip_server import SiglipWorker
from tests.test_wd14 import data_url

REF = "image_embeddings/family-fixture"


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def model_tree(root, model_type="siglip2", *, sharded=False):
    path = root / "data/models" / REF
    path.mkdir(parents=True)
    write_json(path / "config.json", {"model_type": model_type,
        "text_config": {"hidden_size": 3, "projection_size": 2, "max_position_embeddings": 7},
        "vision_config": {"hidden_size": 2, "image_size": 40, "patch_size": 5}})
    write_json(path / "preprocessor_config.json", {"size": {"height": 40, "width": 32}, "patch_size": 5,
        "max_num_patches": 91, "do_resize": True, "resample": 2, "do_rescale": True,
        "rescale_factor": 0.01, "do_normalize": True, "image_mean": [0.1, 0.2, 0.3], "image_std": [0.4, 0.5, 0.6]})
    write_json(path / "tokenizer_config.json", {"do_lower_case": True, "add_bos_token": False,
        "add_eos_token": True, "model_max_length": 10**30, "tokenizer_class": "PreTrainedTokenizerFast"})
    write_json(path / "tokenizer.json", {"fixture": "serialized tokenizer"})
    write_json(path / "special_tokens_map.json", {"eos_token": "<end>"})
    write_json(path / "added_tokens.json", {"<end>": 1})
    if sharded:
        for name in ("z.safetensors", "a.safetensors"):
            (path / name).write_bytes(name.encode())
        write_json(path / "model.safetensors.index.json", {"weight_map": {
            "text.weight": "z.safetensors", "vision.weight": "a.safetensors"}})
    else:
        (path / "model.safetensors").write_bytes(b"both towers; no model validation")
    return path


@pytest.mark.parametrize("model_type,structure", [("siglip", "fixres"), ("siglip2", "naflex")])
def test_inspection_reports_only_declared_information(tmp_path, model_type, structure):
    path = model_tree(tmp_path, model_type)
    result = inspect_siglip(tmp_path, REF)
    assert result.structure == structure and result.model_type == model_type
    assert result.image.model_dump() == {"dimensions": 2, "image_size": 40, "patch_size": 5}
    assert result.text.dimensions == 2 and result.text.hidden_size == 3
    assert result.text.max_position_embeddings == 7 and result.text.tokenizer_max_length == 10**30
    assert result.processor.max_num_patches == 91 and result.processor.rescale_factor == 0.01
    assert result.processor.size == {"height": 40, "width": 32} and result.diagnostics == []
    write_json(path / "config.json", {"model_type": model_type, "text_config": {"hidden_size": 17}})
    write_json(path / "preprocessor_config.json", {})
    result = inspect_siglip(tmp_path, REF)
    assert result.image.dimensions is None and result.text.dimensions is None
    assert result.text.hidden_size == 17 and result.text.max_position_embeddings is None
    assert all(value is None for value in result.processor.model_dump().values())


def test_inspection_retains_partial_information_and_diagnostics(tmp_path):
    path = model_tree(tmp_path)
    write_json(path / "config.json", {"model_type": "unknown", "vision_config": [],
        "text_config": {"projection_size": "12", "max_position_embeddings": 24}})
    (path / "preprocessor_config.json").write_text("{broken", encoding="utf-8")
    (path / "tokenizer_config.json").unlink()
    result = inspect_siglip(tmp_path, REF)
    assert result.structure is None and result.model_type == "unknown"
    assert result.text.dimensions is None and result.text.max_position_embeddings == 24
    assert {d.code for d in result.diagnostics} == {"missing_config", "invalid_config", "invalid_field", "unknown_structure"}
    write_json(path / "preprocessor_config.json", {"do_resize": "true", "image_mean": [0.1, "bad"], "max_num_patches": 37})
    result = inspect_siglip(tmp_path, REF)
    assert result.processor.do_resize is None and result.processor.image_mean is None
    assert result.processor.max_num_patches == 37


def test_inspection_api_has_no_runtime_weights_or_hash_dependency(tmp_path, monkeypatch):
    path = model_tree(tmp_path)
    with TestClient(create_app(root=tmp_path, use_memory=True)) as client:
        state = client.app.state.runtime_state
        def forbidden(*args, **kwargs):
            raise AssertionError("Inspection touched loading infrastructure")
        monkeypatch.setattr(state.model_manager.runtime_supervisor, "executable", forbidden)
        monkeypatch.setattr(siglip, "model_revision", forbidden)
        original_open, before = Path.open, set(sys.modules)
        def checked_open(source, *args, **kwargs):
            if source.is_relative_to(path):
                assert source.name in {"config.json", "preprocessor_config.json", "tokenizer_config.json"}
            return original_open(source, *args, **kwargs)
        monkeypatch.setattr(Path, "open", checked_open)
        response = client.get("/api/models/inspect", params={"kind": "image_embedding", "model_ref": REF})
        assert response.status_code == 200 and response.json()["structure"] == "naflex"
        assert inventory(tmp_path, "image_embedding")[0]["model_ref"] == REF
        assert not {"torch", "transformers", "onnxruntime", "numpy", "tokenizers"} & (set(sys.modules) - before)
        for invalid in ("../escape", "/absolute", "image_embeddings/../escape", "C:/absolute", "a\\b", "invalid\0"):
            result = client.get("/api/models/inspect", params={"kind": "image_embedding", "model_ref": invalid})
            assert result.status_code == 422 and result.json()["error"]["code"] == "INVALID_REQUEST"
        assert client.get("/api/models/inspect", params={"kind": "llm", "model_ref": REF}).status_code == 422
        assert client.get("/api/models/inspect", params={"kind": "image_embedding", "model_ref": "missing"}).status_code == 404
        (path / "config.json").unlink()
        assert client.get("/api/models/inspect", params={"kind": "image_embedding", "model_ref": REF}).status_code == 200
        draft = client.post("/api/models/profiles", json={"name": "Draft", "alias": "draft", "kind": "image_embedding", "model_ref": REF})
        assert draft.status_code == 200 and draft.json()["source"] is None
        assert client.post(f"/api/models/profiles/{draft.json()['id']}/load").json()["error"]["code"] == "MODEL_NOT_CONFIGURED"


def test_inspection_rejects_directory_and_config_links_outside_boundary(tmp_path):
    from tests.test_runtime_maintenance import link_directory
    outside = model_tree(tmp_path / "outside")
    models = tmp_path / "data/models"
    models.mkdir(parents=True)
    link_directory(models / "linked", outside)
    with pytest.raises(ModelError) as error:
        inspect_siglip(tmp_path, "linked")
    assert error.value.code == "INVALID_REQUEST"
    path = model_tree(tmp_path)
    (path / "config.json").unlink()
    if os.name == "nt":
        link_directory(path / "config.json", outside)
    else:
        (path / "config.json").symlink_to(outside / "config.json")
    with pytest.raises(ModelError) as error:
        inspect_siglip(tmp_path, REF)
    assert error.value.code == "INVALID_REQUEST"


@pytest.mark.parametrize("sharded, expected", [
    (False, "sha256:d4dc74abe8111da92468cab092a5381fb413af602c7f1ac46537415fbdde75bc"),
    (True, "sha256:55a6e0c1fc3376b7e1d0acf095e28e1b1e3ec19bf7aa5cf8b50093bb3c8aee2c"),
])
def test_revision_covers_consumed_files_and_is_independent_of_directory(tmp_path, sharded, expected):
    path = model_tree(tmp_path, sharded=sharded)
    baseline = model_revision(path)
    assert baseline == expected
    copied = tmp_path / "copied"
    shutil.copytree(path, copied)
    assert model_revision(copied) == baseline
    assert model_files(path) == sorted(model_files(path))
    for filename in model_files(path):
        source, original = path / filename, (path / filename).read_bytes()
        source.write_bytes(original + b" ")
        assert model_revision(path) != baseline, filename
        source.write_bytes(original)
    for filename in ("README.md", "model-ready.json", "tokenizer.model", "unused.safetensors", ".cache"):
        (path / filename).write_text("irrelevant", encoding="utf-8")
    assert model_revision(path) == baseline


def test_single_file_precedence_and_only_consumed_optional_token_files_are_hashed(tmp_path):
    path = model_tree(tmp_path)
    write_json(path / "model.safetensors.index.json", {"weight_map": {"unused": "missing.safetensors"}})
    write_json(path / "tokenizer_config.json", {"added_tokens_decoder": {}})
    baseline = model_revision(path)
    assert "model.safetensors.index.json" not in model_files(path)
    assert not {"special_tokens_map.json", "added_tokens.json"} & set(model_files(path))
    (path / "special_tokens_map.json").write_text("broken but unused", encoding="utf-8")
    assert model_revision(path) == baseline


def test_shard_existence_and_path_containment_without_tensor_checks(tmp_path):
    path = model_tree(tmp_path, sharded=True)
    (path / "z.safetensors").unlink()
    with pytest.raises(WorkerError) as error:
        model_revision(path)
    assert error.value.code == "MODEL_NOT_FOUND"
    for invalid in ("../outside", "invalid\0"):
        write_json(path / "model.safetensors.index.json", {"weight_map": {"anything": invalid}})
        with pytest.raises(WorkerError) as error:
            model_revision(path)
        assert error.value.code == "INVALID_REQUEST"


def test_prepared_identity_is_computed_off_loop_and_recomputed_for_a_new_use(tmp_path, monkeypatch):
    import threading
    path = model_tree(tmp_path)
    original, threads = siglip.model_revision, []
    def capture(path):
        threads.append(threading.get_ident())
        return original(path)
    monkeypatch.setattr(siglip, "model_revision", capture)
    async def scenario():
        first = await SiglipModelUse.prepare(tmp_path, REF)
        (path / "model.safetensors").write_bytes(b"replaced after release")
        second = await SiglipModelUse.prepare(tmp_path, REF)
        assert first.model_revision != second.model_revision
        assert threads and all(thread != threading.get_ident() for thread in threads)
    asyncio.run(scenario())


def test_embedding_images_share_normalization_but_use_actual_area(monkeypatch):
    from ai_workbench.core.models import images as module
    monkeypatch.setattr(module, "MAX_TAGGING_PIXELS", 16)
    transparent = data_url(Image.new("RGBA", (8, 2), (0, 0, 0, 0)))
    normalized = prepare_embedding_images([transparent])[0]
    with Image.open(BytesIO(base64.b64decode(normalized.partition(",")[2]))) as result:
        assert result.mode == "RGB" and result.size == (8, 2) and result.getpixel((0, 0)) == (255, 255, 255)
    with pytest.raises(ModelError) as error:
        prepare_tagging_images("fixture", [transparent], {"general": 0.3, "character": 0.8})
    assert error.value.code == "REQUEST_TOO_LARGE"
    with pytest.raises(ModelError):
        prepare_embedding_images([data_url(Image.new("RGB", (9, 2)))])
    image = Image.new("RGB", (2, 3), "red")
    exif = Image.Exif(); exif[274] = 6
    normalized = prepare_embedding_images([data_url(image, format="JPEG", exif=exif)])[0]
    with Image.open(BytesIO(base64.b64decode(normalized.partition(",")[2]))) as result:
        assert result.size == (3, 2)


class Tensor:
    def __init__(self, values, dtype="float32"):
        self.values, self.dtype = values, dtype
    def is_floating_point(self):
        return self.dtype != "int64"
    def to(self, **kwargs):
        self.device, self.dtype = kwargs["device"], kwargs["dtype"]
        return self
    def float(self):
        return Tensor(self.values)
    def cpu(self):
        return self
    def tolist(self):
        return self.values


def fake_libraries(monkeypatch):
    calls = SimpleNamespace(loads=[], text=[], images=[], processor_config=None, tokenizer_kwargs=None, forwards=[])
    class Processor:
        @classmethod
        def from_dict(cls, values):
            calls.processor_config = values
            result = cls()
            result.__dict__.update(values)
            return result
        def __call__(self, *, images, return_tensors):
            calls.images.extend(image.getpixel((0, 0)) for image in images)
            return {"pixel_values": Tensor([[image.getpixel((0, 0))[0], 4.] for image in images])}
    class Backend:
        normalizer = "original"
        def to_str(self):
            return json.dumps({"normalizer": self.normalizer})
    class Tokenizer:
        @classmethod
        def convert_to_native_format(cls, trust_remote_code=False, **kwargs):
            return {"tokenizer_object": kwargs.pop("tokenizer_file"), **kwargs}
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls.tokenizer_kwargs = kwargs
            calls.native_kwargs = cls.convert_to_native_format(**kwargs)
            result = cls()
            result.init_kwargs = json.loads((Path(path) / "tokenizer_config.json").read_text())
            result.backend_tokenizer = Backend()
            result.padding_side, result.truncation_side, result.model_input_names = "right", "left", ["input_ids"]
            calls.tokenizer = result
            return result
        def __call__(self, values, **kwargs):
            calls.text.append((values, kwargs))
            return {"input_ids": Tensor([[len(value), 4.] for value in values], "int64")}
    calls.tokenizer_type = Tokenizer
    class Config:
        @classmethod
        def from_dict(cls, values):
            return SimpleNamespace(text_config=SimpleNamespace(**values["text_config"]),
                                   vision_config=SimpleNamespace(**values["vision_config"]))
    def model_type(name):
        class Model:
            @classmethod
            def from_pretrained(cls, path, **kwargs):
                calls.loads.append((name, kwargs))
                result = cls(); result.config = kwargs["config"]
                return result
            def to(self, device):
                calls.device = device
                return self
            def eval(self):
                return self
            def __call__(self, **batch):
                calls.forwards.append(batch)
                return SimpleNamespace(pooler_output=next(iter(batch.values())))
        return Model
    transformers = SimpleNamespace(__version__="fixture", PreTrainedTokenizerFast=Tokenizer)
    for prefix in ("Siglip", "Siglip2"):
        setattr(transformers, prefix + "Config", Config)
        setattr(transformers, prefix + "ImageProcessorPil", Processor)
        for tower in ("Vision", "Text"):
            setattr(transformers, prefix + tower + "Model", model_type(prefix + tower + "Model"))
    def normalize(tensor, p, dim):
        assert tensor.dtype == "float32" and p == 2 and dim == -1
        return Tensor([[value / math.sqrt(sum(v * v for v in row)) for value in row] for row in tensor.values])
    torch = SimpleNamespace(float16="float16", float32="float32", set_num_threads=lambda n: None,
        inference_mode=nullcontext, nn=SimpleNamespace(functional=SimpleNamespace(normalize=normalize)),
        cuda=SimpleNamespace(is_available=lambda: True, get_device_name=lambda n: "Mock GPU"))
    tokenizers = SimpleNamespace(__version__="fixture", normalizers=SimpleNamespace(Lowercase=lambda: "lowercase", Sequence=lambda v: v))
    monkeypatch.setattr(siglip_engine, "require_offline", lambda: None)
    monkeypatch.setattr(siglip_engine, "libraries", lambda: (torch, transformers, tokenizers, Image))
    return calls, torch


@pytest.mark.parametrize("model_type,prefix", [("siglip", "Siglip"), ("siglip2", "Siglip2")])
@pytest.mark.parametrize("tower", ["image", "text"])
@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_engine_only_instantiates_target_tower_with_native_processing(tmp_path, monkeypatch, model_type, prefix, tower, device):
    path = model_tree(tmp_path, model_type)
    calls, _ = fake_libraries(monkeypatch)
    engine = siglip_engine.SiglipEngine(path, tower, {"device": device, "intraop_threads": 3, "max_batch_size": 2}, "sha256:" + "a" * 64)
    assert [name for name, _ in calls.loads] == [prefix + ("Vision" if tower == "image" else "Text") + "Model"]
    load = calls.loads[0][1]
    assert load["local_files_only"] is True and load["trust_remote_code"] is False and load["use_safetensors"] is True
    assert load["dtype"] == ("float16" if device == "cuda" else "float32")
    assert calls.processor_config["rescale_factor"] == 0.01 and calls.processor_config["max_num_patches"] == 91
    assert calls.tokenizer_kwargs["tokenizer_file"] == str(path / "tokenizer.json")
    assert calls.native_kwargs["tokenizer_file"] == str(path / "tokenizer.json")
    assert "tokenizer_object" not in calls.native_kwargs
    assert calls.tokenizer.backend_tokenizer.normalizer == ["lowercase", "original"]
    values = [data_url(Image.new("RGB", (2, 2), color)) for color in ((3, 1, 1), (4, 1, 1), (5, 1, 1))] if tower == "image" else ["HELLO", "<Special>", "long " * 20]
    first = engine.embed(values)
    assert engine.embed(values) == first and len(calls.loads) == 1
    assert all(math.isclose(sum(x*x for x in vector), 1) for vector in first["vectors"])
    assert first["dimensions"] == 2 and first["output_dtype"] == "float32"
    assert first["usage"] is first["timing"] is None
    if tower == "text":
        assert calls.text[0][0] == values[:2]  # No query prefix or translation; special input is preserved.
        assert calls.text[0][1] == {"padding": "max_length", "truncation": True, "max_length": 7,
            "add_special_tokens": True, "return_tensors": "pt", "return_attention_mask": False, "return_token_type_ids": False}
        assert all(batch["input_ids"].dtype == "int64" for batch in calls.forwards)
    else:
        assert first["vectors"][0] == [0.6, 0.8]
        assert calls.images[:3] == [(3, 1, 1), (4, 1, 1), (5, 1, 1)]


def test_tokenizer_file_override_is_local_to_siglip(tmp_path, monkeypatch):
    path = model_tree(tmp_path)
    calls, _ = fake_libraries(monkeypatch)
    native_conversion = calls.tokenizer_type.convert_to_native_format.__func__
    siglip_engine.SiglipEngine(path, "text", SiglipOptions().model_dump(), "sha256:" + "a" * 64)
    assert type(calls.tokenizer) is not calls.tokenizer_type
    assert isinstance(calls.tokenizer, calls.tokenizer_type)
    assert calls.tokenizer_type.convert_to_native_format.__func__ is native_conversion
    assert calls.tokenizer_type.convert_to_native_format(tokenizer_file="other.json") == {"tokenizer_object": "other.json"}


def test_vector_identity_is_shared_across_towers_devices_and_batch_options(tmp_path, monkeypatch):
    path = model_tree(tmp_path)
    fake_libraries(monkeypatch)
    def identity(tower, device, batch=1):
        return siglip_engine.SiglipEngine(path, tower, {"device": device, "intraop_threads": 1, "max_batch_size": batch}, "sha256:" + "a"*64).info["vector_space_id"]
    baseline = identity("image", "cuda")
    assert identity("text", "cpu", 3) == baseline
    processor = (path / "preprocessor_config.json").read_bytes()
    changed = json.loads(processor); changed["max_num_patches"] = 29
    write_json(path / "preprocessor_config.json", changed)
    assert identity("image", "cuda") != baseline
    (path / "preprocessor_config.json").write_bytes(processor)
    tokenizer = (path / "tokenizer_config.json").read_bytes()
    changed = json.loads(tokenizer); changed["do_lower_case"] = False
    write_json(path / "tokenizer_config.json", changed)
    assert identity("text", "cuda") != baseline
    (path / "tokenizer_config.json").write_bytes(tokenizer)
    monkeypatch.setattr(siglip_engine, "PIPELINE_VERSION", "changed")
    assert identity("image", "cuda") != baseline


def test_unavailable_cuda_never_falls_back_to_cpu(tmp_path, monkeypatch):
    path = model_tree(tmp_path)
    calls, torch = fake_libraries(monkeypatch)
    torch.cuda.is_available = lambda: False
    with pytest.raises(WorkerError) as error:
        siglip_engine.SiglipEngine(path, "text", SiglipOptions().model_dump(), "sha256:" + "a"*64)
    assert error.value.code == "RUNTIME_DEVICE_UNAVAILABLE" and calls.loads == []


def test_private_worker_validation_options_and_reserved_timing(tmp_path):
    model_tree(tmp_path)
    factory = lambda *args: SimpleNamespace(info={"tower": "text"}, embed=lambda inputs: inputs)
    worker = SiglipWorker(tmp_path / "data/models", REF, "text", SiglipOptions().model_dump(), "sha256:" + "a"*64, factory)
    assert worker.dispatch("/embed", {"inputs": ["hello"]}) == ["hello"]
    for operation, body in (("/load", {}), ("/embed", {"inputs": [""]}), ("/embed", {"inputs": ["hello"], "tower": "image"})):
        with pytest.raises(WorkerError):
            worker.dispatch(operation, body)
    with worker.lock:
        with pytest.raises(WorkerError) as error:
            worker.dispatch("/embed", {"inputs": ["hello"]})
    assert error.value.code == "MODEL_BUSY"
    assert SiglipOptions().model_dump() == {"device": "cuda", "intraop_threads": 4, "max_batch_size": 1}
    assert all(value is None for value in InferenceTiming().model_dump().values())
    for values in ({"device": "auto"}, {"max_batch_size": 0}, {"max_batch_size": True}, {"dtype": "float16"}):
        with pytest.raises(ValidationError):
            SiglipOptions(**values)
