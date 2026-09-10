import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
from types import SimpleNamespace
import wave

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.manager import ModelManager, ProviderSlot
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.schema import AudioOutput, ModelProfile, ModelStatus, SpeechRequest
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.core.models.voice_references import VoiceReferences, credential_id
from ai_workbench.workers.audio_catalog import CHATTERBOX_DEFAULTS, CHATTERBOX_FILES, MAX_REFERENCE_BYTES
from tests.test_tts import HEADERS, wav_bytes


def profile(**values):
    return ModelProfile(**{**dict(name="Chatterbox", alias="chatterbox", kind="tts", model_ref="tts/chatterbox",
        runtime_id="python-worker", runtime_variant="audio-cuda", parameters={"architecture": "chatterbox"},
        external_enabled=True), **values})


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 10, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def published(store, owner="profile", binding="binding", key="credential"):
    return store.publish(store.stage(wav_bytes(), "wav"), owner, binding, key)


def test_reference_expiry_renewal_ownership_and_active_pins(tmp_path):
    clock = Clock()
    store = VoiceReferences(tmp_path, clock=clock)
    entry = published(store)
    created = clock.now
    assert entry.expires_at == created + timedelta(minutes=30)
    clock.now += timedelta(minutes=16)
    assert store.list("profile", "binding", "credential")[0]["id"] == entry.id
    assert entry.expires_at == created + timedelta(minutes=30)
    for owner, binding, key in (("other", "binding", "credential"), ("profile", "other", "credential"),
                                ("profile", "binding", "other")):
        with pytest.raises(ModelError) as error:
            store.admit(entry.id, owner, binding, key)
        assert error.value.code == "VOICE_UNAVAILABLE"
    store.admit(entry.id, "profile", "binding", "credential")
    assert entry.expires_at == clock.now + timedelta(minutes=15)
    with pytest.raises(ModelError) as conflict:
        store.delete(entry.id, "profile", "binding", "credential")
    assert conflict.value.status == 409
    clock.now = entry.expires_at
    assert store.list("profile", "binding", "credential") == []
    assert entry.path.exists()
    # Observing expiry invalidates the ID even if the wall clock later moves back.
    clock.now -= timedelta(seconds=1)
    with pytest.raises(ModelError):
        store.admit(entry.id, "profile", "binding", "credential")
    store.release(entry)
    assert not entry.path.exists()
    store.close()


def test_concurrent_admissions_take_maximum_and_read_clock_once(tmp_path):
    clock = Clock()
    store = VoiceReferences(tmp_path, clock=clock)
    entry = published(store)
    start = clock.now
    moments = iter(start + timedelta(minutes=value) for value in (20, 16, 28, 5, 24, 18))
    store.clock = lambda: next(moments)
    with ThreadPoolExecutor(max_workers=6) as pool:
        admitted = list(pool.map(lambda _: store.admit(entry.id, "profile", "binding", "credential"), range(6)))
    assert admitted == [entry] * 6
    assert entry.active == 6 and entry.expires_at == start + timedelta(minutes=43)
    store.clock = clock
    store.invalidate()
    assert entry.path.exists()
    for _ in admitted:
        store.release(entry)
    assert not entry.path.exists()
    store.close()


def test_restart_cleanup_limits_and_shutdown_preserve_active_files(tmp_path):
    store = VoiceReferences(tmp_path, max_count=1, max_bytes=len(wav_bytes()))
    old = published(store)
    with pytest.raises(ModelError) as limit:
        store.stage(b"another", "wav")
    assert limit.value.code == "VOICE_REFERENCE_LIMIT"
    restarted = VoiceReferences(tmp_path)
    assert not old.path.exists()
    with pytest.raises(ModelError):
        restarted.admit(old.id, "profile", "binding", "credential")
    entry = published(restarted)
    restarted.admit(entry.id, "profile", "binding", "credential")
    restarted.close()
    assert entry.path.exists()
    restarted.release(entry)
    assert not entry.path.exists() and not restarted.base.exists()
    store.close()


@pytest.mark.parametrize("patch", [
    {"runtime_variant": "onnx-cpu"}, {"provider_profile_id": "external"}, {"runtime_options": {"device": "auto"}},
    {"runtime_options": {"intraop_threads": True}}, {"kind": "asr"},
    {"parameters": {"architecture": "chatterbox", "temperature": 0}},
    {"parameters": {"architecture": "chatterbox", "cfg_weight": 1.01}},
    {"parameters": {"architecture": "chatterbox", "exaggeration": True}},
    {"parameters": {"architecture": "chatterbox", "repetition_penalty": 0.5}},
    {"parameters": {"architecture": "chatterbox", "min_p": -0.1}},
    {"parameters": {"architecture": "chatterbox", "top_p": 0}},
    {"parameters": {"architecture": "chatterbox", "language": "en-US"}},
])
def test_strict_audio_profiles(patch):
    with pytest.raises(ValidationError):
        profile(**patch)


def test_chatterbox_defaults_and_no_kokoro_option_leakage():
    value = profile()
    assert value.parameters == {"architecture": "chatterbox", "speed": 1.0, "response_format": "mp3", **CHATTERBOX_DEFAULTS}
    assert value.runtime_options == {"device": "cuda", "intraop_threads": 4}
    with pytest.raises(ValidationError):
        profile(runtime_variant="onnx-cpu", parameters={"architecture": "kokoro", "cfg_weight": None})


class Adapter:
    def __init__(self, manager):
        self.manager = manager
        self.loaded = False
        self.calls = []

    def snapshot(self, _profile):
        return ModelStatus(state="ready" if self.loaded else "unloaded", residency="loaded" if self.loaded else "unloaded", unload_supported=True)

    async def load(self, value, **_):
        self.loaded = True
        return self.snapshot(value)

    async def close(self):
        self.loaded = False

    async def validate_reference(self, _profile, reference):
        path = self.manager.voice_references.base / reference
        try:
            if path.suffix != ".wav":
                raise ValueError()
            with wave.open(str(path), "rb") as source:
                assert source.readframes(source.getnframes())
                return {"frames": source.getnframes(), "sample_rate": source.getframerate()}
        except (wave.Error, EOFError, ValueError) as exc:
            raise ModelError("INVALID_AUDIO", "Invalid reference audio.") from exc

    async def speech(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        assert (self.manager.voice_references.base / kwargs["reference"]).exists()
        return AudioOutput(data=wav_bytes(), response_format="wav")


@pytest.fixture
def api(tmp_path):
    path = tmp_path / "data/models/tts/chatterbox"
    path.mkdir(parents=True)
    for name in CHATTERBOX_FILES:
        (path / name).write_bytes(b"fixture")
    with TestClient(create_app(use_memory=True, root=tmp_path), client=("127.0.0.1", 40001)) as client:
        manager = client.app.state.runtime_state.model_manager
        manager.runtime_supervisor.assert_available = lambda *args: None
        value = manager.profiles.create(profile(parameters={"architecture": "chatterbox", "response_format": "wav"}))
        manager.settings.patch({"external_enabled": True, "external_api_key": "test-key"})
        adapter = Adapter(manager)
        manager._slots[manager.backend_key(value)] = ProviderSlot(adapter, asyncio.Semaphore(1))
        yield client, manager, value, adapter


def upload(client, alias="chatterbox", data=None, filename="voice.wav", **kwargs):
    return client.post("/v1/audio/voice-references", headers=HEADERS,
        data={"model": alias}, files={"file": (filename, wav_bytes() if data is None else data)}, **kwargs)


def test_reference_api_binary_speech_overrides_and_one_request_files(api):
    client, manager, value, adapter = api
    response = upload(client)
    assert response.status_code == 200, response.text
    voice_id = response.json()["voice_id"]
    assert response.headers["x-request-id"] and response.json()["source"] == "temporary"
    assert client.get("/v1/audio/voices?source=preset", headers=HEADERS).json()["data"] == []
    listed = client.get("/v1/audio/voices?model=chatterbox&source=temporary", headers=HEADERS).json()["data"]
    assert listed[0]["id"] == voice_id and listed[0]["expires_at"] == response.json()["expires_at"]
    other = manager.profiles.create(profile(alias="other"))
    assert client.get("/v1/audio/voices?model=other", headers=HEADERS).json()["data"] == []
    speech = client.post("/v1/audio/speech", headers=HEADERS, json={"model": value.alias, "input": "Hello", "voice": voice_id,
        "speed": 0.75, "tts": {"language": "en-US", "model_options": {"cfg_weight": 0.25}}})
    assert speech.status_code == 200 and speech.content == wav_bytes(), speech.text
    assert speech.headers["content-type"] == "audio/wav"
    assert adapter.calls[-1][0][3:5] == (0.75, "wav")
    assert adapter.calls[-1][1]["model_options"] == {**CHATTERBOX_DEFAULTS, "cfg_weight": 0.25}
    one_shot = client.post("/v1/audio/speech", headers=HEADERS, json={"model": value.alias, "input": "Hello",
        "tts": {"reference_audio": {"format": "wav", "data_base64": base64.b64encode(wav_bytes()).decode()}}})
    assert one_shot.status_code == 200, one_shot.text
    assert len(list(manager.voice_references.base.iterdir())) == 1
    assert len(manager.profiles.list()) == 2
    assert client.app.state.runtime_state.runs.list_all_runs() == []
    deletion = client.delete(f"/v1/audio/voice-references/{voice_id}", headers=HEADERS)
    assert deletion.json() == {"deleted": True, "voice_id": voice_id}
    assert not list(manager.voice_references.base.iterdir())
    assert client.delete(f"/v1/audio/voice-references/{voice_id}", headers=HEADERS).status_code == 404


@pytest.mark.parametrize("tts", [{"language": "en-GB"}, {"model_options": {"top_p": 0}},
    {"model_options": {"temperature": True}}, {"model_options": {"unknown": 1}},
    {"reference_audio": {"format": "flac", "data_base64": "YWJj"}},
    {"reference_audio": {"format": "wav", "data_base64": "bad!"}}])
def test_invalid_chatterbox_requests_do_not_admit_or_renew(api, tts):
    client, manager, _, adapter = api
    voice_id = upload(client).json()["voice_id"]
    entry = manager.voice_references._entries[voice_id]
    expiry = entry.expires_at
    response = client.post("/v1/audio/speech", headers=HEADERS,
        json={"model": "chatterbox", "input": "Hello", "voice": voice_id, "tts": tts})
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_REQUEST", response.text
    assert not adapter.calls and entry.active == 0 and entry.expires_at == expiry


def test_upload_limits_malformed_inputs_and_authentication(api):
    client, manager, _, adapter = api
    for filename, data, status in (("voice.wav", b"broken", 400), ("voice.mp3", wav_bytes(), 400),
                                  ("voice.flac", wav_bytes(), 400), ("voice.wav", b"x" * (MAX_REFERENCE_BYTES + 1), 413)):
        response = upload(client, filename=filename, data=data)
        assert response.status_code == status, response.text
    assert not list(manager.voice_references.base.iterdir())
    assert upload(client, alias="missing").status_code == 404
    assert client.post("/v1/audio/voice-references", content=b"invalid").status_code == 401
    extra = client.post("/v1/audio/voice-references", headers=HEADERS, data={"model": "chatterbox", "extra": "field"},
        files={"file": ("voice.wav", wav_bytes())})
    assert extra.status_code == 400
    duplicates = client.post("/v1/audio/voice-references", headers=HEADERS, data={"model": "chatterbox"},
        files=[("file", ("one.wav", wav_bytes())), ("file", ("two.wav", wav_bytes()))])
    assert duplicates.status_code == 400
    client.patch("/api/models/settings", json={"max_request_mb": 1})
    assert upload(client, data=b"x" * (1024 * 1024)).status_code == 413
    assert not adapter.calls


def test_backendless_chatterbox_does_not_break_reference_discovery_or_deletion(api):
    client, manager, _, _ = api
    manager.profiles.create(profile(name="A draft", alias="draft", runtime_id=None, runtime_variant=None))
    voice_id = upload(client).json()["voice_id"]
    result = client.get("/v1/audio/voices?source=temporary", headers=HEADERS)
    assert result.status_code == 200, result.text
    assert [item["id"] for item in result.json()["data"]] == [voice_id]
    assert client.get("/v1/audio/voices?model=draft", headers=HEADERS).json()["data"] == []
    assert client.delete(f"/v1/audio/voice-references/{voice_id}", headers=HEADERS).status_code == 200


@pytest.mark.parametrize("change", ["key", "service", "enabled", "external_enabled", "binding", "delete"])
def test_disabling_or_replacing_ownership_invalidates_voice_ids(api, change):
    client, manager, value, _ = api
    voice_id = upload(client).json()["voice_id"]
    path = manager.voice_references._entries[voice_id].path
    if change == "key":
        client.patch("/api/models/settings", json={"external_api_key": "new-key"}).raise_for_status()
        client.patch("/api/models/settings", json={"external_api_key": "test-key"}).raise_for_status()
    elif change == "service":
        client.patch("/api/models/settings", json={"external_enabled": False}).raise_for_status()
        client.patch("/api/models/settings", json={"external_enabled": True}).raise_for_status()
    elif change == "delete":
        client.delete(f"/api/models/profiles/{value.id}").raise_for_status()
    else:
        patch = {"model_ref": "tts/another"} if change == "binding" else {change: False}
        client.patch(f"/api/models/profiles/{value.id}", json=patch).raise_for_status()
    assert not path.exists()
    assert client.get("/v1/audio/voices?source=temporary", headers=HEADERS).json()["data"] == []


def make_manager(root):
    supervisor = RuntimeSupervisor(root, RuntimeStore())
    manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=supervisor)
    manager.settings.patch({"external_enabled": True, "external_api_key": "test-key"})
    supervisor.assert_available = lambda *args: None
    return manager


def test_waiting_admission_renews_but_overflow_does_not_and_cancellation_releases_last(tmp_path):
    async def scenario():
        manager = make_manager(tmp_path)
        clock = Clock()
        manager._voice_references = VoiceReferences(tmp_path, clock=clock)
        value = manager.profiles.create(profile())
        adapter = Adapter(manager)
        started, stopped = asyncio.Event(), asyncio.Event()

        async def speech(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                assert entry.path.exists() and slot.active == 1
                stopped.set()

        adapter.speech = speech
        slot = ProviderSlot(adapter, asyncio.Semaphore(1))
        manager._slots[manager.backend_key(value)] = slot
        manager._slot = lambda *args: (SimpleNamespace(concurrency=1, queue_size=1, queue_timeout_seconds=0.05), slot)
        entry = published(manager.voice_references, value.id, manager.voice_binding(value), credential_id("test-key"))
        request = SpeechRequest(model=value.alias, input="Hello", voice=entry.id)
        first = asyncio.create_task(manager.speech(value.id, request))
        await started.wait()
        clock.now += timedelta(minutes=20)
        waiting = asyncio.create_task(manager.speech(value.id, request))
        while slot.queued != 1:
            await asyncio.sleep(0)
        expiry = clock.now + timedelta(minutes=15)
        assert entry.expires_at == expiry and entry.active == 2
        clock.now += timedelta(minutes=1)
        with pytest.raises(ModelError) as overflow:
            await manager.speech(value.id, request)
        assert overflow.value.code == "MODEL_BUSY" and entry.expires_at == expiry
        with pytest.raises(ModelError) as timeout:
            await waiting
        assert timeout.value.code == "MODEL_BUSY" and entry.active == 1 and not stopped.is_set()
        manager.invalidate_voice_references()
        assert entry.path.exists()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert stopped.is_set() and entry.active == 0 and not entry.path.exists()
        assert slot.active == slot.queued == 0
        await manager.close()
        await manager.runtime_supervisor.close()
    asyncio.run(scenario())


def test_cancelling_file_staging_waits_for_write_and_removes_the_file(tmp_path):
    async def scenario():
        manager = make_manager(tmp_path)
        entered, finish = threading.Event(), threading.Event()
        references = manager.voice_references
        original = references.stage

        def stage(*args):
            entry = original(*args)
            entered.set()
            assert finish.wait(5)
            return entry

        references.stage = stage
        task = asyncio.create_task(manager._stage_reference(wav_bytes(), "wav"))
        await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not references._entries and not list(references.base.iterdir())
        await manager.close()
        await manager.runtime_supervisor.close()
    asyncio.run(scenario())
