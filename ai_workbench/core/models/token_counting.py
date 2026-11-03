"""Offline reference counting for providers with unknown native tokenizers."""
import asyncio
import base64
import json
from pathlib import Path
import threading
import time

IDLE_SECONDS = 60
IDLE_CHECK_SECONDS = 5


def _load_encoding():
    import tiktoken

    # The vocabulary is an installation asset. Never use tiktoken's URL loader.
    with (Path(__file__).parent / "token_data" / "o200k_base.tiktoken").open("rb") as lines:
        ranks = {base64.b64decode(token): int(rank) for token, rank in (line.split() for line in lines)}
    pattern = "|".join([
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"\p{N}{1,3}", r" ?[^\s\p{L}\p{N}]+[\r\n/]*", r"\s*[\r\n]+", r"\s+(?!\S)", r"\s+",
    ])
    return tiktoken.Encoding(name="cogita_o200k_base", pat_str=pattern, mergeable_ranks=ranks, special_tokens={})


class ReferenceTokenCounter:
    """One lazily loaded vocabulary, shared by the application's counting calls."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._condition = threading.Condition()
        self._encoding = None
        self._active = 0
        self._last_used = 0.0
        self._closed = False

    def count_text(self, text: str) -> int:
        with self._condition:
            if self._closed:
                raise RuntimeError("Reference token counter is closed")
            if self._encoding is None:
                self._encoding = _load_encoding()
            encoding = self._encoding
            self._active += 1
        try:
            return len(encoding.encode_ordinary(text))
        finally:
            with self._condition:
                self._active -= 1
                self._last_used = self._clock()
                self._condition.notify_all()

    def estimate_input_tokens(self, payload: dict) -> int:
        messages, images = [], 0
        for message in payload["messages"]:
            message = dict(message)
            if isinstance(message.get("content"), list):
                content = []
                for part in message["content"]:
                    if part["type"] == "image_url":
                        images += 1
                    else:
                        content.append(part)
                message["content"] = content
            messages.append(message)
        text = json.dumps({"messages": messages, **({"tools": payload["tools"]} if payload.get("tools") else {})},
                          ensure_ascii=False, separators=(",", ":"))
        return self.count_text(text) + images * 4096

    def release_idle(self) -> bool:
        # A first load can hold this lock in a worker; never block the event loop.
        if not self._condition.acquire(blocking=False):
            return False
        try:
            if self._encoding is None or self._active or self._clock() - self._last_used < IDLE_SECONDS:
                return False
            self._encoding = None
            return True
        finally:
            self._condition.release()

    async def expire_idle(self) -> None:
        while True:
            await asyncio.sleep(IDLE_CHECK_SECONDS)
            self.release_idle()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            while self._active:
                self._condition.wait()
            self._encoding = None
