import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.store import LocalRuntimeSettingsStore, ProviderProfileStore, ModelProfileStore, ModelSettingsStore
from scripts import smoke_audio_runtime, smoke_cuda_runtime, smoke_llm_runtime, smoke_model_loading, smoke_reranker_runtime, smoke_siglip_runtime, smoke_text_embedding_runtime, smoke_tts_runtime, smoke_wd14_runtime


SCRIPTS = (smoke_audio_runtime, smoke_cuda_runtime, smoke_llm_runtime, smoke_model_loading, smoke_tts_runtime)


def test_reranker_smoke_requires_supplied_models_and_has_no_install_mode():
    model = ["--model-ref", "rerankers/example"]
    for argv in ([], model, [*model, "--device", "cpu", "--install-only"]):
        with pytest.raises(SystemExit):
            smoke_reranker_runtime.parse_args(argv)
    assert smoke_reranker_runtime.parse_args([*model, "--device", "cpu"]).device == "cpu"
    cuda = smoke_reranker_runtime.parse_args([*model, "--embedding-model-ref", "embeddings/example"])
    assert cuda.device == "cuda" and cuda.embedding_model_ref == "embeddings/example"


def test_text_embedding_smoke_requires_a_model_and_preserves_device_scope():
    model = ["--model-ref", "embeddings/example"]
    for argv in ([], [*model, "--install-only"], [*model, "--device", "cpu", "--native-reference"]):
        with pytest.raises(SystemExit):
            smoke_text_embedding_runtime.parse_args(argv)
    assert smoke_text_embedding_runtime.parse_args(model).device == "cuda"
    assert smoke_text_embedding_runtime.parse_args([*model, "--device", "cpu"]).device == "cpu"


def test_siglip_smoke_requires_a_model_and_has_no_cpu_or_install_mode():
    for argv in ([], ["--model-ref", "image_embeddings/test", "--device", "cpu"],
                 ["--model-ref", "image_embeddings/test", "--install-only"]):
        with pytest.raises(SystemExit):
            smoke_siglip_runtime.parse_args(argv)
    assert smoke_siglip_runtime.parse_args(["--model-ref", "image_embeddings/test"]).model_ref == "image_embeddings/test"


def test_wd14_requires_an_explicit_model_and_never_installs(tmp_path, monkeypatch):
    for argv in ([], ["--model-ref", "vision/test", "--install-only"]):
        with pytest.raises(SystemExit):
            smoke_wd14_runtime.parse_args(argv)
    assert smoke_wd14_runtime.parse_args(["--model-ref", "vision/test"]).model_ref == "vision/test"
    supervisor = SimpleNamespace(submit=AsyncMock(), close=AsyncMock(),
        assert_available=Mock(side_effect=ModelError("RUNTIME_BROKEN", "Repair the local backend", 503)))
    manager = SimpleNamespace(close=AsyncMock())
    engine = SimpleNamespace(dispose=Mock())
    monkeypatch.setattr(smoke_wd14_runtime, "get_engine", lambda *_: engine)
    monkeypatch.setattr(smoke_wd14_runtime, "init_db", lambda *_: None)
    monkeypatch.setattr(smoke_wd14_runtime, "RuntimeStore", lambda *_: None)
    monkeypatch.setattr(smoke_wd14_runtime, "LocalRuntimeSettingsStore", lambda *_: None)
    monkeypatch.setattr(smoke_wd14_runtime, "build_runtime_state",
        lambda **_: SimpleNamespace(runtime_supervisor=supervisor, model_manager=manager))
    with pytest.raises(ModelError, match="Repair"):
        asyncio.run(smoke_wd14_runtime.smoke(tmp_path, "vision/test"))
    supervisor.assert_available.assert_called_once_with()
    supervisor.submit.assert_not_called()
    manager.close.assert_awaited_once()
    engine.dispose.assert_called_once_with()


def test_audio_and_loading_defaults_preserve_explicit_cpu_selection():
    assert smoke_audio_runtime.parse_args([]).device == ["cuda"]
    assert smoke_audio_runtime.parse_args(["--device", "cpu"]).device == ["cpu"]
    assert smoke_audio_runtime.parse_args(["--device", "cuda", "--device", "cpu"]).device == ["cuda", "cpu"]
    defaults = smoke_model_loading.parse_args([]).backend
    assert set(defaults) == {"llama-cpu", "llama-cuda", "transformers-cpu", "transformers-cuda", "kokoro", "chatterbox-cuda", "qwen3tts-cuda"}
    assert smoke_model_loading.parse_args(["--backend", "qwen3tts-cpu"]).backend == ["qwen3tts-cpu"]
    assert smoke_llm_runtime.parse_args([]).device == "both"


def test_vision_smoke_requires_explicit_gguf_projector_and_checks_answers():
    assert smoke_llm_runtime.parse_args(["--vision"]).vision
    args = smoke_llm_runtime.parse_args(["--vision", "--engine", "llama-server", "--mmproj-ref", "llms/mmproj.gguf"])
    assert args.mmproj_ref == "llms/mmproj.gguf"
    for argv in (["--vision", "--engine", "llama-server"], ["--mmproj-ref", "llms/mmproj.gguf"]):
        with pytest.raises(SystemExit):
            smoke_llm_runtime.parse_args(argv)
    smoke_llm_runtime.check_colors("First: red. Second: blue.", ["red", "blue"])
    for answer in ("A colorful image.", "<think>red and blue</think>No answer.", "First blue, second red."):
        with pytest.raises(AssertionError):
            smoke_llm_runtime.check_colors(answer, ["red", "blue"])


@pytest.mark.parametrize("script", SCRIPTS)
def test_obsolete_skip_install_option_is_rejected(script):
    with pytest.raises(SystemExit) as error:
        script.parse_args(["--skip-install"])
    assert error.value.code == 2


def test_cuda_requires_a_model_unless_installation_is_explicit():
    with pytest.raises(SystemExit) as error:
        smoke_cuda_runtime.parse_args([])
    assert error.value.code == 2
    assert smoke_cuda_runtime.parse_args(["--install-only"]).install_only
    assert smoke_cuda_runtime.parse_args(["--model-ref", "llms/local.gguf"]).model_ref == "llms/local.gguf"


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("install_only", [False, True])
def test_smoke_modes_separate_installation_from_inference(tmp_path, monkeypatch, script, install_only):
    job = SimpleNamespace(id="job", version="1", state="completed", error_code=None)
    store = SimpleNamespace(job=lambda _: job)
    providers = ProviderProfileStore()
    settings = LocalRuntimeSettingsStore()
    supervisor = SimpleNamespace(store=store, settings=settings, task=None, release=SimpleNamespace(version="1"),
        submit=AsyncMock(return_value=job), close=AsyncMock(),
        assert_available=Mock(side_effect=ModelError("RUNTIME_BROKEN", "Repair the local backend", 503)))
    manager = SimpleNamespace(close=AsyncMock(), profiles=ModelProfileStore(), settings=ModelSettingsStore(),
        load=AsyncMock(side_effect=AssertionError("Unexpected inference")), process_log=lambda _: "")
    state = SimpleNamespace(runtime_supervisor=supervisor, model_manager=manager)
    engine = SimpleNamespace(dispose=Mock())
    monkeypatch.setattr(script, "get_engine", lambda *_: engine)
    monkeypatch.setattr(script, "RuntimeStore", lambda *_: store)
    if hasattr(script, "ProviderProfileStore"):
        monkeypatch.setattr(script, "ProviderProfileStore", lambda *_: providers)
    monkeypatch.setattr(script, "LocalRuntimeSettingsStore", lambda *_: settings)
    if hasattr(script, "init_db"):
        monkeypatch.setattr(script, "init_db", lambda *_: None)
    if hasattr(script, "platform"):
        monkeypatch.setattr(script.platform, "system", lambda: "Windows")
    if hasattr(script, "migrations"):
        monkeypatch.setattr(script.migrations, "current_revision", lambda *_: script.migrations.HEAD_REVISION)
    if hasattr(script, "build_runtime_state"):
        monkeypatch.setattr(script, "build_runtime_state", lambda **_: state)
    if hasattr(script, "RuntimeSupervisor"):
        monkeypatch.setattr(script, "RuntimeSupervisor", lambda *_: supervisor)
        monkeypatch.setattr(script, "ModelManager", lambda *_, **__: manager)
    argv = ["--root", str(tmp_path)] + (["--install-only"] if install_only else [])
    if script is smoke_cuda_runtime:
        argv += ["--model-ref", "llms/local.gguf"]
    if script is smoke_model_loading:
        argv += ["--backend", "chatterbox-cuda"]
    args = script.parse_args(argv)
    if script is smoke_audio_runtime:
        call = script.smoke(args)
    elif script is smoke_llm_runtime:
        call = script.smoke(tmp_path, "llms/local.gguf", ("cuda",), install_only, "llama-server")
    elif script is smoke_tts_runtime:
        call = script.smoke(tmp_path, "tts/kokoro", install_only, None)
    elif script is smoke_cuda_runtime:
        call = script.smoke(tmp_path, args.model_ref, install_only)
    else:
        call = script.main(args)
    if install_only:
        asyncio.run(call)
        supervisor.submit.assert_awaited_once_with("install")
        supervisor.assert_available.assert_not_called()
    else:
        expected = RuntimeError if script is smoke_model_loading else ModelError
        with pytest.raises(expected):
            asyncio.run(call)
        supervisor.assert_available.assert_called_once_with()
        supervisor.submit.assert_not_called()
    manager.load.assert_not_called()
    engine.dispose.assert_called_once_with()
