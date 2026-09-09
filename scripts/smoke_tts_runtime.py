"""Install ONNX CPU and exercise all local Kokoro voices through the public API."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.workers.tts_catalog import VOICE_IDS

SAMPLES = {
    "a": "Hello, this is a voice test.", "b": "Hello, this is a voice test.",
    "j": "\u3053\u3093\u306b\u3061\u306f\u3002\u97f3\u58f0\u306e\u30c6\u30b9\u30c8\u3067\u3059\u3002",
    "z": "\u4f60\u597d\uff0c\u8fd9\u662f\u4e00\u6b21\u8bed\u97f3\u6d4b\u8bd5\u3002",
    "e": "Hola, esta es una prueba de voz.", "f": "Bonjour, ceci est un test vocal.",
    "h": "\u0928\u092e\u0938\u094d\u0924\u0947\u002c \u092f\u0939 \u0906\u0935\u093e\u091c \u0915\u093e \u092a\u0930\u0940\u0915\u094d\u0937\u0923 \u0939\u0948\u0964",
    "i": "Ciao, questa e una prova vocale.", "p": "Ola, este e um teste de voz.",
}


async def check_disconnect(manager, profile, port, token, voice):
    body = json.dumps({"model": profile.alias, "input": (SAMPLES[voice[0]] * 300)[:4096],
                       "voice": voice, "response_format": "wav", "speed": 0.25}).encode()
    _, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write((f"POST /v1/audio/speech HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {token}\r\n"
                      f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body)
        await writer.drain()
        deadline = asyncio.get_running_loop().time() + 10
        while not manager.status(profile.id).active:
            assert asyncio.get_running_loop().time() < deadline, "Speech never entered the worker queue"
            await asyncio.sleep(0.02)
        adapter = manager._slots[manager.backend_key(profile)].adapter
        process = adapter.process
        await asyncio.sleep(0.1)
        assert manager.status(profile.id).active == 1 and process is not None
    finally:
        writer.close()
        await writer.wait_closed()
    deadline = asyncio.get_running_loop().time() + 10
    while manager.status(profile.id).active:
        assert asyncio.get_running_loop().time() < deadline, "Disconnected speech retained its queue slot"
        await asyncio.sleep(0.02)
    assert manager.status(profile.id).queued == 0
    assert process.process.returncode is not None and adapter.process is None


async def smoke(root, model_ref, install_only, selected):
    engine = get_engine(f"sqlite:///{root / 'data/agent_workbench.db'}")
    init_db(engine)
    supervisor = RuntimeSupervisor(root, RuntimeStore(engine))
    manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=supervisor)
    try:
        job = await supervisor.submit("python-worker", "onnx-cpu", "install")
        last = None
        while supervisor.task and not supervisor.task.done():
            current = supervisor.store.job(job.id)
            if current.stage != last:
                print(json.dumps({"stage": current.stage}), flush=True)
                last = current.stage
            await asyncio.wait({supervisor.task}, timeout=1)
        result = supervisor.store.job(job.id)
        print(json.dumps({"installation_job": result.id, "state": result.state, "error_code": result.error_code}), flush=True)
        if result.state != "completed":
            print(supervisor.log_text(result.id), flush=True)
            raise RuntimeError("ONNX CPU installation failed")
        if install_only:
            return
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        import miniaudio
        from openai import AsyncOpenAI
        import uvicorn
        from ai_workbench.api.routes.openai_compatible import router
        from ai_workbench.core.models.errors import ModelError
        from ai_workbench.core.models.http import InferenceObservabilityMiddleware

        profile = manager.profiles.create(ModelProfile(name="Kokoro smoke", alias="kokoro-smoke", kind="tts",
            runtime_id="python-worker", runtime_variant="onnx-cpu", model_ref=model_ref, external_enabled=True))
        token = secrets.token_urlsafe(32)
        manager.settings.patch({"external_enabled": True, "external_api_key": token})
        app = FastAPI()
        app.state.runtime_state = SimpleNamespace(model_manager=manager, model_profiles=manager.profiles, model_settings=manager.settings)
        app.include_router(router)
        app.add_middleware(InferenceObservabilityMiddleware, repo_root=root)
        @app.exception_handler(ModelError)
        async def error(_request, exc):
            return JSONResponse(exc.payload(), status_code=exc.status)
        output = root / "build/tts-smoke"
        output.mkdir(parents=True, exist_ok=True)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", ws="none"))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                while not server.started:
                    if task.done():
                        await task
                    await asyncio.sleep(0.05)
                async with AsyncOpenAI(base_url=f"http://127.0.0.1:{port}/v1", api_key=token, timeout=310) as client:
                    voices = selected or VOICE_IDS
                    available = {v["id"] for v in manager.voice_list(profile.id) if v["available"]}
                    if not set(voices) <= available:
                        raise RuntimeError("Missing required local voices: " + ", ".join(sorted(set(voices) - available)))
                    for voice in voices:
                        for audio_format in ("wav", "mp3"):
                            response = await client.audio.speech.create(model=profile.alias, input=SAMPLES[voice[0]],
                                voice=voice, response_format=audio_format, speed=1)
                            data = response.content
                            decoded = miniaudio.decode(data, nchannels=1, sample_rate=24000)
                            assert len(decoded.samples) > 100 and any(decoded.samples)
                            (output / f"{voice}.{audio_format}").write_bytes(data)
                            print(json.dumps({"voice": voice, "format": audio_format, "bytes": len(data), "samples": len(decoded.samples)}), flush=True)
                    assert "network access rejected" not in manager.process_log(profile)
                    await check_disconnect(manager, profile, port, token, voices[0])
                    assert "network access rejected" not in manager.process_log(profile)
                    await manager.load(profile.id)
                    recovered = await client.audio.speech.create(model=profile.alias, input=SAMPLES[voices[0][0]],
                        voice=voices[0], response_format="wav")
                    assert miniaudio.decode(recovered.content, nchannels=1, sample_rate=24000).samples
                assert "network access rejected" not in manager.process_log(profile)
                await manager.unload(profile.id)
                print(json.dumps({"voices": len(voices), "formats": 2, "sdk": "passed", "offline": "passed",
                                  "disconnect_cleanup": "passed", "reload": "passed"}), flush=True)
            finally:
                server.should_exit = True
                await task
    finally:
        await manager.close()
        await supervisor.close()
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-ref", default="tts/Kokoro-82M-onnx")
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--voice", action="append", choices=VOICE_IDS)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="workbench-tts-cache-") as cache:
        with patch.dict(os.environ, {"HF_HOME": str(Path(cache) / "hf"), "XDG_CACHE_HOME": str(Path(cache) / "xdg"),
                                     "TMPDIR": cache, "TMP": cache, "TEMP": cache}):
            asyncio.run(smoke(args.root.resolve(), args.model_ref, args.install_only, args.voice))
