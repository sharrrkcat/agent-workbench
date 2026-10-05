"""Online-only group observations and cancellable, single-reply attempts."""
import asyncio
from dataclasses import dataclass

from ai_workbench.db.qq_models import QQBatch


ICEBREAKER_SETTINGS = (
    "icebreaker_enabled", "icebreaker_cold_seconds", "icebreaker_wait_seconds", "icebreaker_cooldown_seconds",
    "connection_enabled", "websocket_url", "access_token", "bot_account",
)


@dataclass
class GroupActivity:
    project_id: str
    settings: tuple
    last_activity: float
    sender_id: str | None = None
    first_message_id: int | None = None
    deadline: float | None = None
    batch_id: int | None = None


@dataclass
class IcebreakerAttempt:
    group: GroupActivity
    task: asyncio.Task | None = None
    cancelled: bool = False
    dispatched: bool = False


class QQIcebreaker:
    def __init__(self, store):
        self.store = store
        self.groups: dict[str, GroupActivity] = {}
        self.attempts: dict[int, IcebreakerAttempt] = {}

    def sync(self, project, binding, ready, now):
        session_id = binding.session_id
        if binding.target_kind != "group" or binding.paused or not ready or not (
                project.connection_enabled and project.icebreaker_enabled):
            self.reset_session(session_id)
            return None
        settings = tuple(getattr(project, field) for field in ICEBREAKER_SETTINGS)
        group = self.groups.get(session_id)
        if group is None or group.settings != settings:
            self.reset_session(session_id)
            group = self.groups[session_id] = GroupActivity(project.id, settings, now)
        return group

    def reset_session(self, session_id):
        group = self.groups.pop(session_id, None)
        if group is not None:
            self.cancel(group)

    def reset_project(self, project_id):
        for session_id, group in list(self.groups.items()):
            if group.project_id == project_id:
                self.reset_session(session_id)

    def cancel(self, group):
        group.deadline = None
        group.first_message_id = None
        group.sender_id = None
        if group.batch_id is None:
            return
        attempt = self.attempts[group.batch_id]
        if attempt.dispatched:
            return
        attempt.cancelled = True
        if attempt.task is not None:
            if attempt.task is not asyncio.current_task(loop=attempt.task.get_loop()):
                attempt.task.cancel()
        else:
            batch = self.store.get(QQBatch, group.batch_id)
            if batch is not None and batch.status == "queued":
                batch.status, batch.error_code = "cancelled", "QQ_ICEBREAKER_CANCELLED"
                self.store.save(batch)
            self.finish(group.batch_id)

    def observe(self, project, binding, ready, message_id, sender_id, now):
        group = self.sync(project, binding, ready, now)
        if group is None:
            return
        previous = group.last_activity
        group.last_activity = now
        if binding.deadline is not None or self.store.has_reply_work(binding.session_id):
            self.cancel(group)
        elif group.batch_id is not None or group.deadline is not None:
            if sender_id != group.sender_id:
                self.cancel(group)
            elif group.batch_id is None:
                group.deadline = now + project.icebreaker_wait_seconds
        elif now - previous > project.icebreaker_cold_seconds and (
                binding.icebreaker_cooldown_until is None or now >= binding.icebreaker_cooldown_until):
            group.sender_id = sender_id
            group.first_message_id = message_id
            group.deadline = now + project.icebreaker_wait_seconds

    def tick(self, project, binding, ready, now):
        group = self.sync(project, binding, ready, now)
        if group is None:
            return
        if group.batch_id is not None:
            batch = self.store.get(QQBatch, group.batch_id)
            if batch is None or batch.status not in {"queued", "running"}:
                self.finish(group.batch_id)
            return
        if group.deadline is None or group.deadline > now:
            return
        if binding.deadline is not None or self.store.has_reply_work(binding.session_id):
            self.cancel(group)
            return
        batch = self.store.freeze(binding.session_id, project.batch_message_limit, now,
            icebreaker_first_id=group.first_message_id)
        group.deadline = None
        if batch is None:
            self.cancel(group)
            return
        group.batch_id = batch.id
        self.attempts[batch.id] = IcebreakerAttempt(group)

    def begin(self, batch):
        attempt = self.attempts.get(batch.id)
        if attempt is None:
            batch.status, batch.error_code = "cancelled", "QQ_ICEBREAKER_CANCELLED"
            self.store.save(batch)
            return None
        attempt.task = asyncio.current_task()
        return attempt

    def check(self, batch, project, binding, ready, now):
        self.sync(project, binding, ready, now)
        attempt = self.attempts[batch.id]
        if attempt.cancelled:
            raise asyncio.CancelledError
        return attempt

    def confirmed_send(self, session_id, now):
        group = self.groups.get(session_id)
        if group is not None:
            group.last_activity = now
            self.cancel(group)

    def finish(self, batch_id):
        attempt = self.attempts.pop(batch_id, None)
        if attempt is not None:
            group = attempt.group
            group.batch_id = group.deadline = group.first_message_id = group.sender_id = None
