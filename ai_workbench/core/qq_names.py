"""Bounded OneBot name lookups shared by display and batch-input projection."""
import asyncio
from collections import OrderedDict
import json
import logging
import re
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from websockets.exceptions import WebSocketException

from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.qq_protocol import OneBotUser

log = logging.getLogger(__name__)
LOOKUP_SECONDS = 2
CACHE_SIZE = 1024
NAME_TTL = 600
FAILURE_TTL = 60


class QQReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["at", "reply"]
    id: str
    name: str | None = None
    is_self: bool = False
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    frozen: bool = False


references_adapter = TypeAdapter(list[QQReference])


def render_mentions(text, references, *, for_model=False):
    parts, offset = [], 0
    for ref in references:
        if ref.type != "at" or ref.start is None or ref.end is None:
            continue
        label = "@全体成员" if ref.id == "all" else "@" + (ref.name or ref.id)
        if for_model and ref.id != "all":
            if ref.name:
                label += f"（QQ:{ref.id}{'，你' if ref.is_self else ''}）"
            elif ref.is_self:
                label += "（你）"
        parts.extend((text[offset:ref.start], label))
        offset = ref.end
    return "".join([*parts, text[offset:]])


def model_batch_text(rows):
    """Render stored ingress using only the mention names frozen at submission."""
    return "\n".join(
        f"[{row.timestamp}][{row.sender_name}（QQ:{row.sender_id}）]:"
        + render_mentions(row.text, references_adapter.validate_json(row.references_json), for_model=True)
        for row in rows
    )


class QQNames:
    def __init__(self, connections):
        self.connections = connections
        self.cache = {}
        self.inflight = {}
        self.slots = asyncio.Semaphore(4)

    def _cached(self, project_id, key):
        cache = self.cache.get(project_id)
        item = cache.get(key) if cache is not None else None
        if item is not None:
            if item[0] > time.monotonic():
                cache.move_to_end(key)
                return item
            del cache[key]
        return None

    def _remember(self, project_id, key, name):
        cache = self.cache.setdefault(project_id, OrderedDict())
        cache[key] = (time.monotonic() + (NAME_TTL if name else FAILURE_TTL), name)
        cache.move_to_end(key)
        while len(cache) > CACHE_SIZE:
            cache.popitem(last=False)

    def observe(self, binding, sender_id, sender_name):
        if sender_name.strip() and sender_name != sender_id:
            self._remember(binding.project_id, (binding.session_id, sender_id), sender_name)

    async def _query(self, connection, binding, user_id):
        async with self.slots:
            action = "get_group_member_info" if binding.target_kind == "group" else "get_stranger_info"
            params = {"user_id": int(user_id)}
            if binding.target_kind == "group":
                params["group_id"] = int(binding.target_id)
            user = OneBotUser.model_validate(await connection.call(action, params))
            if str(user.user_id) != user_id:
                raise ValueError("OneBot returned a different member")
            return (user.card.strip() if binding.target_kind == "group" else "") or user.nickname.strip() or None

    async def _lookup(self, binding, bot_account, user_id):
        key = (binding.session_id, user_id)
        connection = self.connections.get(binding.project_id)
        name = None
        if connection is not None and connection.ready:
            try:
                name = await asyncio.wait_for(self._query(connection, binding, user_id), LOOKUP_SECONDS)
            except (ToolExecutionError, OSError, WebSocketException, ValueError, asyncio.TimeoutError) as exc:
                # Missing member information is display enrichment, not delivery failure.
                log.warning("QQ name lookup unavailable (%s)", type(exc).__name__)
            if not name and user_id == bot_account:
                name = getattr(connection, "login_name", "") or None
        observed = self._cached(binding.project_id, key)
        if observed is not None and observed[1]:
            return observed[1]
        self._remember(binding.project_id, key, name)
        return name

    async def _name(self, binding, bot_account, user_id):
        cached = self._cached(binding.project_id, (binding.session_id, user_id))
        if cached is not None:
            return cached[1]
        key = (binding.project_id, binding.session_id, user_id)
        task = self.inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._lookup(binding, bot_account, user_id))
            self.inflight[key] = task
            task.add_done_callback(lambda _: self.inflight.pop(key, None))
        return await asyncio.shield(task)

    async def project(self, binding, bot_account, rows, *, freeze=False, for_model=False):
        references = [references_adapter.validate_json(row["references_json"]) for row in rows]
        ids = iter(dict.fromkeys(ref.id for refs in references for ref in refs
            if ref.type == "at" and ref.start is not None and ref.end is not None and not ref.frozen
            and re.fullmatch(r"[1-9][0-9]{0,19}", ref.id)))

        async def worker():
            for user_id in ids:
                await self._name(binding, bot_account, user_id)

        try:
            await asyncio.wait_for(asyncio.gather(*(worker() for _ in range(4))), LOOKUP_SECONDS)
        except asyncio.TimeoutError:
            pass  # Use completed lookups; the bounded shared requests may still fill the cache.
        for row, refs in zip(rows, references):
            for ref in refs:
                if ref.type == "at" and ref.start is not None and ref.end is not None and not ref.frozen:
                    ref.is_self = ref.id == bot_account
                    cached = self._cached(binding.project_id, (binding.session_id, ref.id))
                    ref.name = cached[1] if cached is not None else None
                    ref.frozen = freeze
            row["text"] = render_mentions(row["text"], refs, for_model=for_model)
            row["references"] = [ref.model_dump(include={"type", "id", "name", "is_self"}) for ref in refs]
            row["references_json"] = references_adapter.dump_json(refs).decode()
        return rows

    def retain_projects(self, project_ids):
        for project_id in self.cache.keys() - project_ids:
            del self.cache[project_id]

    async def close(self):
        tasks = list(self.inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.cache.clear()
