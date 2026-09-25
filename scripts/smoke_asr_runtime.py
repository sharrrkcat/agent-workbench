"""Accept supplied Whisper recordings and models using the installed runtime, without model hashes."""
import argparse
import asyncio
from contextlib import suppress
from io import BytesIO
import json
from pathlib import Path
import platform
import re
import secrets
import socket
import time
import wave


def pcm_prefix(data, seconds):
    with wave.open(BytesIO(data), "rb") as source:
        params = source.getparams()
        frames = round(params.framerate * seconds)
        pcm = source.readframes(frames)
    assert params.sampwidth == 2, "Acceptance fixtures must be PCM16 WAV"
    required = frames * params.nchannels * params.sampwidth
    stream = BytesIO()
    with wave.open(stream, "wb") as target:
        target.setparams(params)
        target.writeframes(pcm.ljust(required, b"\0"))
    return stream.getvalue()


def contains(text, phrase):
    words = lambda value: " ".join(re.findall(r"\w+", value.casefold()))
    return words(phrase) in words(text)


async def until(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("Acceptance condition was not reached")
        await asyncio.sleep(0.02)


async def smoke(args):
    import httpx
    import uvicorn
    from ai_workbench.api.deps import build_runtime_state
    from ai_workbench.api.main import create_app
    from ai_workbench.core.models.runtimes.store import RuntimeStore
    from ai_workbench.core.models.schema import TranscriptionRequest
    from ai_workbench.core.models.store import LocalRuntimeSettingsStore
    from ai_workbench.db.database import get_engine, init_db
    from ai_workbench.workers.asr_catalog import load_configuration

    root = args.root.resolve()
    assert platform.system() == "Windows", "Real ASR acceptance currently supports Windows only"
    load_configuration(root / "data/models", args.model_ref)
    audio = args.audio.read_bytes()
    with wave.open(BytesIO(audio), "rb") as source:
        duration, rate = source.getnframes() / source.getframerate(), source.getframerate()
    if args.device == "cuda":
        assert duration > 60, "Use a longer recording with unique speech after 30 seconds"
    output = root / "build/asr-smoke"
    output.mkdir(parents=True, exist_ok=True)
    report_file = output / (Path(args.model_ref).name + "-" + args.device + "-report.json")
    database = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    init_db(database)
    state = build_runtime_state(root=root, use_memory=True)
    manager, supervisor = state.model_manager, state.runtime_supervisor
    supervisor.store, supervisor.settings = RuntimeStore(database), LocalRuntimeSettingsStore(database)
    listener, server, server_task = None, None, None
    report = {"model_ref": args.model_ref, "device": args.device, "platform": platform.platform(),
        "input": str(args.audio), "input_duration": duration, "cases": [], "status": "running"}
    try:
        supervisor.assert_available()
        report["runtime_version"] = supervisor.release.version
        token = secrets.token_urlsafe(32)
        manager.settings.patch({"external_enabled": True, "external_api_key": token})
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(create_app(runtime_state=state), log_level="error", ws="none"))
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        await until(lambda: server.started or server_task.done())
        assert server.started, "Acceptance API server failed to start"
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                timeout=httpx.Timeout(300, read=None), headers={"Authorization": f"Bearer {token}"}, trust_env=False) as client:
            async def call(method, path, **kwargs):
                response = await client.request(method, path, **kwargs)
                assert response.is_success, (response.status_code, response.text)
                return response

            information = (await call("GET", "/api/models/inspect", params={"kind": "asr", "model_ref": args.model_ref})).json()
            assert not information["diagnostics"] and information["architecture"] == "whisper"
            report["information"] = information
            saved = (await call("POST", "/api/models/profiles", json={"name": "ASR acceptance", "alias": "asr-smoke",
                "kind": "asr", "model_ref": args.model_ref, "source": {"type": "local", "execution_options": {"device": args.device}},
                "external_enabled": True})).json()
            profile = manager.profiles.get(saved["id"])
            assert profile.source.lifecycle.unload == "manual"
            assert profile.source.execution_options == {"device": args.device, "intraop_threads": 4}
            assert (await call("GET", "/v1/models", params={"kind": "asr"})).json()["data"][0]["id"] == profile.alias
            route = f"/api/models/profiles/{profile.id}"

            async def infer(label, data, response_format="text", audio_format="wav", **overrides):
                print(json.dumps({"stage": label, "device": args.device, "model_ref": args.model_ref}), flush=True)
                started = time.monotonic()
                response = await call("POST", "/v1/audio/transcriptions", data={"model": profile.alias,
                    "response_format": response_format, **overrides},
                    files={"file": ("input." + audio_format, data, "audio/wav" if audio_format == "wav" else "audio/mpeg")})
                result = {"text": response.text} if response_format == "text" else response.json()
                assert result["text"] and "usage" not in result
                if response_format == "json":
                    assert set(result) == {"text"}
                if response_format == "verbose_json":
                    assert result["task"] == "transcribe" and result["language"] == "en"
                    assert [row["id"] for row in result["segments"]] == list(range(len(result["segments"])))
                    assert all(0 <= row["start"] <= row["end"] <= result["duration"] + 1 for row in result["segments"])
                assert not list(manager.asr_inputs.base.iterdir())
                report["cases"].append({"case": label, "seconds": round(time.monotonic() - started, 3), **result})
                report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                return result

            short = pcm_prefix(audio, 6)
            first = await infer("short", short)
            adapter = manager._managed_slot(profile).adapter
            first_process = adapter.process.process
            metadata = await adapter._rpc("GET", "/health")
            assert metadata["device"] == args.device
            assert metadata["dtype"] == ("torch.float16" if args.device == "cuda" else "torch.float32")
            report["worker"] = {key: metadata[key] for key in ("device", "device_name", "dtype")}
            repeated = await infer("repeat", short, "json", language="auto", prompt="", temperature="0")
            assert repeated["text"] == first["text"] and adapter.process.process is first_process
            if args.device == "cuda":
                for label, seconds in (("below-30", 29), ("exactly-30", 30), ("above-30", 30 + 1 / rate)):
                    await infer(label, pcm_prefix(audio, seconds))
                for response_format in ("text", "json", "verbose_json"):
                    result = await infer("long-" + response_format, audio, response_format,
                        **({"timestamp_granularities[]": "segment"} if response_format == "verbose_json" else {}))
                    assert contains(result["text"], args.tail_text), "Identifiable speech after 30 seconds is missing"
                    if response_format == "verbose_json":
                        assert abs(result["duration"] - duration) < 0.001
                        assert any(row["start"] > 30 and contains(row["text"], args.tail_text) for row in result["segments"])
                if args.mp3:
                    await infer("mp3", args.mp3.read_bytes(), "json", "mp3", language="en", prompt="", temperature="0.2")
                print(json.dumps({"stage": "cancel", "device": args.device}), flush=True)
                pending = asyncio.create_task(manager.transcribe(profile.id, audio, "wav", TranscriptionRequest()))
                await until(lambda: manager.status(profile.id).active == 1 and bool(list(manager.asr_inputs.base.iterdir())))
                await asyncio.sleep(0.1)
                assert not pending.done(), "Inference completed before cancellation was exercised"
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending
                assert first_process.returncode is not None and manager.status(profile.id).active == 0
                assert not list(manager.asr_inputs.base.iterdir())
                report["cancellation"] = "passed"
                await infer("reload-after-cancel", short, "verbose_json")
            else:
                await infer("short-segments", short, "verbose_json", language="en", prompt="", temperature="0")
            process = adapter.process.process
            await call("POST", route + "/unload")
            assert process.returncode is not None and manager.status(profile.id).residency == "unloaded"
            report.update(status="passed", manual_release="passed", input_cleanup="passed")
            print(json.dumps({"asr": "passed", "report": str(report_file)}), flush=True)
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        raise
    finally:
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if server:
            server.should_exit = True
        if server_task:
            await server_task
        if listener:
            listener.close()
        await manager.close()
        await supervisor.close()
        database.dispose()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-ref", required=True, help="Existing native Whisper directory relative to data/models")
    parser.add_argument("--audio", type=Path, required=True, help="Supplied PCM16 WAV; CUDA requires >60 seconds")
    parser.add_argument("--tail-text", help="Unique phrase recorded after 30 seconds; required for CUDA")
    parser.add_argument("--mp3", type=Path, help="Optional supplied MP3 for format acceptance")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args(argv)
    if args.device == "cuda" and not args.tail_text:
        parser.error("CUDA acceptance requires --tail-text to verify the end of long recordings")
    return args


if __name__ == "__main__":
    asyncio.run(smoke(parse_args()))
