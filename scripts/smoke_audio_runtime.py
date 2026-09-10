"""Windows Audio installation and offline three-engine acceptance."""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import time
from types import SimpleNamespace
import wave

import httpx
import uvicorn

from ai_workbench.api.deps import build_runtime_state
from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.manager import ProviderSlot
from ai_workbench.core.models.runtimes.adapters import AudioWorkerAdapter
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.db.database import get_engine, init_db
from scripts.smoke_transformers_runtime import until


async def smoke(args):
    if platform.system() != "Windows":
        raise RuntimeError("This acceptance command supports Windows only")
    root = args.root.resolve()
    engine = get_engine(f"sqlite:///{root / 'data/agent_workbench.db'}")
    init_db(engine)
    state = build_runtime_state(root=root, use_memory=True)
    supervisor = state.runtime_supervisor
    supervisor.store = RuntimeStore(engine)
    try:
        if not args.skip_install:
            job = await supervisor.submit("python-worker", "audio-cuda", "install")
            previous = None
            while supervisor.task and not supervisor.task.done():
                current = supervisor.store.job(job.id)
                progress = (current.stage, current.progress_current // (64 * 1024 * 1024))
                if progress != previous:
                    print(json.dumps({"stage": current.stage, "bytes": current.progress_current}), flush=True)
                    previous = progress
                await asyncio.wait({supervisor.task}, timeout=1)
            result = supervisor.store.job(job.id)
            print(json.dumps({"installation_job": result.id, "state": result.state, "error_code": result.error_code}), flush=True)
            if result.state != "completed":
                print(supervisor.log_text(result.id), flush=True)
                raise RuntimeError("Audio installation failed")
        if not args.install_only:
            await validate_engines(state, args)
    finally:
        await state.model_manager.close()
        await supervisor.close()
        engine.dispose()


async def checked(client, method, path, **kwargs):
    response = await client.request(method, path, **kwargs)
    if response.is_error:
        raise RuntimeError(f"{path}: {response.status_code} {response.text}")
    return response


@asynccontextmanager
async def reference_file(manager, data, audio_format):
    entry = await manager._stage_reference(data, audio_format)
    try:
        yield entry
    finally:
        await asyncio.to_thread(manager.voice_references.release, entry)


async def save_audio(manager, adapter, profile, output, data, audio_format):
    output.write_bytes(data)
    async with reference_file(manager, data, audio_format) as entry:
        decoded = await adapter.validate_reference(profile, entry.path.name)
    assert decoded["frames"] > 0 and decoded["sample_rate"] == 24000, decoded
    return {"bytes": len(data), **decoded}


async def unavailable_cuda(adapter, profile):
    old = os.environ.get("CUDA_VISIBLE_DEVICES")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    try:
        try:
            await adapter.load(profile, explicit=True)
        except ModelError as exc:
            assert exc.code == "RUNTIME_DEVICE_UNAVAILABLE", exc.code
        else:
            raise AssertionError("Unavailable CUDA was silently substituted")
    finally:
        if old is None:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        else:
            os.environ["CUDA_VISIBLE_DEVICES"] = old
        await adapter.unload(profile)


def check_device(metadata, device):
    assert metadata["device"] == device, metadata
    assert metadata["device_name"] and metadata["dtype"], metadata
    if device == "cpu":
        assert metadata["dtype"] == "torch.float32", metadata


def offline_files(adapter):
    cache = adapter.run_dir / "cache"
    # Diffusers records its cache-format version during an offline import.
    files = {path.relative_to(cache).as_posix() for path in cache.rglob("*") if path.is_file()}
    assert files <= {"hub/version_diffusers_cache.txt"}, f"Unexpected model cache files: {sorted(files)}"
    assert "network access rejected" not in adapter.log_path.read_text(encoding="utf-8", errors="replace")


async def reference_tts(state, client, args, architecture, device, reference, output, keeper):
    manager = state.model_manager
    qwen = architecture == "qwen3tts"
    created = (await checked(client, "POST", "/api/models/profiles", json={
        "name": f"{architecture} {device}", "alias": f"{architecture}-{device}", "kind": "tts",
        "runtime_id": "python-worker", "runtime_variant": "audio-cuda", "model_ref": getattr(args, architecture),
        "runtime_options": {"device": device}, "parameters": {"architecture": architecture, "response_format": "wav"},
        "external_enabled": True})).json()
    profile = manager.profiles.get(created["id"])
    uploaded = (await checked(client, "POST", "/v1/audio/voice-references", data={"model": profile.alias},
        files={"file": (reference.name, reference.read_bytes())})).json()
    voice_id = uploaded["voice_id"]
    transcript_voice = None
    if qwen:
        transcript_voice = (await checked(client, "POST", "/v1/audio/voice-references",
            data={"model": profile.alias, "reference_text": args.reference_text},
            files={"file": (reference.name, reference.read_bytes())})).json()["voice_id"]
    voices = (await checked(client, "GET", "/v1/audio/voices", params={"model": profile.alias, "source": "temporary"})).json()
    assert voices["data"][0]["id"] == voice_id
    assert all(item["language"] == (None if qwen else "en-US") and "reference_text" not in item for item in voices["data"])
    assert (await checked(client, "GET", "/v1/audio/voices", params={"model": profile.alias, "source": "preset"})).json()["data"] == []
    adapter = manager._slots[manager.backend_key(profile)].adapter
    # Unavailable-device validation must start a fresh process with hidden GPUs.
    if device == "cuda":
        await adapter.unload(profile)
        await unavailable_cuda(adapter, profile)
    await manager.load(profile.id)
    metadata = (await adapter.client.get("/health")).json()
    check_device(metadata, device)
    results = {}
    for audio_format in ("wav", "mp3"):
        conditioning = qwen and audio_format == "mp3"
        extensions = {"language": "zh-CN" if conditioning else "en-US", "model_options": {"max_new_tokens": 128}} if qwen else {}
        response = await checked(client, "POST", "/v1/audio/speech", json={"model": profile.alias,
            "input": "你好，世界。" if conditioning else "Hello from the local audio runtime.",
            "voice": transcript_voice if conditioning else voice_id, "response_format": audio_format,
            "speed": 0.9 if conditioning else 1, "tts": extensions})
        assert response.headers["x-request-id"]
        results[audio_format] = await save_audio(manager, adapter, profile,
            output / f"{architecture}-{device}.{audio_format}", response.content, audio_format)
    assert manager.status(profile.id).residency == "loaded"
    offline_files(adapter)
    process = adapter.process
    pending = asyncio.create_task(client.post("/v1/audio/speech", json={"model": profile.alias,
        "input": "This request will be cancelled. " * 80, "voice": voice_id}))
    await until(lambda: manager.status(profile.id).active == 1)
    conflict = await client.delete(f"/v1/audio/voice-references/{voice_id}")
    assert conflict.status_code == 409, conflict.text
    await asyncio.sleep(0.2)
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    await until(lambda: manager.status(profile.id).active == 0)
    assert process.process.returncode is not None and adapter.process is None
    assert keeper.process and keeper.process.process.returncode is None
    await manager.load(profile.id)
    for transcript in ([None, args.reference_text] if qwen else [None]):
        reference_audio = {"format": reference.suffix[1:], "data_base64": base64.b64encode(reference.read_bytes()).decode()}
        if transcript is not None:
            reference_audio["reference_text"] = transcript
        one_shot = await checked(client, "POST", "/v1/audio/speech", json={"model": profile.alias, "input": "Hello again.",
            "tts": {"reference_audio": reference_audio, "language": "auto" if qwen else "en-US",
                    "model_options": {"max_new_tokens": 128, "temperature": 0.8, "top_k": 40} if qwen else {"exaggeration": 0.4}}})
        mode = "transcript" if transcript is not None else "audio-only"
        results[f"inline-{mode}"] = await save_audio(manager, adapter, profile,
            output / f"{architecture}-{device}-reload-{mode}.wav", one_shot.content, "wav")
    await checked(client, "DELETE", f"/v1/audio/voice-references/{voice_id}")
    if transcript_voice:
        await checked(client, "DELETE", f"/v1/audio/voice-references/{transcript_voice}")
    assert (await checked(client, "GET", "/v1/audio/voices", params={"model": profile.alias})).json()["data"] == []
    process = adapter.process
    await manager.unload(profile.id)
    assert process.process.returncode is not None
    return {"metadata": metadata, "outputs": results, "http_disconnect": "passed", "reference_api": "passed",
            "manual_unload": "passed", "unrelated_worker": "preserved",
            **({"cloning_modes": ["audio-only", "audio-and-transcript"], "languages": ["en-US", "zh-CN", "auto"]} if qwen else {})}


async def whisper(state, args, device, reference, output, keeper):
    manager = state.model_manager
    # Whisper alone remains private acceptance tooling, outside public ModelInput.
    profile = SimpleNamespace(id=f"acceptance-whisper-{device}", kind="asr",
        runtime_id="python-worker", runtime_variant="audio-cuda", model_ref=args.whisper,
        parameters={"architecture": "whisper"}, runtime_options={"device": device, "intraop_threads": 4})
    adapter = AudioWorkerAdapter(state.runtime_supervisor, profile, lambda: None)
    adapter.validation = True
    backend = manager.backend_key(profile)
    manager._slots[backend] = ProviderSlot(adapter, asyncio.Semaphore(1))

    async def call(operation):
        async with manager._provider_lease(backend, (backend, profile.id), profile, require_runtime=False):
            return await operation

    try:
        if device == "cuda":
            await unavailable_cuda(adapter, profile)
        await call(adapter.load(profile, explicit=True))
        metadata = (await adapter.client.get("/health")).json()
        check_device(metadata, device)
        results = {}
        async with reference_file(manager, reference.read_bytes(), reference.suffix[1:]) as entry:
            for label, frames in (("below", 29 * 24000), ("exactly", 30 * 24000), ("above", 30 * 24000 + 1)):
                path = output / f"whisper-{label}.wav"
                with wave.open(str(reference), "rb") as source:
                    assert source.getparams()[:3] == (1, 2, 24000), "Whisper acceptance reference must be mono PCM16 at 24 kHz"
                    pcm = source.readframes(source.getnframes())
                with wave.open(str(path), "wb") as target:
                    target.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                    target.writeframes((pcm * (frames * 2 // len(pcm) + 1))[:frames * 2])
                async with reference_file(manager, path.read_bytes(), "wav") as bounded:
                    try:
                        result = await call(adapter.transcribe(profile, bounded.path.name))
                    except ModelError as exc:
                        assert label == "above" and exc.code == "AUDIO_TOO_LONG", exc.code
                        results[label] = "AUDIO_TOO_LONG"
                    else:
                        assert label != "above" and isinstance(result["text"], str), result
                        results[label] = result
            operation = adapter.transcribe(profile, entry.path.name)
            offline_files(adapter)
            process = adapter.process
            pending = asyncio.create_task(call(operation))
            await until(lambda: manager._slots[backend].active == 1)
            await asyncio.sleep(0.1)
            assert not pending.done(), "Inference completed before cancellation could be exercised"
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            assert process.process.returncode is not None and manager._slots[backend].active == 0
            assert keeper.process and keeper.process.process.returncode is None
            await call(adapter.load(profile, explicit=True))
            process = adapter.process
            await call(adapter.unload(profile))
            assert process.process.returncode is not None
        return {"metadata": metadata, "outputs": results, "cancellation": "passed", "manual_unload": "passed",
                "unrelated_worker": "preserved"}
    finally:
        await adapter.close()
        manager._slots.pop(backend, None)


async def validate_engines(state, args):
    manager = state.model_manager
    root = args.root.resolve()
    reference = (args.reference or root / "build/tts-smoke/af_heart.wav").resolve()
    if not reference.is_file():
        raise RuntimeError("Supply --reference with a local speech WAV; no audio is downloaded")
    if (not args.engine or "qwen3tts" in args.engine) and (not args.reference_text or not args.reference_text.strip()):
        raise RuntimeError("Qwen acceptance requires --reference-text matching the reference recording")
    output = root / "build/audio-smoke"
    output.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    manager.settings.patch({"external_enabled": True, "external_api_key": token})
    report = {"platform": "windows", "runtime_version": state.runtime_supervisor.entry("python-worker", "audio-cuda").version,
              "models": {name: getattr(args, name) for name in ("chatterbox", "qwen3tts", "whisper")}, "results": []}
    keeper_profile = manager.profiles.create(ModelProfile(name="Audio isolation witness", alias="audio-witness", kind="tts",
        runtime_id="python-worker", runtime_variant="audio-cuda", model_ref=args.chatterbox,
        parameters={"architecture": "chatterbox"}, runtime_options={"device": "cpu"}))
    # Start only the reference decoder in this witness, keeping its process alive without weights.
    _, keeper_slot = manager._slot(manager.backend_key(keeper_profile), keeper_profile)
    keeper = keeper_slot.adapter
    async with reference_file(manager, reference.read_bytes(), reference.suffix[1:]) as entry:
        await keeper.validate_reference(keeper_profile, entry.path.name)
    app = create_app(runtime_state=state)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", ws="none"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            await until(lambda: server.started)
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=360, trust_env=False,
                    headers={"Authorization": f"Bearer {token}"}) as client:
                for device in args.device or ["cpu", "cuda"]:
                    for architecture in args.engine or ["chatterbox", "qwen3tts", "whisper"]:
                        started = time.monotonic()
                        print(json.dumps({"engine": architecture, "device": device, "state": "running"}), flush=True)
                        result = {"engine": architecture, "device": device}
                        try:
                            result.update(await whisper(state, args, device, reference, output, keeper) if architecture == "whisper"
                                else await reference_tts(state, client, args, architecture, device, reference, output, keeper))
                            result["state"] = "passed"
                        except Exception as exc:
                            result.update(state="failed", error=str(exc))
                            for slot in manager._slots.values():
                                if slot.adapter is not keeper:
                                    if slot.adapter.log_path and slot.adapter.log_path.exists():
                                        print(slot.adapter.log_path.read_text(encoding="utf-8", errors="replace")[-4000:], flush=True)
                                    await slot.adapter.close()
                        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
                        report["results"].append(result)
                        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                        print(json.dumps(result), flush=True)
        finally:
            server.should_exit = True
            await task
    if any(result["state"] != "passed" for result in report["results"]):
        raise RuntimeError("Audio acceptance failed; see build/audio-smoke/report.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--device", choices=("cpu", "cuda"), action="append")
    parser.add_argument("--engine", choices=("chatterbox", "qwen3tts", "whisper"), action="append")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--reference-text", help="Transcript of --reference; required for Qwen Base full-conditioning acceptance")
    parser.add_argument("--chatterbox", default="tts/chatterbox")
    parser.add_argument("--qwen3tts", default="tts/Qwen3-TTS-12Hz-0.6B-Base")
    parser.add_argument("--whisper", default="asr/whisper-base")
    args = parser.parse_args()
    asyncio.run(smoke(args))
