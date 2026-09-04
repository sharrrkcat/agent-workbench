"""Lifecycle coordinator for ordinary chat and waiting-run resume."""

from __future__ import annotations

import asyncio
from typing import Any

from ai_workbench.core.chat_runner import ChatRunner
from ai_workbench.core.message_parts import text_from_parts
from ai_workbench.core.schema.result import RunResult
from ai_workbench.core.schema.run import RunStatus


class ActiveRunRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def register(self, run_id: str, task: asyncio.Task[Any]) -> None:
        self._tasks[run_id] = task

    def unregister(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def active_count(self) -> int:
        return sum(1 for task in self._tasks.values() if not task.done())

    async def cancel_all(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


class WorkbenchRuntime:
    """The only input coordinator.

    Prefixes are intentionally opaque to this class: the complete user text is
    handed to ChatRunner unchanged.
    """

    def __init__(self, chat_runner: ChatRunner, active_runs: ActiveRunRegistry | None = None) -> None:
        self.chat_runner = chat_runner
        self.active_runs = active_runs or ActiveRunRegistry()

    def announce_model_change_if_needed(self, session_id: str) -> None:
        return None

    async def handle_input(
        self,
        session: Any,
        text: str,
        *,
        input_message_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        client_message_id: str | None = None,
    ) -> RunResult:
        if session.waiting_run_id:
            return await self.chat_runner.resume_run(
                session_id=session.session_id,
                run_id=session.waiting_run_id,
                text=text,
                attachments=attachments,
            )
        return await self.chat_runner.run(
            session_id=session.session_id,
            text=text,
            attachments=attachments,
            input_message_id=input_message_id,
            client_message_id=client_message_id,
        )

    async def retry_assistant_message(self, session: Any, message: Any, source_user_message: Any) -> RunResult:
        if message.run_id:
            try:
                self.chat_runner.messages.delete_messages_after(
                    session.session_id, message.message_id, include_target=True
                )
            except Exception:
                pass
        return await self.chat_runner.run(
            session_id=session.session_id,
            text=_text(source_user_message),
            attachments=(source_user_message.metadata or {}).get("attachments") or [],
        )

    async def rerun_user_message(self, session: Any, message: Any) -> RunResult:
        try:
            self.chat_runner.messages.delete_messages_after(
                session.session_id, message.message_id, include_target=False
            )
        except Exception:
            pass
        return await self.chat_runner.run(
            session_id=session.session_id,
            text=_text(message),
            attachments=(message.metadata or {}).get("attachments") or [],
            input_message_id=message.message_id,
        )

    def cancel_run(self, run_id: str) -> Any:
        return self.chat_runner.runs.update_status(
            run_id,
            RunStatus.CANCELLED,
            current_step="cancelled",
            error="Run was cancelled.",
            error_code="RUN_CANCELLED",
            cancel_requested=True,
        )


def _text(message: Any) -> str:
    return text_from_parts(getattr(message, "parts", None))
