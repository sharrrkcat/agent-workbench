from __future__ import annotations

import asyncio
import json
import time
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from ai_workbench.core.assistant_output import AssistantDraft
from ai_workbench.core.harness.registry import TOOL_NAME_RE, ToolRegistry, public_url
from ai_workbench.core.harness.schema import HarnessState, ToolExecutionContext, ToolExecutionError, ToolOutcome
from ai_workbench.core.harness.settings import HarnessSettings
from ai_workbench.core.json_data import strict_json_loads
from ai_workbench.core.message_parts import make_tool_call_part, make_tool_result_part
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import ChatRequest, ToolCall
from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.schema.persona import ResolvedChatConfig
from ai_workbench.core.schema.result import RunResult
from ai_workbench.core.schema.run import RunStatus, RunStepStatus


MAX_TOOL_ROUNDS = 8
TOOL_TIMEOUT_SECONDS = 30
ACTIVE_BUDGET_SECONDS = 300
TERMINAL_STATUSES = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}


@dataclass
class _Budget:
    spent: float
    started: float = field(default_factory=time.monotonic)

    def remaining(self) -> float:
        return ACTIVE_BUDGET_SECONDS - self.spent - (time.monotonic() - self.started)

    def check(self) -> float:
        remaining = self.remaining()
        if remaining <= 0:
            raise ToolExecutionError("TOOL_RUN_TIMEOUT", "Harness execution exceeded 5 minutes.")
        return remaining


class HarnessAgentLoop:
    def __init__(self, *, sessions, messages, runs, events, model_manager, registry: ToolRegistry,
                 network_policy, harness_settings, repo_root, knowledge_service=None, active_runs=None) -> None:
        self.sessions = sessions
        self.messages = messages
        self.runs = runs
        self.events = events
        self.model_manager = model_manager
        self.registry = registry
        self.network_policy = network_policy
        self.harness_settings = harness_settings
        self.repo_root = repo_root
        self.knowledge_service = knowledge_service
        self.active_runs = active_runs

    async def run(self, *, session: Any, config: ResolvedChatConfig, run: Any,
                  user: MessageSchema, context: list[dict[str, Any]], active_seconds: float = 0.0) -> RunResult:
        state = HarnessState(base_messages=context, active_seconds=active_seconds,
                             searxng_base_url=self.harness_settings.get().searxng_base_url)
        return await self._drive(session=session, config=config, run=run, user=user, state=state)

    async def direct(self, *, session: Any, config: ResolvedChatConfig, run: Any,
                     tool_name: str, arguments: dict[str, Any]) -> RunResult:
        call = ToolCall(id=str(uuid4()), function={"name": tool_name, "arguments": json.dumps(arguments, ensure_ascii=False, allow_nan=False)})
        state = HarnessState(direct=True, pending_calls=[call], searxng_base_url=self.harness_settings.get().searxng_base_url)
        self.runs.update_status(run.run_id, RunStatus.RUNNING, current_step="tool")
        self._emit_run("run_started", run.run_id)
        draft = AssistantDraft(messages=self.messages, events=self.events, session_id=session.session_id,
                               run_id=run.run_id, message_id=str(uuid4()), config=config,
                               parent_message_id=None, streamed=False)
        self._persist_calls(draft, [call], direct=True)
        self._save_state(run.run_id, state)
        return await self._drive(session=session, config=config, run=run, user=None, state=state)

    async def resume_approval(self, *, session: Any, run: Any, decision: str) -> RunResult:
        # This claim is synchronous: concurrent approval requests cannot execute the same call.
        current = self.runs.get_run(run.run_id)
        if current.status != RunStatus.WAITING_FOR_USER or current.cancel_requested:
            raise ToolExecutionError("APPROVAL_NOT_WAITING", "Run is not waiting for approval.")
        if session.waiting_run_id != run.run_id:
            raise ToolExecutionError("APPROVAL_NOT_WAITING", "Session is not waiting for this run.")
        if decision not in {"approve", "reject"}:
            raise ToolExecutionError("APPROVAL_INVALID", "Choose approve or reject.")
        try:
            state = HarnessState.model_validate(self.runs.get_harness_state(run.run_id))
            config = ResolvedChatConfig.model_validate(self.runs.get_config_snapshot(run.run_id))
            if not state.awaiting_approval:
                raise ValueError("Missing approval")
            user = None if state.direct else self.messages.get_message(run.metadata["input_message_id"])
            if user is not None and user.session_id != session.session_id:
                raise ValueError("Mismatched input")
        except (KeyError, ValueError, ValidationError) as exc:
            raise ToolExecutionError("APPROVAL_STATE_INVALID", "The saved tool approval cannot be resumed; cancel this run.") from exc
        call_id = state.awaiting_approval
        step_id = state.approval_step_id
        state.awaiting_approval = None
        state.approval_step_id = None
        self.sessions.set_waiting_run(session.session_id, None)
        self.runs.update_status(run.run_id, RunStatus.RUNNING, current_step="tool")
        self.runs.update_step(step_id, status=RunStepStatus.COMPLETED, message="Approval resolved", metadata={"decision": decision})
        self._emit_step(run.run_id, step_id)
        self._save_state(run.run_id, state)
        self._emit_run("approval_resolved", run.run_id, {
            "tool_call_id": call_id, "tool_name": state.pending_calls[0].function.name, "decision": decision,
        })
        return await self._drive(session=session, config=config, run=run, user=user, state=state,
                                 approved_call_id=call_id if decision == "approve" else None,
                                 rejected_call_id=call_id if decision == "reject" else None)

    async def _drive(self, *, session, config, run, user, state: HarnessState,
                     approved_call_id: str | None = None, rejected_call_id: str | None = None) -> RunResult:
        task = asyncio.current_task()
        if task is not None and self.active_runs is not None:
            self.active_runs.register(run.run_id, task)
        budget = _Budget(state.active_seconds)
        try:
            if rejected_call_id:
                self._record_result(session, run, state, state.pending_calls[0], ToolOutcome(
                    status="rejected", error_code="APPROVAL_REJECTED", error_message="User rejected this tool call."))
                state.pending_calls.pop(0)
            while True:
                self._check_cancelled(run.run_id)
                budget.check()
                while state.pending_calls:
                    self._check_cancelled(run.run_id)
                    budget.check()
                    call = state.pending_calls[0]
                    try:
                        spec = self.registry.get(call.function.name)
                        if call.function.name not in config.tools_allowed:
                            raise ToolExecutionError("TOOL_NOT_ALLOWED", "Tool is not allowed for this persona/session.")
                        if state.direct and not spec.direct_callable:
                            raise ToolExecutionError("TOOL_NOT_DIRECT_CALLABLE", "Tool cannot be called directly.")
                        arguments = self._arguments(call)
                        self.registry.validate_arguments(spec.name, arguments)
                    except ToolExecutionError as exc:
                        self._record_result(session, run, state, call, ToolOutcome(
                            status="error", error_code=exc.code, error_message=exc.message))
                        state.pending_calls.pop(0)
                        continue
                    if spec.requires_approval and call.id != approved_call_id:
                        return self._pause(session, run, state, call, arguments, spec.risk)
                    approved_call_id = None
                    await self._execute_one(session, config, run, state, call, arguments, budget)
                    state.pending_calls.pop(0)
                    self._save_state(run.run_id, state)
                if state.direct:
                    outcome = state.last_result
                    if outcome is None:
                        raise ToolExecutionError("TOOL_PROTOCOL_ERROR", "Tool did not produce a result.")
                    if outcome.status != "success":
                        return self._terminate(run, state, RunStatus.FAILED, outcome.error_code, outcome.error_message)
                    self._complete(run.run_id)
                    return RunResult(success=True, run_id=run.run_id, data=outcome.data)
                content = await self._model_round(session, config, run, user, state, budget)
                if self.runs.get_run(run.run_id).status == RunStatus.DONE:
                    return RunResult(success=True, run_id=run.run_id, data=content)
        except asyncio.CancelledError:
            requested = self.runs.get_run(run.run_id).cancel_requested
            result = self._terminate(run, state, RunStatus.CANCELLED, "RUN_CANCELLED", "Run was cancelled.")
            if requested:
                return result
            raise
        except (ModelError, ToolExecutionError) as exc:
            return self._terminate(run, state, RunStatus.FAILED, exc.code, exc.message)
        except Exception:
            return self._terminate(run, state, RunStatus.FAILED, "HARNESS_EXECUTION_FAILED", "Harness execution failed.")
        finally:
            state.active_seconds = budget.spent + (time.monotonic() - budget.started)
            if self.runs.get_run(run.run_id).status == RunStatus.WAITING_FOR_USER:
                self._save_state(run.run_id, state)
            else:
                self.runs.update_harness_state(run.run_id, {})
            if self.active_runs is not None:
                self.active_runs.unregister(run.run_id)

    async def _model_round(self, session, config, run, user, state: HarnessState, budget: _Budget) -> str | None:
        step = self._start_step(run.run_id, "model", "Generating response", {"round": state.rounds + 1})
        if not config.model_profile_id:
            raise ModelError("MODEL_NOT_CONFIGURED", "Select a model for this session.", 503)
        profile = self.model_manager.profile(config.model_profile_id, "llm")
        tools = [{"type": "function", "function": {"name": spec.name, "description": spec.description, "parameters": spec.parameters}}
                 for spec in (self.registry.get(name) for name in config.tools_allowed)]
        request = ChatRequest(model=profile.alias, messages=[*state.base_messages, *state.transcript],
                              tools=tools, stream=profile.capabilities.streaming,
                              **config.generation.model_dump(exclude_none=True))
        self.model_manager.validate_chat(profile, request)
        resolution = {"model_profile_id": profile.id, "alias": profile.alias,
                      "provider_profile_id": profile.provider_profile_id, "model_ref": profile.model_ref}
        self.runs.update_metadata(run.run_id, {**self.runs.get_run(run.run_id).metadata, "model_resolution": resolution})
        draft = AssistantDraft(messages=self.messages, events=self.events, session_id=session.session_id,
                               run_id=run.run_id, message_id=str(uuid4()), config=config,
                               parent_message_id=user.message_id, streamed=request.stream)
        try:
            try:
                calls = await asyncio.wait_for(self._model_turn(profile.id, request, run.run_id, draft),
                                               timeout=budget.check())
            except asyncio.TimeoutError as exc:
                raise ToolExecutionError("TOOL_RUN_TIMEOUT", "Harness execution exceeded 5 minutes.") from exc
            self._check_cancelled(run.run_id)
            budget.check()
            self._validate_calls(calls, state)
            if calls and state.rounds >= MAX_TOOL_ROUNDS:
                raise ToolExecutionError("TOOL_LOOP_LIMIT", "Tool loop reached the maximum of 8 rounds.")
        except (Exception, asyncio.CancelledError):
            draft.persist(incomplete=True)
            raise
        self.runs.update_step(step.step_id, status=RunStepStatus.COMPLETED, message="Response generated",
                              metadata={"streamed": request.stream, "tool_calls": len(calls)})
        self._emit_step(run.run_id, step.step_id)
        if not calls:
            self._save_final(run, draft)
            return draft.text
        state.rounds += 1
        self._persist_calls(draft, calls)
        state.transcript.append({"role": "assistant", "content": draft.raw_content or None,
                                 **({"reasoning_content": draft.reasoning_content} if draft.reasoning_content else {}),
                                 "tool_calls": [call.model_dump(mode="json") for call in calls]})
        state.pending_calls = calls
        self._save_state(run.run_id, state)

    async def _model_turn(self, profile_id: str, request: ChatRequest, run_id: str,
                          draft: AssistantDraft) -> list[ToolCall]:
        if not request.stream:
            result = await self.model_manager.chat(profile_id, request)
            if result.message.content is not None and not isinstance(result.message.content, str):
                raise ModelError("MODEL_PROTOCOL_ERROR", "Model returned an invalid tool response.", 502)
            draft.append(result.message.content, result.message.reasoning_content)
            if result.finish_reason == "content_filter":
                raise ModelError("MODEL_REFUSAL", "Provider refused this request.", 422)
            calls = list(result.message.tool_calls or [])
            if bool(calls) != (result.finish_reason == "tool_calls"):
                raise ModelError("MODEL_PROTOCOL_ERROR", "Model returned an invalid tool finish reason.", 502)
            return calls
        calls: dict[int, dict[str, str]] = {}
        finish = None
        async with aclosing(self.model_manager.chat_stream(profile_id, request)) as stream:
            async for chunk in stream:
                self._check_cancelled(run_id)
                draft.append(chunk.delta.content, chunk.delta.reasoning_content)
                for delta in chunk.delta.tool_calls or []:
                    item = calls.setdefault(delta.index, {"id": "", "name": "", "arguments": ""})
                    if delta.id:
                        if item["id"] and item["id"] != delta.id:
                            raise ModelError("MODEL_PROTOCOL_ERROR", "Model changed a tool call id.", 502)
                        item["id"] = delta.id
                    if delta.function:
                        item["name"] += delta.function.name or ""
                        item["arguments"] += delta.function.arguments or ""
                if chunk.finish_reason:
                    finish = chunk.finish_reason
        if finish == "content_filter":
            raise ModelError("MODEL_REFUSAL", "Provider refused this request.", 422)
        if bool(calls) != (finish == "tool_calls") or finish is None:
            raise ModelError("MODEL_PROTOCOL_ERROR", "Model returned an invalid tool finish reason.", 502)
        try:
            result = [ToolCall(id=item["id"], function={"name": item["name"], "arguments": item["arguments"]})
                      for _, item in sorted(calls.items())]
        except ValidationError as exc:
            raise ModelError("MODEL_PROTOCOL_ERROR", "Model returned an incomplete tool call.", 502) from exc
        return result

    @staticmethod
    def _validate_calls(calls: list[ToolCall], state: HarnessState) -> None:
        seen = {call["id"] for message in state.transcript for call in message.get("tool_calls", [])}
        for call in calls:
            if (not call.id or len(call.id) > 128 or any(char.isspace() for char in call.id)
                    or not TOOL_NAME_RE.fullmatch(call.function.name) or call.id in seen):
                raise ModelError("MODEL_PROTOCOL_ERROR", "Model returned an invalid or duplicate tool call.", 502)
            seen.add(call.id)

    @staticmethod
    def _arguments(call: ToolCall) -> dict[str, Any]:
        try:
            arguments = strict_json_loads(call.function.arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Expected an object")
            return arguments
        except (ValueError, TypeError, RecursionError) as exc:
            raise ToolExecutionError("TOOL_INVALID_ARGUMENTS", "Tool arguments must be a valid JSON object matching the schema.") from exc

    async def _execute_one(self, session, config, run, state, call, arguments, budget) -> None:
        step = self._start_step(run.run_id, "tool", call.function.name,
                                {"tool_name": call.function.name, "tool_call_id": call.id})
        context = ToolExecutionContext(repo_root=self.repo_root, network_policy=self.network_policy,
                                       knowledge_service=self.knowledge_service, session_id=session.session_id,
                                       knowledge_base_ids=config.knowledge_base_ids,
                                       harness_settings=HarnessSettings(searxng_base_url=state.searxng_base_url))
        remaining = budget.check()
        try:
            data = await asyncio.wait_for(self.registry.execute(call.function.name, arguments, context),
                                          timeout=min(TOOL_TIMEOUT_SECONDS, remaining))
            outcome = ToolOutcome(status="success", data=data)
        except asyncio.TimeoutError:
            total = remaining <= TOOL_TIMEOUT_SECONDS or budget.remaining() <= 0
            outcome = ToolOutcome(status="error", error_code="TOOL_RUN_TIMEOUT" if total else "TOOL_TIMEOUT",
                                  error_message="Harness execution exceeded 5 minutes." if total else "Tool execution timed out.")
        except ToolExecutionError as exc:
            outcome = ToolOutcome(status="error", data=exc.details or None, error_code=exc.code, error_message=exc.message)
        self._record_result(session, run, state, call, outcome, step_id=step.step_id)
        if outcome.error_code == "TOOL_RUN_TIMEOUT":
            state.pending_calls.pop(0)
            raise ToolExecutionError(outcome.error_code, outcome.error_message)

    def _record_result(self, session, run, state, call, outcome: ToolOutcome, *, step_id=None) -> None:
        if step_id is None:
            step = self._start_step(run.run_id, "tool", call.function.name,
                                    {"tool_name": call.function.name, "tool_call_id": call.id})
            step_id = step.step_id
        part = make_tool_result_part(call.id, call.function.name, outcome.status, outcome.data,
                                    error_code=outcome.error_code, error_message=outcome.error_message,
                                    truncated=bool((outcome.data or {}).get("truncated")))
        message = self.messages.add_message(session.session_id, role="tool", parts=[part], run_id=run.run_id,
                                            parent_message_id=run.metadata.get("input_message_id"),
                                            metadata={"tool": call.function.name, "tool_call_id": call.id})
        self.events.emit("tool_result_created", session_id=session.session_id, run_id=run.run_id, message_id=message.message_id,
                         payload={"message": message.model_dump(mode="json"), "status": outcome.status,
                                  "tool_name": call.function.name, "tool_call_id": call.id})
        state.transcript.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(outcome.model_dump(exclude_none=True), ensure_ascii=False, allow_nan=False)})
        state.last_result = outcome
        self.runs.update_step(step_id, status=RunStepStatus.COMPLETED if outcome.status == "success" else
                              RunStepStatus.SKIPPED if outcome.status in {"rejected", "cancelled"} else RunStepStatus.FAILED,
                              message="Tool " + outcome.status, error_code=outcome.error_code, error_message=outcome.error_message,
                              metadata={"result_status": outcome.status})
        self._emit_step(run.run_id, step_id)

    def _persist_calls(self, draft: AssistantDraft, calls: list[ToolCall], *, direct: bool = False) -> None:
        parts = []
        for index, call in enumerate(calls):
            try:
                arguments = self._arguments(call)
            except ToolExecutionError:
                arguments = {}
            parts.append(make_tool_call_part(call.id, call.function.name,
                         self.registry.public_arguments(call.function.name, arguments), part_id=f"call_{index}"))
        message = draft.persist(extra_parts=parts, metadata={"tool_calls": True, "direct": direct})
        payload = {"message": message.model_dump(mode="json")}
        self.events.emit("tool_call_created", session_id=message.session_id, run_id=message.run_id, message_id=message.message_id,
                         payload={**payload, "tool_calls": [{"id": call.id, "name": call.function.name} for call in calls]})

    def _pause(self, session, run, state, call, arguments, risk) -> RunResult:
        service = {"service_url": public_url(state.searxng_base_url)} if call.function.name == "web_search" and state.searxng_base_url else {}
        step = self._start_step(run.run_id, "approval", "Waiting for confirmation",
                               {"tool_name": call.function.name, "tool_call_id": call.id, "risk": risk, **service})
        state.awaiting_approval = call.id
        state.approval_step_id = step.step_id
        self._save_state(run.run_id, state)
        self.runs.update_status(run.run_id, RunStatus.WAITING_FOR_USER, current_step="approval")
        self.sessions.set_waiting_run(session.session_id, run.run_id)
        self._emit_run("approval_requested", run.run_id, {"tool_call_id": call.id, "tool_name": call.function.name,
                       "arguments": self.registry.public_arguments(call.function.name, arguments), "step_id": step.step_id, "risk": risk, **service})
        return RunResult(success=True, run_id=run.run_id)

    def _save_final(self, run, draft: AssistantDraft) -> None:
        step = self._start_step(run.run_id, "save", "Saving response")
        draft.persist()
        self.runs.update_step(step.step_id, status=RunStepStatus.COMPLETED, message="Response saved")
        self._emit_step(run.run_id, step.step_id)
        self._complete(run.run_id)

    def cancel(self, run) -> RunResult:
        state = HarnessState.model_validate(self.runs.get_harness_state(run.run_id))
        return self._terminate(run, state, RunStatus.CANCELLED, "RUN_CANCELLED", "Run was cancelled.")

    def _terminate(self, run, state: HarnessState, status: RunStatus, code: str, message: str) -> RunResult:
        if self.runs.get_run(run.run_id).status in TERMINAL_STATUSES:
            return RunResult(success=False, run_id=run.run_id, error=message, error_code=code)
        session = self.sessions.get_session(run.session_id)
        for call in state.pending_calls:
            step_id = next((step.step_id for step in self.runs.list_steps(run.run_id)
                            if step.kind == "tool" and step.metadata.get("tool_call_id") == call.id
                            and step.status == RunStepStatus.RUNNING), None)
            self._record_result(session, run, state, call, ToolOutcome(
                status="cancelled" if status == RunStatus.CANCELLED else "error",
                error_code=code, error_message=message), step_id=step_id)
        state.pending_calls = []
        for step in self.runs.list_steps(run.run_id):
            if step.status in {RunStepStatus.PENDING, RunStepStatus.RUNNING}:
                self.runs.update_step(step.step_id, status=RunStepStatus.SKIPPED if status == RunStatus.CANCELLED else RunStepStatus.FAILED,
                                      error_code=code, error_message=message)
                self._emit_step(run.run_id, step.step_id)
        self.runs.update_status(run.run_id, status, current_step="cancelled" if status == RunStatus.CANCELLED else "failed",
                                error_code=code, error_message=message, cancel_requested=status == RunStatus.CANCELLED)
        self.runs.update_harness_state(run.run_id, {})
        if session.waiting_run_id == run.run_id:
            self.sessions.set_waiting_run(run.session_id, None)
        self._emit_run("run_cancelled" if status == RunStatus.CANCELLED else "run_failed", run.run_id,
                       {"error": message, "error_code": code})
        return RunResult(success=False, run_id=run.run_id, error=message, error_code=code)

    def _check_cancelled(self, run_id):
        run = self.runs.get_run(run_id)
        if run.cancel_requested or run.status == RunStatus.CANCELLED:
            raise asyncio.CancelledError()

    def _complete(self, run_id):
        self.runs.update_harness_state(run_id, {})
        self.runs.update_status(run_id, RunStatus.DONE, current_step="done")
        self._emit_run("run_completed", run_id)

    def _save_state(self, run_id, state: HarnessState):
        self.runs.update_harness_state(run_id, state.model_dump(mode="json"))

    def _start_step(self, run_id, kind, label, metadata=None):
        self.runs.update_status(run_id, RunStatus.RUNNING, current_step=kind)
        step = self.runs.create_step(run_id, kind=kind, label=label, status=RunStepStatus.RUNNING, metadata=metadata)
        self._emit_step(run_id, step.step_id, "run_step_created")
        return step

    def _emit_step(self, run_id, step_id, event_type="run_step_updated"):
        run = self.runs.get_run(run_id)
        step = self.runs.get_step(step_id)
        self.events.emit(event_type, session_id=run.session_id, run_id=run_id, payload={"step": step.model_dump(mode="json")})

    def _emit_run(self, event_type, run_id, payload=None):
        run = self.runs.get_run(run_id)
        self.events.emit(event_type, session_id=run.session_id, run_id=run_id,
                         payload={"run": run.model_dump(mode="json"), **(payload or {})})
