"""Measure first load/reload and minimal inference using existing local models."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
import platform
import secrets
import time
from unittest.mock import patch

from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes import supervisor as runtime_module
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.schema import ChatRequest, ModelProfile, SpeechRequest
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.core.models.voice_references import credential_id
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.workers.timing import TIMING_PREFIX
from ai_workbench.workers.tts_catalog import LANGUAGES

BACKENDS = ("llama-cpu", "llama-cuda", "transformers-cpu", "transformers-cuda", "kokoro",
            "chatterbox-cpu", "chatterbox-cuda", "qwen3tts-cpu", "qwen3tts-cuda")


def forbidden(*_args, **_kwargs):
    raise AssertionError("Installation verification or cache access occurred during model execution")


class ForbiddenCache(dict):
    get = __getitem__ = __contains__ = __setitem__ = pop = forbidden


def timing_records(text):
    records = []
    for line in text.splitlines():
        if TIMING_PREFIX in line:
            records.append(json.loads(line.split(TIMING_PREFIX, 1)[1]))
    return records


async def install(root, engine):
    supervisor = RuntimeSupervisor(root, RuntimeStore(engine))
    try:
        for variant in ("onnx-cpu", "transformers-cuda", "audio-cuda"):
            job = await supervisor.submit("python-worker", variant, "install")
            previous = None
            while supervisor.task and not supervisor.task.done():
                current = supervisor.store.job(job.id)
                progress = (current.stage, current.progress_current // (64 * 1024 * 1024))
                if progress != previous:
                    print(json.dumps({"variant": variant, "stage": current.stage, "bytes": current.progress_current}), flush=True)
                    previous = progress
                await asyncio.wait({supervisor.task}, timeout=1)
            result = supervisor.store.job(job.id)
            print(json.dumps({"variant": variant, "version": result.version, "job_id": result.id,
                              "state": result.state, "error_code": result.error_code}), flush=True)
            if result.state != "completed":
                print(supervisor.log_text(job.id)[-6000:], flush=True)
                raise RuntimeError("Runtime installation failed")
    finally:
        await supervisor.close()


def profile_for(backend, args):
    if backend.startswith("llama-"):
        return ModelProfile(name=backend, alias=backend, kind="llm", runtime_id="llama-server",
            runtime_variant=backend.removeprefix("llama-"), model_ref=args.gguf_model)
    if backend.startswith("transformers-"):
        return ModelProfile(name=backend, alias=backend, kind="llm", runtime_id="python-worker",
            runtime_variant="transformers-cuda", runtime_options={"device": backend.removeprefix("transformers-")},
            model_ref=args.transformers_model)
    if backend == "kokoro":
        return ModelProfile(name=backend, alias=backend, kind="tts", runtime_id="python-worker",
            runtime_variant="onnx-cpu", model_ref=args.kokoro_model)
    architecture, device = backend.rsplit("-", 1)
    return ModelProfile(name=backend, alias=backend, kind="tts", runtime_id="python-worker",
        runtime_variant="audio-cuda", model_ref=getattr(args, architecture + "_model"),
        runtime_options={"device": device}, parameters={"architecture": architecture}, external_enabled=True)


async def minimal_inference(manager, profile, args, voice):
    if profile.kind == "llm":
        reply = await manager.chat(profile.id, ChatRequest(model=profile.alias, temperature=0, max_tokens=16,
            messages=[{"role": "user", "content": "Say hello."}]))
        assert reply.message.content or reply.message.reasoning_content
        return {"kind": "chat", "state": "passed"}, voice
    if profile.runtime_variant == "audio-cuda" and voice is None:
        reference = (args.reference or args.root / "build/tts-smoke/af_heart.wav").resolve()
        created = await manager.create_voice_reference(profile.id, reference.read_bytes(), reference.suffix[1:],
            credential_id(manager.settings.get().external_api_key))
        voice = created["voice_id"]
    result = await manager.speech(profile.id, SpeechRequest(model=profile.alias, input="Hello from Workbench.",
        voice=voice or "af_heart", response_format="wav"))
    assert result.data.startswith(b"RIFF") and len(result.data) > 44
    return {"kind": "speech", "state": "passed", "bytes": len(result.data)}, voice


def summarize(text, backend):
    records = timing_records(text)
    assert all(math.isfinite(item[field]) and item[field] >= 0 for item in records
               for field in ("cpu_duration_ms", "cpu_elapsed_ms")), "Expected per-process CPU timing on every stage"
    totals = [item for item in records if item["scope"] == "host" and item["stage"] == "load_total"
              and item["result"] == "completed"]
    assert len(totals) == 1, "Expected exactly one successful load total"
    load_id = totals[0]["load_id"]
    completed = [item for item in records if item["load_id"] == load_id and item["result"] == "completed"]
    host = {item["stage"] for item in completed if item["scope"] == "host"}
    worker = {item["stage"] for item in completed if item["scope"] == "worker"}
    assert {"queue_wait", "execution_entry", "model_resources", "process_spawn", "ready_wait"} <= host
    if backend.startswith("llama-"):
        assert "model_advertisement" in host
        if backend == "llama-cuda":
            assert {"cuda_probe", "cuda_offload_confirmation"} <= host
    elif backend == "kokoro":
        assert {"engine_imports", "tokenizer", "onnx_session", "language_frontends", "language_resources", "worker_load"} <= worker
        assert {f"engine_imports.{name}" for name in ("numpy", "onnxruntime", "tokenizers", "lameenc")} <= worker
        assert {f"language_imports.{name}" for name in
                ("importlib_metadata", "spacy", "misaki.en", "misaki.espeak", "misaki.zh", "misaki.cutlet", "jieba")} <= worker
        assert all(f"language.{language}.{step}" in worker for language in LANGUAGES.values() for step in ("build", "warmup"))
    elif backend.startswith("transformers-"):
        assert {"engine_imports", "device_init", "processor", "weights", "post_load", "worker_startup"} <= worker
        assert {"engine_imports.torch", *[f"engine_imports.transformers.{name}" for name in
                ("AutoConfig", "AutoModelForCausalLM", "AutoModelForMultimodalLM", "AutoProcessor",
                 "serving.chat_completion", "serving.model_manager", "serving.utils", "modeling_auto", "logging")]} <= worker
    else:
        assert {"engine_imports", "device_init", "post_load", "worker_load"} <= worker
        assert ("model_from_local" if backend.startswith("chatterbox-") else "model_from_pretrained") in worker
    return {"load_id": load_id, "load_seconds": round(totals[0]["duration_ms"] / 1000, 3),
            "host_cpu_seconds": round(totals[0]["cpu_duration_ms"] / 1000, 3),
            "process_reused": totals[0].get("process_reused"), "model_reused": totals[0].get("model_reused"),
            "stages": [{"scope": item["scope"], "stage": item["stage"], "seconds": round(item["duration_ms"] / 1000, 3),
                        "cpu_seconds": round(item["cpu_duration_ms"] / 1000, 3)}
                       for item in completed]}


async def validate(root, engine, backend, args, output):
    supervisor = RuntimeSupervisor(root, RuntimeStore(engine))
    manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=supervisor)
    manager.settings.patch({"external_enabled": True, "external_api_key": secrets.token_urlsafe(32)})
    profile = manager.profiles.create(profile_for(backend, args))
    result = {"backend": backend, "model_ref": profile.model_ref,
              "runtime_version": supervisor.entry(profile.runtime_id, profile.runtime_variant).version, "rounds": []}
    supervisor._verified = ForbiddenCache()
    voice = None
    try:
        with patch.object(supervisor, "verify", side_effect=forbidden), patch.object(runtime_module, "runtime_inventory", forbidden), patch.object(runtime_module, "sha256", forbidden):
            for name in ("first", "reload"):
                print(json.dumps({"backend": backend, "round": name, "state": "loading"}), flush=True)
                started = time.perf_counter()
                loaded = await manager.load(profile.id)
                wall_seconds = time.perf_counter() - started
                assert loaded.state == "ready" and loaded.residency == "loaded"
                if backend == "llama-cuda":
                    assert loaded.runtime.gpu_layers_loaded > 0
                adapter = manager._managed_slot(profile).adapter
                log_path = adapter.log_paths[profile.id]
                inference, voice = await minimal_inference(manager, profile, args, voice)
                await manager.unload(profile.id)
                assert manager.status(profile.id).residency == "unloaded" and adapter.process is None
                text = log_path.read_text(encoding="utf-8")
                target = output / f"{backend}-{name}.log"
                target.write_text(text, encoding="utf-8")
                measured = {"round": name, "wall_seconds": round(wall_seconds, 3), **summarize(text, backend),
                            "inference": inference, "log": target.relative_to(root).as_posix()}
                result["rounds"].append(measured)
                print(json.dumps({"backend": backend, "round": name, "state": "passed",
                                  "load_seconds": measured["load_seconds"]}), flush=True)
        result.update(state="passed", installation_verification="not_called")
    except Exception as exc:
        result.update(state="failed", error_code=getattr(exc, "code", None), error_type=type(exc).__name__)
        text = manager.process_log(profile)
        (output / f"{backend}-failed.log").write_text(text, encoding="utf-8")
        print(json.dumps({"backend": backend, "state": "failed", "error_type": type(exc).__name__,
                          "error_code": getattr(exc, "code", None)}), flush=True)
        print(text[-6000:], flush=True)
    finally:
        await manager.close()
        await supervisor.close()
    return result


async def main(args):
    args.root = args.root.resolve()
    if platform.system() != "Windows":
        raise RuntimeError("This real-model matrix currently targets Windows")
    engine = get_engine(f"sqlite:///{args.root / 'data/agent_workbench.db'}")
    try:
        if migrations.current_revision(engine) != migrations.HEAD_REVISION:
            raise RuntimeError("Upgrade the database to Alembic head before acceptance")
        if args.install_only:
            await install(args.root, engine)
            return
        output = args.root / "build/model-loading-smoke"
        output.mkdir(parents=True, exist_ok=True)
        report = {"platform": "windows", "results": [], "timing_note":
                  "Nested stages overlap; load totals exclude inference. CPU time includes all process threads, excludes child processes, and may exceed wall time."}
        for backend in args.backend or BACKENDS:
            report["results"].append(await validate(args.root, engine, backend, args, output))
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if any(item["state"] != "passed" for item in report["results"]):
            raise RuntimeError("Model loading acceptance failed; see build/model-loading-smoke/report.json")
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--backend", choices=BACKENDS, action="append")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--gguf-model", default="llms/Qwen3.5-0.8B-GGUF/Qwen3.5-0.8B-Q4_K_M.gguf")
    parser.add_argument("--transformers-model", default="llms/Qwen3.5-0.8B-TF")
    parser.add_argument("--kokoro-model", default="tts/Kokoro-82M-onnx")
    parser.add_argument("--chatterbox-model", default="tts/chatterbox")
    parser.add_argument("--qwen3tts-model", default="tts/Qwen3-TTS-12Hz-0.6B-Base")
    asyncio.run(main(parser.parse_args()))
