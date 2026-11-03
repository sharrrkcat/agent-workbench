"""Vocabulary ownership, concurrent use and deterministic idle expiry."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import weakref

import pytest

from ai_workbench.core.models import token_counting
from ai_workbench.core.models.token_counting import ReferenceTokenCounter


class Encoding:
    def encode_ordinary(self, text):
        return text.split()


def test_idle_expiry_uses_last_completed_call_and_reloads(monkeypatch):
    now, loaded = [0.0], []

    def load():
        encoding = Encoding()
        loaded.append(weakref.ref(encoding))
        return encoding

    monkeypatch.setattr(token_counting, "_load_encoding", load)
    counter = ReferenceTokenCounter(clock=lambda: now[0])
    assert not counter.release_idle() and not loaded
    assert counter.count_text("one two") == 2
    now[0] = 59
    assert not counter.release_idle()
    assert counter.count_text("three") == 1
    now[0] = 118.99
    assert not counter.release_idle()
    now[0] = 119
    assert counter.release_idle() and loaded[0]() is None
    assert counter.count_text("one two") == 2 and len(loaded) == 2
    counter.close()
    assert loaded[1]() is None
    with pytest.raises(RuntimeError, match="closed"):
        counter.count_text("closed")


def test_concurrent_calls_share_one_load_and_close_waits_for_encoding(monkeypatch):
    entered = threading.Barrier(5)
    release = threading.Event()
    closing = threading.Event()
    loaded, now = [], [0.0]

    class BlockingEncoding:
        def encode_ordinary(self, text):
            entered.wait(timeout=5)
            assert release.wait(timeout=5)
            return [1]

    def load():
        encoding = BlockingEncoding()
        loaded.append(weakref.ref(encoding))
        return encoding

    monkeypatch.setattr(token_counting, "_load_encoding", load)
    counter = ReferenceTokenCounter(clock=lambda: now[0])

    def close():
        closing.set()
        counter.close()

    with ThreadPoolExecutor(max_workers=5) as pool:
        calls = [pool.submit(counter.count_text, str(i)) for i in range(4)]
        try:
            entered.wait(timeout=5)  # All encodes run concurrently, outside the initialization lock.
            assert len(loaded) == 1
            now[0] = 120
            assert not counter.release_idle() and loaded[0]() is not None
            shutdown = pool.submit(close)
            assert closing.wait(timeout=5)
            assert not shutdown.done()
        finally:
            release.set()
        assert [call.result(timeout=5) for call in calls] == [1] * 4
        shutdown.result(timeout=5)
    assert loaded[0]() is None


def test_failed_loading_and_encoding_do_not_pin_the_cache(monkeypatch):
    attempts, now, loaded = [], [0.0], []

    class FailingEncoding:
        def encode_ordinary(self, text):
            raise ValueError("encoding failure")

    def load():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("missing vocabulary")
        encoding = FailingEncoding()
        loaded.append(weakref.ref(encoding))
        return encoding

    monkeypatch.setattr(token_counting, "_load_encoding", load)
    counter = ReferenceTokenCounter(clock=lambda: now[0])
    with pytest.raises(OSError, match="missing vocabulary"):
        counter.count_text("text")
    with pytest.raises(ValueError, match="encoding failure"):
        counter.count_text("text")
    now[0] = 60
    assert counter.release_idle() and loaded[0]() is None
    counter.close()


def test_expiry_task_releases_without_another_request(monkeypatch):
    monkeypatch.setattr(token_counting, "_load_encoding", Encoding)
    monkeypatch.setattr(token_counting, "IDLE_CHECK_SECONDS", 0)
    now = [0.0]
    counter = ReferenceTokenCounter(clock=lambda: now[0])
    counter.count_text("text")
    encoding = weakref.ref(counter._encoding)
    now[0] = 60

    async def scenario():
        task = asyncio.create_task(counter.expire_idle())
        try:
            for _ in range(3):
                await asyncio.sleep(0)
            assert encoding() is None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            counter.close()

    asyncio.run(scenario())
