"""WD14 configuration, image boundaries, public protocol and model-free inference."""
import asyncio
import base64
from contextlib import asynccontextmanager
from io import BytesIO
import json
from pathlib import Path
import random
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
import pytest

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.images import prepare_tagging_images
from ai_workbench.core.models.inventory import inventory
from tests.model_fixtures import resolve_local_profile
from ai_workbench.core.models.runtimes.catalog import worker_entrypoint
from ai_workbench.core.models.runtimes.schema import Installation, local_engine
from ai_workbench.core.models.schema import InferenceUsage, ModelProfile, VisionRequest, VisionResult
from ai_workbench.workers.common import WorkerError, local_model
from ai_workbench.workers.protocol import load_request, tags_request
from ai_workbench.workers import wd14_engine

HEADERS = {"Authorization": "Bearer test-key"}
DEFAULTS = {"general": 0.35, "character": 0.85}


def model_tree(root, name="tagger"):
    path = root / "data/models/vision" / name
    path.mkdir(parents=True)
    (path / "model.onnx").touch()
    (path / "selected_tags.csv").write_text("name,category\nrating,9\nblue_eyes,0\ncharacter_name,4\n", encoding="utf-8")
    return path


def data_url(image=None, *, format="PNG", **save_options):
    output = BytesIO()
    (image or Image.new("RGB", (8, 4), "red")).save(output, format=format, **save_options)
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}[format]
    return f"data:{mime};base64," + base64.b64encode(output.getvalue()).decode("ascii")


def profile(**values):
    return ModelProfile(**{"name": "Tagger", "alias": "tagger", "kind": "vision", "model_ref": "vision/tagger",
                          "source": {"type": "local"}, "external_enabled": True, **values})


@pytest.fixture
def api(tmp_path):
    model_tree(tmp_path)
    with TestClient(create_app(root=tmp_path, use_memory=True), client=("127.0.0.1", 40001)) as client:
        response = client.post("/api/models/profiles", json=profile().model_dump(exclude={"id", "created_at", "updated_at"}))
        assert response.status_code == 200, response.text
        client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "test-key"})
        yield client, response.json()


def test_profile_defaults_and_reserved_usage(tmp_path):
    model_tree(tmp_path)
    value = resolve_local_profile(tmp_path, profile())
    assert value.parameters == {"task": "tags", "thresholds": DEFAULTS}
    assert value.source.execution_options == {"device": "cpu", "intraop_threads": 4, "max_batch_size": 1}
    assert value.source.lifecycle.unload == "manual"
    assert local_engine(value) == "wd14" and worker_entrypoint("wd14") == "server.py"
    assert VisionResult(outputs=[]).usage is None
    assert InferenceUsage(input_images=0).model_dump() == {
        "input_images": 0, "input_tokens": None, "output_tokens": None, "total_tokens": None}
    for invalid in (-1, True, 1.5, "1"):
        with pytest.raises(ValidationError):
            InferenceUsage(input_tokens=invalid)


@pytest.mark.parametrize("values", [
    {"source": {"type": "provider", "provider_profile_id": "remote"}},
    {"source": {"type": "local", "execution_options": {"device": "cuda"}}},
    {"source": {"type": "local", "execution_options": {"max_batch_size": 2}}},
    {"parameters": {"batch_size": 1}}, {"parameters": {"architecture": "another"}},
    {"parameters": {"task": "video"}}, {"parameters": {"thresholds": {"general": None}}},
    *({"parameters": {"thresholds": {"general": value}}} for value in (-0.1, 1.1, True, "0.3", float("nan"))),
])
def test_invalid_profile_configuration_is_rejected(values):
    with pytest.raises(ValidationError):
        profile(**values)


@pytest.mark.parametrize("memory", [True, False])
def test_vision_crud_preserves_zero_and_local_source_in_both_stores(tmp_path, memory):
    with TestClient(create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'app.db'}")) as client:
        draft = client.post("/api/models/profiles", json={"name": "Draft", "alias": "draft", "kind": "vision", "model_ref": "vision/any"})
        assert draft.status_code == 200 and draft.json()["source"]["type"] == 'local'
        path = "/api/models/profiles/" + draft.json()["id"]
        assert client.post(path + "/load").json()["error"]["code"] == "MODEL_NOT_FOUND"
        local = client.patch(path, json={"source": {"type": "local"}, "parameters": {"thresholds": {"general": 0, "character": 1}}})
        assert local.status_code == 200, local.text
        assert local.json()["parameters"]["thresholds"] == {"general": 0, "character": 1}
        assert local.json()["source"]["execution_options"] == {}
        saved, fetched = local.json(), client.get(path).json()
        for result in (saved, fetched):
            for key in ("created_at", "updated_at"):
                result[key] = result[key].removesuffix("Z")
        assert fetched == saved
        assert client.patch(path, json={"parameters": {"batch_size": 1}}).status_code == 422
        assert client.patch(path, json={"source": None}).status_code == 422
        assert client.get(path).json()["parameters"] == local.json()["parameters"]
        assert client.delete(path).status_code == 200


def test_inventory_and_status_read_only_configuration_not_weights_or_labels(tmp_path, api, monkeypatch):
    client, value = api
    manager = client.app.state.runtime_state.model_manager
    monkeypatch.setattr(manager.runtime_supervisor, "installation", lambda **_: Installation(version="1", state="installed"))
    original_open = Path.open

    def read_boundary(path, *args, **kwargs):
        assert not path.is_relative_to(tmp_path / "data/models") or path.suffix == '.json', "Model weights or labels were read before loading"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", read_boundary)
    before = set(sys.modules)
    assert inventory(tmp_path, "vision")[0]["model_ref"] == "vision/tagger"
    assert manager.status(value["id"]).state == "unloaded"
    (tmp_path / "data/models/vision/tagger/selected_tags.csv").unlink()
    assert inventory(tmp_path, "vision") == []
    assert manager.status(value["id"]).error_code == "MODEL_NOT_FOUND"
    assert not {"numpy", "onnxruntime", "spacy", "torch"} & (set(sys.modules) - before)


def test_inventory_and_loading_reject_model_links_outside_models_root(tmp_path):
    from tests.test_runtime_maintenance import link_directory
    outside = model_tree(tmp_path / "outside")
    root = tmp_path / "data/models"
    (root / "vision").mkdir(parents=True)
    link_directory(root / "vision/escape", outside)
    assert inventory(tmp_path, "vision") == []
    with pytest.raises(WorkerError):
        local_model(root, "vision/escape", wd14=True)


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_static_inputs_are_normalized_before_inference(format):
    originals = [data_url(format=format)]
    prepared = prepare_tagging_images("p", originals, DEFAULTS, max_bytes=1024 * 1024)
    assert originals[0].startswith(f"data:image/{'jpeg' if format == 'JPEG' else format.lower()};base64,")
    with Image.open(BytesIO(base64.b64decode(prepared[0].partition(",")[2]))) as result:
        assert result.format == "PNG" and result.mode == "RGB" and result.size == (8, 4)
        assert result.getpixel((3, 2))[0] > 240


def test_exif_orientation_and_alpha_are_applied_before_queueing():
    exif = Image.Exif()
    exif[274] = 6
    url = data_url(Image.new("RGBA", (3, 6), (255, 0, 0, 0)), exif=exif)
    prepared = prepare_tagging_images("p", [url], DEFAULTS, max_bytes=1024 * 1024)
    with Image.open(BytesIO(base64.b64decode(prepared[0].partition(",")[2]))) as result:
        assert result.size == (6, 3)
        assert result.getpixel((1, 1)) == (255, 255, 255)


@pytest.mark.parametrize("url", ["https://example.test/a.png", "vision/picture.png", "file:///a.png", "data:image/png;base64,broken!",
    "data:image/png,plain", data_url().removeprefix("data:"), data_url().replace("image/png", "image/jpeg"), data_url(format="GIF")])
def test_invalid_images_fail_before_admission(api, monkeypatch, url):
    client, _ = api
    manager = client.app.state.runtime_state.model_manager
    monkeypatch.setattr(manager, "_lease", MagicMock(side_effect=AssertionError("Invalid input reached queue")))
    response = client.post("/v1/images/tags", headers=HEADERS, json={"model": "tagger", "images": [url]})
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_IMAGE"
    assert not manager._slots


@pytest.mark.parametrize("format", ["PNG", "WEBP"])
def test_animated_images_are_rejected(format):
    url = data_url(format=format, save_all=True, append_images=[Image.new("RGB", (8, 4), "blue")], duration=100, loop=0)
    with pytest.raises(ModelError, match="static image"):
        prepare_tagging_images("p", [url], DEFAULTS, max_bytes=1024 * 1024)


def test_image_and_private_body_limits_cover_before_and_after_conversion(monkeypatch):
    from ai_workbench.core.models import images
    assert images.MAX_TAGGING_PIXELS == 64_000_000
    monkeypatch.setattr(images, "MAX_TAGGING_PIXELS", 64)
    prepare_tagging_images("p", [data_url()], DEFAULTS, max_bytes=1024 * 1024)
    for size in ((9, 8), (9, 1)):
        with pytest.raises(ModelError) as too_many_pixels:
            prepare_tagging_images("p", [data_url(Image.new("RGB", size))], DEFAULTS, max_bytes=1024 * 1024)
        assert too_many_pixels.value.status == 413
    monkeypatch.setattr(images, "MAX_TAGGING_PIXELS", 64_000_000)
    noise = Image.frombytes("RGB", (96, 96), random.Random(7).randbytes(96 * 96 * 3))
    small = data_url(noise, format="JPEG", quality=1)
    assert len(small) < 4096
    with pytest.raises(ModelError) as expansion:
        prepare_tagging_images("p", [small, data_url()], DEFAULTS, max_bytes=4096)
    assert expansion.value.status == 413
    monkeypatch.setattr(images, "_normalized_image", MagicMock(side_effect=AssertionError("Oversized input decoded")))
    with pytest.raises(ModelError) as before_decode:
        prepare_tagging_images("p", ["x" * 4096], DEFAULTS, max_bytes=4096)
    assert before_decode.value.status == 413


def test_square_pixel_limit_rejects_thin_images_before_decode_and_admission(api, monkeypatch):
    from ai_workbench.core.models import images
    client, _ = api
    manager = client.app.state.runtime_state.model_manager
    monkeypatch.setattr(images, "MAX_TAGGING_PIXELS", 64)
    monkeypatch.setattr(images.ImageOps, "exif_transpose", MagicMock(side_effect=AssertionError("Oversized image decoded")))
    monkeypatch.setattr(manager, "_lease", MagicMock(side_effect=AssertionError("Oversized image reached queue")))
    response = client.post("/v1/images/tags", headers=HEADERS, json={
        "model": "tagger", "images": [data_url(Image.new("RGB", (9, 1)))]})
    assert response.status_code == 413 and response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert not manager._slots


@pytest.mark.parametrize("patch", [{"images": []}, {"images": ["x"] * 17}, {"images": "x"}, {"images": [1]},
    {"thresholds": {"general": True}}, {"thresholds": {"general": "0.3"}}, {"thresholds": {"general": -1}},
    {"thresholds": {"character": 1.1}}, {"thresholds": {"rating": 0}}, {"stream": True}, {"unknown": 1}])
def test_public_request_schema_rejects_invalid_inputs_without_inference(api, monkeypatch, patch):
    client, _ = api
    manager = client.app.state.runtime_state.model_manager
    monkeypatch.setattr(manager, "vision", AsyncMock(side_effect=AssertionError("No inference")))
    response = client.post("/v1/images/tags", headers=HEADERS, json={"model": "tagger", "images": [data_url()], **patch})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    manager.vision.assert_not_called()


def test_public_result_threshold_inheritance_and_statelessness(api, monkeypatch):
    from ai_workbench.core.models import manager as manager_module
    client, value = api
    manager = client.app.state.runtime_state.model_manager
    calls, threads = [], []
    client.patch("/api/models/profiles/" + value["id"], json={"parameters": {"thresholds": {"general": 0.6, "character": 0.9}}})

    async def infer(p, images, thresholds):
        calls.append((p.id, images, thresholds, threading.get_ident()))
        return VisionResult(outputs=[{"index": index, "tags": [] if index else [
            {"name": "blue_eyes", "category": "general", "score": 0.95}]} for index in range(len(images))])

    def prepare(*args):
        threads.append(threading.get_ident())
        return prepare_tagging_images(*args)

    @asynccontextmanager
    async def lease(p):
        assert len(threads) == len(calls) + 1
        yield SimpleNamespace(vision=infer)

    monkeypatch.setattr(manager_module, "prepare_tagging_images", prepare)
    monkeypatch.setattr(manager, "_lease", lease)
    payload = {"model": "tagger", "images": [data_url(), data_url(format="JPEG")]}
    for thresholds, expected in [(None, {"general": 0.6, "character": 0.9}),
        ({"general": 0, "character": None}, {"general": 0, "character": 0.9}), ({}, {"general": 0.6, "character": 0.9})]:
        response = client.post("/v1/images/tags", headers=HEADERS, json={**payload, "thresholds": thresholds})
        assert response.status_code == 200, response.text
        result = response.json()
        assert set(result) == {"object", "model", "data"} and result["model"] == "tagger"
        assert result["data"][1] == {"object": "image.tags", "index": 1, "tags": []}
        assert result["data"][0]["tags"][0]["name"] == "blue_eyes"
        assert calls[-1][2] == expected and threads[-1] != calls[-1][3]
        assert all(image.startswith("data:image/png;base64,") for image in calls[-1][1])
        assert response.headers["x-request-id"]
    assert manager.profiles.get(value["id"]).parameters["thresholds"] == {"general": 0.6, "character": 0.9}
    assert client.get("/api/sessions").json() == []
    assert not client.app.state.runtime_state.runs.list_all_runs()


def test_service_auth_visibility_kind_discovery_and_source_restriction(api, monkeypatch):
    client, value = api
    manager = client.app.state.runtime_state.model_manager
    monkeypatch.setattr(manager, "load", AsyncMock(side_effect=AssertionError("No load")))
    for kind in (None, "vision"):
        response = client.get("/v1/models", headers=HEADERS, params={} if kind is None else {"kind": kind})
        assert [item["id"] for item in response.json()["data"]] == ["tagger"]
    assert client.get("/v1/models?kind=tts", headers=HEADERS).json()["data"] == []
    assert client.get("/v1/models?kind=video", headers=HEADERS).status_code == 422
    payload = {"model": "tagger", "images": [data_url()]}
    assert client.post("/v1/images/tags", json=payload).status_code == 401
    assert client.post("/v1/images/tags", headers={"X-Api-Key": "wrong"}, json=payload).status_code == 401
    path = "/api/models/profiles/" + value["id"]
    assert client.patch(path, json={"source": None}).status_code == 422
    assert client.get(path).json()['source']['type'] == 'local'
    client.patch(path, json={"external_enabled": False})
    assert client.get("/v1/models?kind=vision", headers=HEADERS).json()["data"] == []
    assert client.post("/v1/images/tags", headers=HEADERS, json=payload).status_code == 404
    client.patch("/api/models/settings", json={"external_enabled": False})
    assert client.post("/v1/images/tags", headers=HEADERS, json=payload).status_code == 503
    assert not manager._slots


def test_external_body_limit_and_loopback_requirement(api, tmp_path):
    client, _ = api
    client.patch("/api/models/settings", json={"max_request_mb": 1})
    response = client.post("/v1/images/tags", headers=HEADERS, json={"model": "tagger", "images": ["x" * 1024 * 1024]})
    assert response.status_code == 413
    with TestClient(create_app(root=tmp_path, use_memory=True), client=("192.0.2.2", 5000)) as remote:
        assert remote.post("/v1/images/tags", json={}).status_code == 403


@pytest.mark.parametrize("chunked", [False, True])
def test_public_body_cap_includes_json_whitespace(api, monkeypatch, chunked):
    client, _ = api
    client.patch("/api/models/settings", json={"max_normalized_request_mb": 1}).raise_for_status()
    manager = client.app.state.runtime_state.model_manager
    monkeypatch.setattr(manager, "vision", AsyncMock(side_effect=AssertionError("Oversized body reached inference")))
    payload = json.dumps({"model": "tagger", "images": [data_url()]}).encode()
    assert len(payload) < 1024 * 1024
    pieces = [payload, b" " * (1024 * 1024)]
    response = client.post("/v1/images/tags", headers={**HEADERS, "Content-Type": "application/json"},
        content=iter(pieces) if chunked else b"".join(pieces))
    assert response.status_code == 413 and response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    manager.vision.assert_not_called()


@pytest.mark.parametrize("size,count", [((384, 384), 3), ((448, 448), 5), ((8, 6), 7)])
def test_engine_reads_actual_shapes_names_csv_and_uses_cpu(tmp_path, monkeypatch, size, count):
    path = model_tree(tmp_path)
    (path / "selected_tags.csv").write_text("name,category\n" + "".join(f"tag_{index},{9 if index == 0 else 0}\n" for index in range(count)))
    session = MagicMock()
    session.get_inputs.return_value = [SimpleNamespace(name="actual_pixels", shape=[1, size[1], size[0], 3])]
    session.get_outputs.return_value = [SimpleNamespace(name="actual_scores")]
    session.run.return_value = [[[0.7] * count]]
    ort, np = MagicMock(), MagicMock()
    ort.InferenceSession.return_value = session
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    monkeypatch.setitem(sys.modules, "numpy", np)
    monkeypatch.setattr(wd14_engine, "require_offline", lambda: None)
    engine = wd14_engine.WD14Engine(path, "vision", {}, {"intraop_threads": 3})
    result = engine.tags([data_url(), data_url()], {"general": 0, "character": 0})
    assert engine.image_size == size and len(engine.labels) == count
    assert [tag["name"] for tag in result["outputs"][0]["tags"]] == [f"tag_{i}" for i in range(1, count)]
    assert session.run.call_count == 2
    assert session.run.call_args.args[0] == ["actual_scores"]
    assert set(session.run.call_args.args[1]) == {"actual_pixels"}
    assert ort.InferenceSession.call_args.kwargs["providers"] == ["CPUExecutionProvider"]
    assert ort.SessionOptions.return_value.intra_op_num_threads == 3
    resized = np.asarray.call_args.args[0]
    assert resized.size == size
    assert np.asarray.call_args.kwargs["dtype"] is np.float32
    assert resized.getpixel((0, 0)) == (255, 255, 255)
    assert resized.getpixel((size[0] // 2, size[1] // 2))[0] == 255
    assert np.asarray.return_value.__getitem__.call_args.args == ((slice(None), slice(None), slice(None, None, -1)),)
    assert np.expand_dims.call_args.kwargs == {"axis": 0}
    np.ascontiguousarray.assert_called()


def test_filtering_preserves_csv_names_threshold_zero_and_stable_ties():
    engine = wd14_engine.WD14Engine.__new__(wd14_engine.WD14Engine)
    engine.labels = [("rating", None), ("first_tag", "general"), ("character_name", "character"), ("second_tag", "general"), ("zero_tag", "general")]
    engine._image_batch = lambda _: object()
    engine.model = SimpleNamespace(run=lambda *_: [[[1, 0.85, 0.85, 0.85, 0]]])
    engine.input_name, engine.output_name = "pixels", "scores"
    result = engine.tags(["prepared"], {"general": 0, "character": 0.85})
    assert [item["name"] for item in result["outputs"][0]["tags"]] == ["first_tag", "character_name", "second_tag", "zero_tag"]
    assert engine.tags(["prepared"], {"general": 1, "character": 1})["outputs"][0]["tags"] == []


@pytest.mark.parametrize("scores", [[[0.5]], [[0.5, float("nan")]], [[0.5, 1.2]], [[0.5, -0.1]], [[0.5, 0.5], [0.5, 0.5]]])
def test_invalid_output_mapping_fails_instead_of_truncating(scores):
    engine = wd14_engine.WD14Engine.__new__(wd14_engine.WD14Engine)
    engine.labels = [("a", "general"), ("b", "general")]
    engine.input_name, engine.output_name = "pixels", "scores"
    engine._image_batch = lambda _: object()
    engine.model = SimpleNamespace(run=lambda *_: [scores])
    with pytest.raises(WorkerError) as error:
        engine.tags(["prepared"], DEFAULTS)
    assert (error.value.code, error.value.status) == ("MODEL_UNAVAILABLE", 503)


def test_private_protocol_validates_before_engine_imports(tmp_path):
    path = model_tree(tmp_path)
    p = resolve_local_profile(tmp_path, profile())
    body = {"profile_id": p.id, "kind": p.kind, "model_ref": p.model_ref, "parameters": p.parameters, "options": p.source.execution_options}
    assert load_request(body, tmp_path / "data/models") == path
    for patch in ({"options": {**body["options"], "device": "cuda"}}, {"parameters": {**p.parameters, "batch_size": 1}},
                  {"parameters": {**p.parameters, "thresholds": {"general": True, "character": 1}}}):
        with pytest.raises(WorkerError):
            load_request({**body, **patch}, tmp_path / "data/models")
    tags_request({"profile_id": "p", "images": [data_url()], "thresholds": DEFAULTS})
    for patch in ({"images": []}, {"images": ["https://example.test"]}, {"thresholds": {"general": None, "character": 1}}):
        with pytest.raises(WorkerError):
            tags_request({"profile_id": "p", "images": [data_url()], "thresholds": DEFAULTS, **patch})
