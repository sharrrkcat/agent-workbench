"""Input coordinator for ordinary chat, explicit tools and approval resume."""

from __future__ import annotations

import asyncio
from typing import Any

from ai_workbench.core.chat_runner import ChatRunner
from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.message_parts import text_from_parts
from ai_workbench.core.schema.result import RunResult
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.json_data import strict_json_loads


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
    """Recognize only registered /tool_name inputs; other text goes to chat."""

    def __init__(self, chat_runner: ChatRunner, active_runs: ActiveRunRegistry | None = None) -> None:
        self.chat_runner = chat_runner
        self.active_runs = active_runs or ActiveRunRegistry()

    async def handle_input(
        self,
        session: Any,
        text: str,
        *,
        input_message_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        client_message_id: str | None = None,
        source_message_id: str | None = None,
    ) -> RunResult:
        self._assert_available(session)
        direct = self._parse_direct_tool(text)
        if direct is not None:
            name, arguments = direct
            return await self.call_tool(session, name, arguments)
        return await self.chat_runner.run(
            session_id=session.session_id,
            text=text,
            attachments=attachments,
            input_message_id=input_message_id,
            client_message_id=client_message_id,
            source_message_id=source_message_id,
        )

    def _parse_direct_tool(self, text: str) -> tuple[str, dict[str, Any]] | None:
        value = str(text or "")
        if not value.startswith("/") or self.chat_runner.harness_loop is None:
            return None
        head, _, remainder = value[1:].partition(" ")
        if not head:
            return None
        try:
            spec = self.chat_runner.harness_loop.registry.get(head)
        except ToolExecutionError:
            return None
        required = spec.parameters.get("required", [])
        properties = spec.parameters.get("properties", {})
        if len(required) == 1 and properties.get(required[0], {}).get("type") == "string":
            return head, {required[0]: remainder}
        if not remainder:
            raise ChatError("TOOL_INVALID_ARGUMENTS", "Tool arguments must be a JSON object.")
        try:
            arguments = strict_json_loads(remainder)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ChatError("TOOL_INVALID_ARGUMENTS", "Tool arguments must be a JSON object.") from exc
        if not isinstance(arguments, dict):
            raise ChatError("TOOL_INVALID_ARGUMENTS", "Tool arguments must be a JSON object.")
        return head, arguments

    def _assert_available(self, session: Any) -> None:
        current = self.chat_runner.sessions.get_session(session.session_id)
        if current.waiting_run_id:
            raise ChatError("RUN_WAITING_FOR_APPROVAL", "Resolve the pending tool approval before sending another message.", 409)
        self.chat_runner.chat_service.assert_idle(session.session_id)

    async def call_tool(self, session: Any, name: str, arguments: dict[str, Any]) -> RunResult:
        self._assert_available(session)
        config = self.chat_runner.chat_service.resolve(session)
        registry = self.chat_runner.harness_loop.registry
        try:
            spec = registry.get(name)
            if not spec.direct_callable:
                raise ToolExecutionError("TOOL_NOT_DIRECT_CALLABLE", "Tool cannot be called directly.")
            if name not in config.tools_allowed:
                raise ToolExecutionError("TOOL_NOT_ALLOWED", "Tool is not allowed for this persona/session.")
            registry.validate_arguments(name, arguments)
        except ToolExecutionError as exc:
            raise ChatError(exc.code, exc.message, 404 if exc.code == "TOOL_NOT_FOUND" else 400) from exc
        run = self.chat_runner.runs.create_run(
            kind="tool", persona_id=config.persona_id, session_id=session.session_id,
            metadata={"tool_name": name, "direct": True, "harness": True},
            config_snapshot=config.model_dump(mode="json"),
        )
        return await self.chat_runner.harness_loop.direct(
            session=session, config=config, run=run, tool_name=name, arguments=arguments)

    async def retry_assistant_message(self, session: Any, message: Any, source_user_message: Any) -> RunResult:
        return await self.chat_runner.run(
            session_id=session.session_id,
            text=_text(source_user_message),
            attachments=(source_user_message.metadata or {}).get("attachments") or [],
            input_message_id=source_user_message.message_id,
            persona_id=message.speaker_id,
            source_message_id=self.chat_runner.runs.get_run(message.run_id).metadata.get("context_source_message_id") if message.run_id else None,
        )

    async def rerun_user_message(self, session: Any, message: Any) -> RunResult:
        return await self.chat_runner.run(
            session_id=session.session_id,
            text=_text(message),
            attachments=(message.metadata or {}).get("attachments") or [],
            input_message_id=message.message_id,
        )

def _text(message: Any) -> str:
    return text_from_parts(getattr(message, "parts", None))
