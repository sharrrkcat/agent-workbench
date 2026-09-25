"""ASR schemas, native metadata and long-form preprocessing without heavyweight imports."""
from contextlib import nullcontext
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ai_workbench.api.main import create_app
from ai_workbench.core.models.inspection import inspect_asr
from ai_workbench.core.models.inventory import inventory
from ai_workbench.core.models.schema import TranscriptionRequest, TranscriptionResult
from ai_workbench.core.models.store import ModelProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.workers import asr_engine
from ai_workbench.workers.asr_catalog import input_path, load_configuration
from ai_workbench.workers.asr_server import ASRWorker
from ai_workbench.workers.common import WorkerError
from tests.asr_fixtures import OPTIONS, PARAMETERS, REF, model_tree, profile, write_json


@pytest.mark.parametrize("features,multilingual", [(80, True), (128, True), (80, False)])
def test_native_directory_information_has_no_checkpoint_name_allowlist(tmp_path, features, multilingual):
    path = model_tree(tmp_path, features=features, multilingual=multilingual)
    information = inspect_asr(tmp_path, REF)
    assert not information.diagnostics
    assert information.architecture == "whisper" and information.processor == "WhisperProcessor"
    assert information.sample_rate == 16000 and information.feature_size == features
    assert information.multilingual is multilingual and information.segment_timestamps
    assert information.languages == (["en", "zh"] if multilingual else ["en"])
    assert [item["model_ref"] for item in inventory(tmp_path, "asr")] == [REF]
    assert load_configuration(tmp_path / "data/models", REF)[0] == path


def test_inventory_inspection_status_and_resource_checks_never_read_or_hash_weights(tmp_path, monkeypatch):
    model_tree(tmp_path)
    with TestClient(create_app(root=tmp_path, use_memory=True)) as client:
        manager = client.app.state.runtime_state.model_manager
        model = manager.profiles.create(profile())
        original = Path.open
        def no_weights(path, *args, **kwargs):
            assert path.suffix not in {".safetensors", ".bin"}, f"Unexpected weight read: {path}"
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "open", no_weights)
        monkeypatch.setattr(hashlib, "sha256", lambda *_a, **_kw: pytest.fail("ASR must not hash models"))
        assert not inspect_asr(tmp_path, REF).diagnostics
        assert len(inventory(tmp_path, "asr")) == 1
        assert load_configuration(tmp_path / "data/models", REF)[0].name == "native-model"
        assert manager.status(model.id).residency == "unloaded"
        assert not {"torch", "transformers", "soundfile", "librosa"} & sys.modules.keys()


@pytest.mark.parametrize("file,value,code", [
    ("config.json", {"model_type": "other"}, "unsupported_configuration"),
    ("config.json", {"model_type": "whisper", "architectures": ["WhisperForAudioClassification"]}, "unsupported_configuration"),
    ("preprocessor_config.json", {"sampling_rate": 16000, "feature_size": 128}, "unsupported_configuration"),
    ("preprocessor_config.json", {"sampling_rate": 0, "feature_size": 80}, "invalid_field"),
    ("tokenizer_config.json", {"auto_map": {"AutoTokenizer": "custom.Tokenizer"}}, "remote_code"),
    ("tokenizer_config.json", {"tokenizer_class": "CustomTokenizer"}, "unsupported_configuration"),
    ("generation_config.json", {"is_multilingual": True, "lang_to_id": {}}, "invalid_field"),
    ("config.json", [], "invalid_config"),
])
def test_unsupported_metadata_fails_before_inference_imports(tmp_path, file, value, code):
    path = model_tree(tmp_path)
    write_json(path / file, value)
    assert code in {item.code for item in inspect_asr(tmp_path, REF).diagnostics}
    worker = ASRWorker(tmp_path / "data/models", tmp_path, lambda *_args: pytest.fail("No engine should load"))
    with pytest.raises(WorkerError, match="UNSUPPORTED_CAPABILITY"):
        worker.dispatch("/load", {"profile_id": "test", "kind": "asr", "model_ref": REF,
            "parameters": PARAMETERS, "options": OPTIONS})


def test_missing_configuration_weights_tokenizer_and_unsafe_paths(tmp_path):
    path = model_tree(tmp_path)
    for name in ("preprocessor_config.json", "model.safetensors", "tokenizer.json"):
        file = path / name
        saved = file.read_bytes()
        file.unlink()
        with pytest.raises(WorkerError, match="MODEL_NOT_FOUND"):
            load_configuration(tmp_path / "data/models", REF)
        file.write_bytes(saved)
    for reference in ("../escape", "/absolute", "C:/outside", "asr\\model", "asr/../model"):
        with pytest.raises(WorkerError):
            load_configuration(tmp_path / "data/models", reference)
        with pytest.raises(WorkerError):
            input_path(tmp_path, reference)
    write_json(path / "model.safetensors.index.json", {"weight_map": {"weight": "../outside.safetensors"}})
    with pytest.raises(WorkerError):
        load_configuration(tmp_path / "data/models", REF)


@pytest.mark.parametrize("memory", [True, False])
def test_profile_crud_drafts_inspection_and_local_only_sources(tmp_path, memory):
    model_tree(tmp_path)
    with TestClient(create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'app.db'}")) as client:
        response = client.post("/api/models/profiles", json={"kind": "asr", "name": "ASR", "alias": "asr",
            "model_ref": REF, "source": {"type": "local"}})
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["parameters"] == PARAMETERS and saved["source"]["execution_options"] == OPTIONS
        assert saved["source"]["lifecycle"]["unload"] == "manual" and not saved["external_enabled"]
        information = client.get("/api/models/inspect", params={"kind": "asr", "model_ref": REF})
        assert information.status_code == 200 and information.json()["feature_size"] == 80
        assert client.get("/api/models/inspect", params={"kind": "asr", "model_ref": REF, "query_prompt_name": "q"}).status_code == 422
        assert client.get("/api/models/profiles?kind=asr").json()[0]["id"] == saved["id"]
        route = "/api/models/profiles/" + saved["id"]
        for patch in ({"parameters": {"architecture": "whisper"}}, {"parameters": {"word_timestamps": True}},
                {"source": {"type": "provider", "provider_profile_id": "x"}},
                {"source": {"type": "local", "execution_options": {"max_batch_size": 2}}}):
            assert client.patch(route, json=patch).status_code == 422
        assert client.patch(route, json={"source": None}).status_code == 422
        assert client.patch(route, json={"model_ref": "asr/missing"}).status_code == 200
        assert client.get(route).json()['source']['type'] == 'local'
        assert client.delete(route).status_code == 200


@pytest.mark.parametrize("patch", [{"language": "english"}, {"language": 2}, {"temperature": True},
    {"temperature": "0.2"}, {"temperature": float("nan")}, {"temperature": 1.1}, {"temperature": -0.1},
    {"prompt": 2}, {"response_format": "srt"}, {"timestamp_granularities": ["word"]},
    {"timestamp_granularities": []}, {"stream": False}, {"task": "translate"}, {"num_beams": 4}])
def test_request_controls_are_strict(patch):
    with pytest.raises(ValidationError):
        TranscriptionRequest.model_validate(patch)


def test_transcription_openapi_has_multipart_controls_and_explicit_output_formats(tmp_path):
    with TestClient(create_app(root=tmp_path, use_memory=True)) as client:
        document = client.get("/openapi.json").json()
        operation = document["paths"]["/v1/audio/transcriptions"]["post"]
        reference = operation["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
        schema = document["components"]["schemas"][reference.rsplit("/", 1)[-1]]
        assert schema["additionalProperties"] is False and set(schema["required"]) == {"model", "file"}
        assert set(schema["properties"]) == {"model", "file", "language", "prompt", "temperature", "response_format", "timestamp_granularities[]"}
        assert schema["properties"]["file"]["format"] == "binary"
        assert set(operation["responses"]["200"]["content"]) == {"application/json", "text/plain"}
        assert operation["security"] == [{"BearerAuth": []}, {"ApiKeyAuth": []}]
        assert "X-Request-Id" in operation["responses"]["200"]["headers"]


@pytest.mark.parametrize("patch", [{"duration": float("inf")}, {"language": 4}, {"text": []},
    {"segments": None}, {"segments": [{"id": 1, "start": 0.0, "end": 1.0, "text": "x"}]},
    {"segments": [{"id": 0, "start": 2.0, "end": 1.0, "text": "x"}]}])
def test_worker_results_reject_invalid_types_nonfinite_values_and_segments(patch):
    with pytest.raises(ValidationError):
        TranscriptionResult.model_validate({"response_format": "verbose_json", "task": "transcribe", "language": "en",
            "duration": 2.0, "text": "x", "segments": [{"id": 0, "start": 0.0, "end": 1.0, "text": "x"}], **patch})


@pytest.mark.parametrize("frames,verbose", [(29 * 16000, False), (30 * 16000, False),
    (30 * 16000 + 1, False), (150 * 16000, False), (150 * 16000, True)])
def test_native_generation_receives_full_features_attention_and_controls(monkeypatch, frames, verbose):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    monkeypatch.setitem(sys.modules, "librosa", SimpleNamespace())
    audio = MagicMock()
    audio.__len__.return_value = frames
    monkeypatch.setattr(asr_engine, "decode_audio", lambda _: (audio, 16000))
    engine = asr_engine.ASREngine.__new__(asr_engine.ASREngine)
    engine.device, engine.dtype = "cuda", "float16"
    engine.information = {"languages": ["en", "zh"], "multilingual": True}
    engine.language_codes = {10: "en", 11: "zh"}
    engine.processor, engine.model = MagicMock(), MagicMock()
    engine.model.generation_config = SimpleNamespace(language="zh", task="translate", num_beams=4, no_speech_threshold=0.6)
    engine.processor.feature_extractor.sampling_rate = 16000
    engine.model.model.encoder.conv1.stride = (1,)
    engine.model.model.encoder.conv2.stride = (2,)
    engine.model.config.max_source_positions = 1500
    features, mask = MagicMock(), MagicMock()
    features.shape = (1, 80, (frames + 159) // 160)
    features.to.return_value = features
    mask.to.return_value = mask
    engine.processor.return_value = SimpleNamespace(input_features=features, attention_mask=mask)
    sequence = MagicMock()
    sequence.reshape.return_value.tolist.return_value = [10, 23]
    engine.model.generate.return_value = {"sequences": sequence, "segments": [[
        {"start": 32.0, "end": 35.0, "tokens": [23], "result": sequence}]]}
    engine.processor.batch_decode.return_value = [" complete transcript after thirty seconds "]
    engine.processor.decode.return_value = " after thirty seconds "
    options = {**PARAMETERS, "prompt": "context", "temperature": 0.4,
        "response_format": "verbose_json" if verbose else "text"}
    result = engine.transcribe(Path("input.wav"), options)
    assert result["text"] == "complete transcript after thirty seconds"
    assert result["duration"] == frames / 16000 and result["language"] == "en"
    assert engine.processor.call_args.args[0] is audio
    assert engine.processor.call_args.kwargs == {"sampling_rate": 16000, "return_tensors": "pt",
        "truncation": False, "padding": "max_length", "return_attention_mask": True}
    kwargs = engine.model.generate.call_args.kwargs
    assert kwargs["return_timestamps"] == (verbose or frames > 30 * 16000)
    assert kwargs["task"] == "transcribe" and kwargs["language"] is None
    assert kwargs["attention_mask"] is mask and kwargs["temperature"] == 0.4
    assert kwargs["generation_config"].language is None and engine.model.generation_config.language == "zh"
    assert kwargs["generation_config"].task is None and engine.model.generation_config.task == "translate"
    assert kwargs["force_unique_generate_call"] is False
    assert kwargs["generation_config"].num_beams == 4 and kwargs["generation_config"].no_speech_threshold == 0.6
    assert kwargs["prompt_ids"] is engine.processor.get_prompt_ids.return_value.to.return_value
    assert result["segments"] == ([{"id": 0, "start": 32.0, "end": 35.0, "text": "after thirty seconds"}] if verbose else None)


def test_decoder_accepts_large_inputs_mixes_channels_and_counts_decoded_frames(monkeypatch):
    # Represents >32 MiB of decoded float audio without allocating it in deterministic tests.
    audio = MagicMock()
    audio.__len__.return_value = 9 * 1024 * 1024
    source = MagicMock(format="WAV", samplerate=48000)
    source.read.return_value = audio
    source.__enter__.return_value = source
    numpy = SimpleNamespace(float32="float32", isfinite=lambda _: SimpleNamespace(all=lambda: True))
    monkeypatch.setitem(sys.modules, "numpy", numpy)
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(SoundFile=lambda _: source))
    assert asr_engine.decode_audio(Path("recording.wav")) == (audio.mean.return_value, 48000)
    source.read.assert_called_once_with(dtype="float32", always_2d=True)
    audio.mean.assert_called_once_with(axis=1, dtype="float32")
    source.format = "FLAC"
    with pytest.raises(WorkerError, match="INVALID_AUDIO"):
        asr_engine.decode_audio(Path("recording.wav"))
    source.format = "WAV"
    audio.__len__.return_value = 0
    with pytest.raises(WorkerError, match="INVALID_AUDIO"):
        asr_engine.decode_audio(Path("recording.wav"))


def test_migration_extends_constraints_preserving_profiles_and_data(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.RERANKER_REVISION)
    store = ModelProfileStore(engine)
    saved = store.create(profile(kind="llm", source=None, parameters={}))
    with engine.begin() as connection:
        before = list(connection.execute(text("SELECT * FROM model_profiles")).mappings())
    sentinels = [tmp_path / (folder + "/sentinel") for folder in ("data/models", "data/attachments", "data/runtimes")]
    for path in sentinels:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"keep")
    migrations.upgrade(engine, migrations.ASR_REVISION)
    with engine.begin() as connection:
        assert list(connection.execute(text("SELECT * FROM model_profiles")).mappings()) == before
    assert store.get(saved.id).source is None and migrations.current_revision(engine) == migrations.ASR_REVISION
    created = store.create(profile(alias="new-asr"))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE model_profiles SET kind='invalid' WHERE id=:id"), {"id": created.id})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE model_profiles SET source_type='provider', provider_profile_id='x', execution_options_json=NULL, lifecycle_json=NULL WHERE id=:id"), {"id": created.id})
    assert all(path.read_bytes() == b"keep" for path in sentinels)
    engine.dispose()
