import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.store import BackendProfileStore, ModelProfileStore, ModelSettingsStore
from scripts import smoke_audio_runtime, smoke_cuda_runtime, smoke_llm_runtime, smoke_model_loading, smoke_tts_runtime


SCRIPTS = (smoke_audio_runtime, smoke_cuda_runtime, smoke_llm_runtime, smoke_model_loading, smoke_tts_runtime)


def test_audio_and_loading_defaults_preserve_explicit_cpu_selection():
    assert smoke_audio_runtime.parse_args([]).device == ["cuda"]
    assert smoke_audio_runtime.parse_args(["--device", "cpu"]).device == ["cpu"]
    assert smoke_audio_runtime.parse_args(["--device", "cuda", "--device", "cpu"]).device == ["cuda", "cpu"]
    defaults = smoke_model_loading.parse_args([]).backend
    assert set(defaults) == {"llama-cpu", "llama-cuda", "transformers-cpu", "transformers-cuda", "kokoro", "chatterbox-cuda", "qwen3tts-cuda"}
    assert smoke_model_loading.parse_args(["--backend", "qwen3tts-cpu"]).backend == ["qwen3tts-cpu"]
    assert smoke_llm_runtime.parse_args([]).device == "both"


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
    backends = BackendProfileStore()
    supervisor = SimpleNamespace(store=store, backends=backends, task=None, release=SimpleNamespace(version="1"),
        submit=AsyncMock(return_value=job), close=AsyncMock(),
        assert_available=Mock(side_effect=ModelError("RUNTIME_BROKEN", "Repair the local backend", 503)))
    manager = SimpleNamespace(close=AsyncMock(), profiles=ModelProfileStore(), settings=ModelSettingsStore(),
        load=AsyncMock(side_effect=AssertionError("Unexpected inference")), process_log=lambda _: "")
    state = SimpleNamespace(runtime_supervisor=supervisor, model_manager=manager)
    engine = SimpleNamespace(dispose=Mock())
    monkeypatch.setattr(script, "get_engine", lambda *_: engine)
    monkeypatch.setattr(script, "RuntimeStore", lambda *_: store)
    monkeypatch.setattr(script, "BackendProfileStore", lambda *_: backends)
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
