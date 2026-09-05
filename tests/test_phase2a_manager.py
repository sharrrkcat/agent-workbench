import asyncio
from contextlib import aclosing

import pytest

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.events import EventBus
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.schema import ChatChunk, ChatRequest, ChatResult, ModelProfile, ModelStatus, ProviderProfile
from ai_workbench.core.models.store import ModelProfileStore, ProviderProfileStore, ModelSettingsStore


class ControlledAdapter:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.loads = 0
        self.unloads = 0
        self.closed = False
        self.stream_closed = False
        self.fail_unload = False

    async def load(self, profile):
        self.loads += 1
        return ModelStatus(state="ready", residency="loaded", unload_supported=True)

    async def unload(self, profile):
        self.unloads += 1
        if self.fail_unload:
            raise ModelError("MODEL_UNAVAILABLE", "release failed", 503)
        return ModelStatus(state="unloaded", residency="unloaded", unload_supported=True)

    async def chat(self, profile, request):
        self.started.set()
        await self.release.wait()
        return ChatResult(message={"role": "assistant", "content": "reply"}, finish_reason="stop")

    async def models(self):
        self.started.set()
        await self.release.wait()
        return ["weights"]

    async def chat_stream(self, profile, request):
        try:
            self.started.set()
            yield ChatChunk(delta={"content": "first"})
            await self.release.wait()
            yield ChatChunk(finish_reason="stop")
        finally:
            self.stream_closed = True

    async def close(self):
        self.closed = True


def manager_fixture(*, queue_size=1, timeout=1, lifecycle=None):
    profiles = ModelProfileStore()
    providers = ProviderProfileStore()
    provider = providers.create(ProviderProfile(name="test", base_url="http://test/v1", queue_size=queue_size, queue_timeout_seconds=timeout))
    profile = profiles.create(ModelProfile(name="chat", alias="chat", kind="llm", provider_profile_id=provider.id,
                                          model_ref="weights", capabilities={"streaming": True}, lifecycle=lifecycle or {}))
    adapter = ControlledAdapter()
    manager = ModelManager(profiles, providers, ModelSettingsStore(), adapter_factory=lambda _: adapter)
    return manager, profile, adapter


def request(stream=False):
    return ChatRequest(model="chat", messages=[{"role": "user", "content": "hello"}], stream=stream)


async def wait_until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("condition did not become true")


def test_shared_alias_occupation_queue_limit_cancel_and_manual_default():
    async def scenario():
        manager, profile, adapter = manager_fixture()
        manager.events = EventBus()
        alias = manager.profiles.create(ModelProfile(name="alias", alias="alias", kind="llm", provider_profile_id=profile.provider_profile_id, model_ref=profile.model_ref))
        first = asyncio.create_task(manager.chat(profile.id, request()))
        await adapter.started.wait()
        queued = asyncio.create_task(manager.chat(alias.id, request()))
        await wait_until(lambda: manager.status(profile.id).queued == 1)
        assert manager.status(alias.id).active == 1
        snapshots = {e.payload["model_profile_id"]: e.payload["status"] for e in manager.events.list_events()}
        assert snapshots[alias.id]["active"] == snapshots[profile.id]["active"] == 1
        assert snapshots[alias.id]["queued"] == snapshots[profile.id]["queued"] == 1
        with pytest.raises(ModelError) as full:
            await manager.chat(alias.id, request())
        assert full.value.code == "MODEL_BUSY"
        with pytest.raises(ModelError):
            await manager.unload(profile.id)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert manager.status(profile.id).queued == 0
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert manager.status(profile.id).active == 0
        snapshots = {e.payload["model_profile_id"]: e.payload["status"] for e in manager.events.list_events()}
        assert snapshots[alias.id]["active"] == snapshots[profile.id]["active"] == 0
        assert adapter.unloads == 0
        adapter.release.set()
        await manager.chat(profile.id, request())
        assert adapter.loads == 1
        await manager.close()
        assert adapter.closed
    asyncio.run(scenario())


def test_queue_capacity_is_enforced_even_before_first_acquisition():
    async def scenario():
        manager, profile, adapter = manager_fixture(queue_size=0)
        tasks = [asyncio.create_task(manager.chat(profile.id, request())) for _ in range(8)]
        await adapter.started.wait()
        adapter.release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert sum(isinstance(r, ModelError) and r.code == "MODEL_BUSY" for r in results) == 7
        assert manager.status(profile.id).active == manager.status(profile.id).queued == 0
        await manager.close()
    asyncio.run(scenario())


def test_queue_timeout_and_manager_exit_cancel_active_and_pending():
    async def scenario():
        manager, profile, adapter = manager_fixture(timeout=0.02)
        first = asyncio.create_task(manager.chat(profile.id, request()))
        await adapter.started.wait()
        with pytest.raises(ModelError) as timeout:
            await manager.chat(profile.id, request())
        assert timeout.value.code == "MODEL_BUSY"
        pending = asyncio.create_task(manager.chat(profile.id, request()))
        await wait_until(lambda: manager.status(profile.id).queued == 1)
        await manager.close()
        results = await asyncio.gather(first, pending, return_exceptions=True)
        assert all(isinstance(r, asyncio.CancelledError) for r in results)
        assert adapter.closed
    asyncio.run(scenario())


def test_stream_close_releases_model_and_upstream_without_background_leak():
    async def scenario():
        manager, profile, adapter = manager_fixture()
        async with aclosing(manager.chat_stream(profile.id, request(stream=True))) as stream:
            first = await anext(stream)
            assert first.delta.content == "first"
            assert manager.status(profile.id).active == 1
        assert adapter.stream_closed
        assert manager.status(profile.id).active == 0
        assert not manager._slots[profile.provider_profile_id].tasks
        await manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["after_request", "idle"])
def test_opt_in_release_and_shared_manual_alias(mode):
    async def scenario():
        manager, profile, adapter = manager_fixture(lifecycle={"unload": mode, "idle_seconds": 0.01})
        adapter.release.set()
        await manager.chat(profile.id, request())
        await wait_until(lambda: adapter.unloads == 1)
        manager.profiles.create(ModelProfile(name="manual", alias="manual", kind="llm", provider_profile_id=profile.provider_profile_id, model_ref=profile.model_ref))
        await manager.chat(profile.id, request())
        await asyncio.sleep(0.02)
        assert adapter.unloads == 1
        await manager.close()
    asyncio.run(scenario())


def test_release_error_does_not_leak_semaphore_or_active_task():
    async def scenario():
        manager, profile, adapter = manager_fixture(lifecycle={"unload": "after_request"})
        adapter.fail_unload = True
        adapter.release.set()
        await manager.chat(profile.id, request())
        assert manager.status(profile.id).error_code == "MODEL_UNAVAILABLE"
        assert manager.status(profile.id).active == 0
        assert not manager._slots[profile.provider_profile_id].tasks
        await manager.chat(profile.id, request())
        await manager.close()
    asyncio.run(scenario())


def test_model_discovery_shares_queue_and_shutdown_tracking():
    async def scenario():
        manager, profile, adapter = manager_fixture()
        discovery = asyncio.create_task(manager.provider_models(profile.provider_profile_id))
        await adapter.started.wait()
        with pytest.raises(ModelError, match="before editing"):
            manager.require_idle(profile.provider_profile_id)
        request_task = asyncio.create_task(manager.chat(profile.id, request()))
        await wait_until(lambda: manager.status(profile.id).queued == 1)
        await manager.close()
        results = await asyncio.gather(discovery, request_task, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert adapter.closed
    asyncio.run(scenario())


def test_changing_connection_blocks_new_requests_until_old_client_closes():
    async def scenario():
        manager, profile, adapter = manager_fixture()
        adapter.release.set()
        await manager.chat(profile.id, request())
        closing = asyncio.Event()
        release_close = asyncio.Event()

        async def close():
            closing.set()
            await release_close.wait()
        adapter.close = close
        change = asyncio.create_task(manager.invalidate(profile.provider_profile_id))
        await closing.wait()
        with pytest.raises(ModelError) as busy:
            await manager.chat(profile.id, request())
        assert busy.value.code == "MODEL_BUSY"
        release_close.set()
        await change
        assert not manager._load_locks
        await manager.chat(profile.id, request())
        await manager.close()
    asyncio.run(scenario())
