"""Public multipart transcription, request files and actual isolated worker processes."""
import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import json
import re
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
import wave

import httpx
import psutil
import pytest

from ai_workbench.core.models.asr_inputs import ASRInputs
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.adapters import ASRWorkerAdapter
from ai_workbench.core.models.runtimes.catalog import catalog
from ai_workbench.core.models.schema import ASRParameters, TranscriptionRequest
from tests.asr_fixtures import PARAMETERS, model_tree, profile
from tests.test_text_embedding_runtime import runtime as embedding_runtime
from tests.test_wd14_runtime import wait_for

FAKE_ENGINE = '''
import json, os, subprocess, sys, time, wave
from common import WorkerError
class ASREngine:
    def __init__(self, path, options, information):
        self.device, self.device_name, self.dtype = options['device'], 'Fixture device', 'float32'
    def transcribe(self, path, options):
        if options['prompt'] == 'crash': os._exit(7)
        if options['prompt'] == 'fail': raise WorkerError('MODEL_UNAVAILABLE', 503)
        if options['language'] not in ('auto', 'en', 'zh'): raise WorkerError('UNSUPPORTED_CAPABILITY')
        if options['prompt'] == 'wait':
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            print('waiting child_id=' + str(child.pid), flush=True)
            time.sleep(60)
        try:
            with wave.open(str(path), 'rb') as audio:
                duration = audio.getnframes() / audio.getframerate()
        except (wave.Error, EOFError):
            raise WorkerError('INVALID_AUDIO')
        text = json.dumps(options)
        value = {'response_format': options['response_format'], 'task': 'transcribe',
            'text': text, 'language': 'en' if options['language'] == 'auto' else options['language'],
            'duration': duration, 'segments': [{'id': 0, 'start': 0.0, 'end': duration, 'text': text}]
                if options['response_format'] == 'verbose_json' else None}
        if options['prompt'] == 'bad-result': value['duration'] = -1
        return value
'''


def audio_bytes(frames=16000, rate=16000):
    stream = BytesIO()
    with wave.open(stream, "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(b"\x01\x00" * frames)
    return stream.getvalue()


@asynccontextmanager
async def runtime(tmp_path, **values):
    async with embedding_runtime(tmp_path) as (service, manager, _, caller):
        (service.worker_root / "asr_engine.py").write_text(FAKE_ENGINE, encoding="utf-8")
        model_tree(tmp_path)
        model = manager.profiles.create(profile(**values))
        yield service, manager, model, caller


async def upload(caller, model, audio=None, **options):
    return await caller.post("/v1/audio/transcriptions", data={"model": model.alias, **options},
        files={"file": ("recording.wav", audio if audio is not None else audio_bytes(), "audio/wav")})


def test_public_formats_inheritance_explicit_resets_and_repeated_inference(tmp_path):
    async def scenario():
        saved = {"language": "zh", "prompt": "saved context", "temperature": 0.4, "response_format": "verbose_json"}
        async with runtime(tmp_path, parameters=saved) as (_, manager, model, caller):
            discovered = (await caller.get("/v1/models", params={"kind": "asr"})).json()["data"]
            assert len(discovered) == 1 and discovered[0]["id"] == model.alias
            assert manager._slots == {}
            result = await upload(caller, model, timestamp_granularities__unused="x")
            assert result.status_code == 422 and not manager._slots
            result = await upload(caller, model, **{"timestamp_granularities[]": "segment"})
            assert result.status_code == 200, result.text
            body = result.json()
            assert body["task"] == "transcribe" and body["language"] == "zh" and body["duration"] == 1
            assert json.loads(body["text"]) == saved and body["segments"][0]["end"] == 1
            assert "usage" not in body and "avg_logprob" not in body["segments"][0]
            assert result.headers["x-request-id"]
            adapter = manager._managed_slot(model).adapter
            process = adapter.process.process
            for response_format in ("json", "text"):
                result = await upload(caller, model, response_format=response_format, language="auto", prompt="", temperature="0")
                assert result.status_code == 200, result.text
                text = result.text if response_format == "text" else result.json()["text"]
                assert json.loads(text) == {**PARAMETERS, "response_format": response_format}
                if response_format == "json":
                    assert set(result.json()) == {"text"}
                else:
                    assert result.headers["content-type"].startswith("text/plain; charset=utf-8")
                assert not list(manager.asr_inputs.base.iterdir()) and adapter.process.process is process
            internal = await manager.transcribe(model.id, audio_bytes(), "wav", TranscriptionRequest(language="auto", prompt="", temperature=0))
            assert internal.response_format == "verbose_json" and json.loads(internal.text)["prompt"] == ""
            assert manager.profiles.get(model.id).parameters == saved
            async with httpx.AsyncClient(trust_env=False) as private:
                assert (await private.get(str(adapter.client.base_url) + "/health")).status_code == 401
            await manager.unload(model.id)
            assert process.returncode is not None and manager.status(model.id).residency == "unloaded"
    asyncio.run(scenario())


def test_public_boundary_audio_auth_visibility_and_http_limits(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, caller):
            for options in ({"temperature": "NaN"}, {"temperature": "true"}, {"temperature": "2"},
                    {"response_format": "srt"}, {"language": "english"}, {"stream": "true"}, {"task": "translate"},
                    {"timestamp_granularities[]": "word", "response_format": "verbose_json"},
                    {"timestamp_granularities[]": "segment"}):
                assert (await upload(caller, model, **options)).status_code == 422
            malformed = await caller.post("/v1/audio/transcriptions", content=b"x", headers={"Content-Type": "application/json"})
            assert malformed.status_code == 422
            for files in ([('file', ('a.wav', audio_bytes())), ('file', ('b.wav', audio_bytes()))],
                    [('model', (None, model.alias)), ('file', ('a.wav', audio_bytes()))]):
                duplicate = await caller.post("/v1/audio/transcriptions", data={"model": model.alias}, files=files)
                assert duplicate.status_code == 422
            assert not manager._slots
            assert (await caller.post("/v1/audio/transcriptions", headers={"Authorization": "Bearer wrong"})).status_code == 401
            assert (await upload(caller, SimpleNamespace(alias=model.id))).status_code == 404
            route = "/api/models/profiles/" + model.id
            await caller.patch(route, json={"external_enabled": False})
            assert (await upload(caller, model)).status_code == 404
            assert (await caller.get("/v1/models?kind=asr")).json()["data"] == []
            await caller.patch(route, json={"external_enabled": True})
            response = await upload(caller, model, audio=b"invalid WAV")
            assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_AUDIO"
            assert not list(manager.asr_inputs.base.iterdir())
            assert (await upload(caller, model, language="xx")).json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"
            large = audio_bytes(9 * 1024 * 1024 // 2)
            result = await upload(caller, model, audio=large, response_format="verbose_json")
            assert result.status_code == 200 and result.json()["duration"] > 30
            manager.settings.patch({"max_request_mb": 1})
            assert (await upload(caller, model, audio=large)).status_code == 413
            assert not list(manager.asr_inputs.base.iterdir())
            manager.settings.patch({"external_enabled": False})
            assert (await upload(caller, model)).status_code == 503
    asyncio.run(scenario())


def test_cancellation_queue_isolation_failure_recovery_and_input_cleanup(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, _):
            data = audio_bytes()
            other = manager.profiles.create(profile(name="Other ASR", alias="other-asr"))
            await manager.transcribe(model.id, data, "wav", TranscriptionRequest())
            await manager.transcribe(other.id, data, "wav", TranscriptionRequest())
            adapter = manager._managed_slot(model).adapter
            process = adapter.process.process
            witness = manager._managed_slot(other).adapter.process.process
            assert process.pid != witness.pid
            active = asyncio.create_task(manager.transcribe(model.id, data, "wav", TranscriptionRequest(prompt="wait")))
            await wait_for(lambda: "waiting child_id=" in adapter.log_path.read_text())
            child = int(re.search(r"waiting child_id=(\d+)", adapter.log_path.read_text())[1])
            assert len(list(manager.asr_inputs.base.iterdir())) == 1
            queued = asyncio.create_task(manager.transcribe(model.id, data, "wav", TranscriptionRequest()))
            await wait_for(lambda: manager.status(model.id).queued == 1)
            assert len(list(manager.asr_inputs.base.iterdir())) == 1
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)
            assert process.returncode is None
            original_stop = adapter._stop
            async def stop_before_cleanup():
                assert manager.status(model.id).active == 1 and list(manager.asr_inputs.base.iterdir())
                await original_stop()
                assert process.returncode is not None and list(manager.asr_inputs.base.iterdir())
            adapter._stop = stop_before_cleanup
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
            adapter._stop = original_stop
            assert process.returncode is not None and not psutil.pid_exists(child)
            assert witness.returncode is None and manager.status(model.id).active == 0
            assert not list(manager.asr_inputs.base.iterdir())
            await manager.transcribe(model.id, data, "wav", TranscriptionRequest())
            for prompt in ("fail", "bad-result", "crash"):
                with pytest.raises(ModelError):
                    await manager.transcribe(model.id, data, "wav", TranscriptionRequest(prompt=prompt))
                assert not list(manager.asr_inputs.base.iterdir())
                await manager.load(model.id)
                assert (await manager.transcribe(model.id, data, "wav", TranscriptionRequest())).text
            await manager.unload(model.id)
            assert witness.returncode is None
    asyncio.run(scenario())


def test_only_asr_inference_disables_the_fixed_read_timeout(tmp_path):
    async def scenario():
        adapter = ASRWorkerAdapter(SimpleNamespace(root=tmp_path, release=catalog("windows", "x86_64")), profile(), lambda: None)
        adapter._rpc = AsyncMock()
        await adapter.transcribe(profile(), "input.wav", ASRParameters())
        timeout = adapter._rpc.call_args.kwargs["timeout"]
        assert timeout.read is None and timeout.connect == timeout.write == timeout.pool == 300
    asyncio.run(scenario())


def test_public_disconnect_stops_transcription_before_input_cleanup(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, caller):
            await manager.load(model.id)
            adapter = manager._managed_slot(model).adapter
            process = adapter.process.process
            request = caller.build_request("POST", "/v1/audio/transcriptions", data={"model": model.alias, "prompt": "wait"},
                files={"file": ("input.wav", audio_bytes(), "audio/wav")})
            body = request.read()
            disconnected, delivered, responses = asyncio.Event(), False, []
            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await disconnected.wait()
                return {"type": "http.disconnect"}
            async def send(message):
                responses.append(message)
            scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
                "scheme": "http", "path": "/v1/audio/transcriptions", "raw_path": b"/v1/audio/transcriptions",
                "query_string": b"", "headers": [(key.lower(), value) for key, value in request.headers.raw], "client": ("127.0.0.1", 40001),
                "server": ("cogita.test", 80), "root_path": ""}
            task = asyncio.create_task(caller._transport.app(scope, receive, send))
            try:
                await wait_for(lambda: "waiting child_id=" in adapter.log_path.read_text())
                disconnected.set()
                await asyncio.wait_for(task, 5)
                assert process.returncode is not None and manager.status(model.id).active == 0
                assert not list(manager.asr_inputs.base.iterdir())
                assert next(item["status"] for item in responses if item["type"] == "http.response.start") == 499
            finally:
                disconnected.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_request_files_cleanup_after_write_cancellation_failure_and_restart(tmp_path):
    async def scenario():
        store = ASRInputs(tmp_path)
        original = store._write
        started, release = threading.Event(), threading.Event()
        def delayed(data, audio_format):
            started.set()
            assert release.wait(3)
            return original(data, audio_format)
        store._write = delayed
        async def staged():
            async with store.stage(audio_bytes(), "wav"):
                pytest.fail("Cancellation should stop entry")
        task = asyncio.create_task(staged())
        await asyncio.to_thread(started.wait, 3)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not list(store.base.iterdir())
        store._write = original
        with pytest.raises(RuntimeError):
            async with store.stage(audio_bytes(), "wav") as name:
                assert (store.base / name).is_file()
                raise RuntimeError("failure")
        assert not list(store.base.iterdir())
        original(b"left after crash", "wav")
        outside = tmp_path / "data/tmp/asr-inputs/unowned.txt"
        outside.write_bytes(b"keep")
        restarted = ASRInputs(tmp_path)
        assert not store.base.exists() and outside.read_bytes() == b"keep"
        restarted.close()
    asyncio.run(scenario())
