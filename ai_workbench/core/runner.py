import asyncio
import inspect
from datetime import datetime
from typing import Any, AsyncIterator

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.events import EventBus
from ai_workbench.core.llm_config import LLMConfigError, require_llm_model, resolve_llm_config
from ai_workbench.core.llm_stream import LLMResult, LLMStreamChunk, LLMMetricsRecorder
from ai_workbench.core.schema.message import ImageGalleryPayload, ImagePayload, RichContentPayload
from ai_workbench.core.schema.result import CommandResult, RunResult
from ai_workbench.core.schema.run import RunSchema, RunStatus
from ai_workbench.core.script import ScriptAgentRunner
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore


class ActiveRunRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def register(self, run_id: str, task: asyncio.Task) -> None:
        self._tasks[run_id] = task

    def unregister(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True


class AgentRunner:
    def __init__(
        self,
        agent_registry: AgentRegistry,
        run_store: RunStore,
        message_store: MessageStore,
        event_bus: EventBus,
        llm_runtime: object,
        session_store: SessionStore = None,
        runtime_registry: CapabilityRuntimeRegistry = None,
        agent_config_store=None,
        capability_registry: CapabilityRegistry = None,
        capability_config_store=None,
        llm_profile_store=None,
        active_runs: ActiveRunRegistry = None,
    ) -> None:
        self.agent_registry = agent_registry
        self.run_store = run_store
        self.message_store = message_store
        self.event_bus = event_bus
        self.llm_runtime = llm_runtime
        self.context_builder = ContextBuilder(message_store)
        self.session_store = session_store
        self.runtime_registry = runtime_registry
        self.agent_config_store = agent_config_store
        self.capability_registry = capability_registry
        self.capability_config_store = capability_config_store
        self.llm_profile_store = llm_profile_store
        self.active_runs = active_runs or ActiveRunRegistry()
        self.script_runner = None
        if session_store is not None and runtime_registry is not None:
            self.script_runner = ScriptAgentRunner(
                agent_registry=agent_registry,
                run_store=run_store,
                message_store=message_store,
                session_store=session_store,
                event_bus=event_bus,
                runtime_registry=runtime_registry,
                llm_runtime=llm_runtime,
                capability_registry=capability_registry,
                capability_config_store=capability_config_store,
                llm_profile_store=llm_profile_store,
            )

    async def run(
        self,
        agent_id: str,
        action_id: str,
        args: str,
        session_id: str,
        source_message_id: str = "",
        parent_message_id: str = "",
        prefill=None,
        input_message_id: str = "",
        create_user_message: bool = True,
    ) -> RunResult:
        try:
            agent = self.agent_registry.get(agent_id)
        except KeyError:
            return RunResult(success=False, run_id="", error=f"Unknown agent: {agent_id}", error_code="AGENT_NOT_FOUND")

        if self.agent_config_store is not None and not self.agent_config_store.is_enabled(agent_id):
            return RunResult(
                success=False,
                run_id="",
                error=f"Agent is disabled: {agent_id}",
                error_code="AGENT_DISABLED",
            )

        if action_id not in {action.id for action in agent.actions}:
            return RunResult(
                success=False,
                run_id="",
                error=f"Unknown action '{action_id}' for agent '{agent_id}'.",
                error_code="ACTION_NOT_FOUND",
            )

        if agent.type == "script":
            if self.script_runner is None:
                return RunResult(success=False, run_id="", error="Script agent runner is not configured.")
            return await self.script_runner.run(
                agent=agent,
                action_id=action_id,
                args=args,
                session_id=session_id,
                source_message_id=source_message_id,
                parent_message_id=parent_message_id,
                prefill=prefill or {},
                input_message_id=input_message_id,
                create_user_message=create_user_message,
            )

        if agent.type != "prompt":
            return RunResult(success=False, run_id="", error=f"Unsupported agent type: {agent.type}")

        action = next(item for item in agent.actions if item.id == action_id)
        parent_id = parent_message_id or source_message_id or ""
        current_user_message_id = ""
        if action_id == "default":
            if input_message_id and not create_user_message:
                user_message = self.message_store.get_message(input_message_id)
                current_user_message_id = user_message.message_id
            else:
                user_message = self.message_store.add_message(
                    session_id=session_id,
                    role="user",
                    content=args,
                    agent_id=agent_id,
                    action_id=action_id,
                    metadata={
                        "input_source": "text",
                        "invocation": {
                            "route_type": "agent",
                            "agent_id": agent_id,
                            "action_id": action_id,
                            "raw_text": args,
                        },
                    },
                )
                current_user_message_id = user_message.message_id
            parent_id = user_message.message_id

        kind = "agent" if action_id == "default" else "action"
        run = self.run_store.create_run(
            kind=kind,
            target_id=agent_id,
            action_id=action_id,
            session_id=session_id,
            metadata={
                "args": args,
                "input_message_id": current_user_message_id or None,
                "parent_message_id": parent_id or None,
                "source_message_id": source_message_id or None,
                "prefill": prefill or {},
            },
        )
        self.event_bus.emit("run_started", session_id=session_id, run_id=run.run_id)
        if action_id != "default":
            self.event_bus.emit(
                "action_invoked",
                session_id=session_id,
                run_id=run.run_id,
                payload={
                    "agent_id": agent_id,
                    "action_id": action_id,
                    "source_message_id": source_message_id or None,
                    "prefill": prefill or {},
                },
            )
        self.run_store.update_status(run.run_id, RunStatus.RUNNING, current_step="running")
        current_task = asyncio.current_task()
        if current_task is not None:
            self.active_runs.register(run.run_id, current_task)

        try:
            return await self._run_prompt_agent(
                agent=agent,
                action=action,
                action_id=action_id,
                args=args,
                session_id=session_id,
                source_message_id=source_message_id,
                parent_id=parent_id,
                current_user_message_id=current_user_message_id,
                prefill=prefill or {},
                run=run,
            )
        finally:
            self.active_runs.unregister(run.run_id)

    async def _run_prompt_agent(
        self,
        agent,
        action,
        action_id: str,
        args: str,
        session_id: str,
        source_message_id: str,
        parent_id: str,
        current_user_message_id: str,
        prefill: dict,
        run: RunSchema,
    ) -> RunResult:
        context_policy = action.context_policy or agent.context_policy
        try:
            context = self.context_builder.build(
                session_id=session_id,
                args=args,
                policy=context_policy,
                source_message_id=source_message_id or None,
                current_message_id=current_user_message_id or None,
            )
        except KeyError as exc:
            error = str(exc)
            failed_run = self.run_store.update_status(
                run.run_id,
                RunStatus.FAILED,
                current_step="failed",
                error=error,
            )
            self.event_bus.emit(
                "run_failed",
                session_id=session_id,
                run_id=failed_run.run_id,
                payload={"error": error},
            )
            return RunResult(success=False, run_id=failed_run.run_id, error=error)

        messages = []
        if agent.prompt:
            prompt = agent.prompt
            if action.instruction:
                prompt = f"{prompt.rstrip()}\n\n{action.instruction}"
            messages.append({"role": "system", "content": prompt})
        messages.extend(context.messages)

        try:
            llm_config = self._resolve_llm_model_config(agent, action, session_id)
            require_llm_model(llm_config)
            self._record_llm_resolution(run.run_id, llm_config)
            if _streaming_enabled(llm_config):
                return await self._run_prompt_agent_streaming(
                    agent=agent,
                    action_id=action_id,
                    messages=messages,
                    session_id=session_id,
                    source_message_id=source_message_id,
                    parent_id=parent_id,
                    current_user_message_id=current_user_message_id,
                    prefill=prefill,
                    run=run,
                    context_warnings=context.warnings,
                    llm_config=llm_config,
                )
            metrics_recorder = LLMMetricsRecorder(streamed=False)
            raw_content = await _call_chat_nonstream(self.llm_runtime, messages, llm_config.values)
            llm_result = _extract_llm_result(raw_content)
            content = llm_result.content
            llm_metrics = metrics_recorder.complete(content, llm_result.usage)
        except LLMConfigError as exc:
            failed_run = self.run_store.update_status(
                run.run_id,
                RunStatus.FAILED,
                current_step="failed",
                error=exc.message,
            )
            self.event_bus.emit(
                "run_failed",
                session_id=session_id,
                run_id=failed_run.run_id,
                payload={"error": exc.message, "error_code": exc.code},
            )
            return RunResult(success=False, run_id=failed_run.run_id, error=exc.message, error_code=exc.code)
        except Exception as exc:
            error = str(exc) or "Prompt agent failed."
            failed_run = self.run_store.update_status(
                run.run_id,
                RunStatus.FAILED,
                current_step="failed",
                error=error,
            )
            self.event_bus.emit(
                "run_failed",
                session_id=session_id,
                run_id=failed_run.run_id,
                payload={"error": error},
            )
            return RunResult(success=False, run_id=failed_run.run_id, error=error)

        if self._is_cancelled(run.run_id):
            cancelled_run = self.run_store.update_status(run.run_id, RunStatus.CANCELLED, current_step="cancelled")
            self.event_bus.emit("run_cancelled", session_id=session_id, run_id=cancelled_run.run_id)
            return RunResult(success=False, run_id=cancelled_run.run_id, error="Run was cancelled.", data=None)

        original_user_message_id = self._find_original_user_message_id(source_message_id)
        source_user_message_id = current_user_message_id or original_user_message_id
        metadata = {
            "success": True,
            "context_warnings": context.warnings,
            "original_user_message_id": original_user_message_id,
            "source_user_message_id": source_user_message_id,
            "prefill": prefill or {},
            "llm_resolution": _public_llm_resolution(llm_config),
            "llm_metrics": llm_metrics,
            "reasoning": _reasoning_metadata(llm_config, llm_result.reasoning_content),
        }
        if llm_result.reasoning_content:
            metadata["reasoning_content"] = llm_result.reasoning_content
        self._record_llm_metadata(run.run_id, llm_config, llm_metrics)
        message = self.message_store.add_message(
            session_id=session_id,
            role="assistant",
            content=content,
            agent_id=agent.id,
            action_id=action_id,
            run_id=run.run_id,
            output_type="text",
            parent_message_id=parent_id or None,
            available_actions=self._available_actions(agent, source_message_id=""),
            metadata=metadata,
        )
        message_actions = self._available_actions(agent, source_message_id=message.message_id)
        if message_actions:
            message = message.model_copy(update={"available_actions": message_actions})
            self.message_store.update_message(message)
        done_run = self.run_store.update_status(
            run.run_id,
            RunStatus.DONE,
            current_step="done",
        )
        self.event_bus.emit("run_done", session_id=session_id, run_id=done_run.run_id)
        self.event_bus.emit(
            "run_metrics",
            session_id=session_id,
            run_id=done_run.run_id,
            payload={"metrics": llm_metrics},
        )
        self.event_bus.emit(
            "message_done",
            session_id=session_id,
            run_id=done_run.run_id,
            message_id=message.message_id,
            payload={"available_actions": message.available_actions},
        )

        lifecycle_result = self._apply_model_lifecycle(agent.model_lifecycle, llm_config.values, done_run.run_id, session_id)
        if lifecycle_result:
            done_run = self.run_store.get_run(done_run.run_id)
            if done_run.status == RunStatus.FAILED:
                return RunResult(success=False, run_id=done_run.run_id, data=content, error=done_run.error)

        return RunResult(success=True, run_id=done_run.run_id, data=content)

    async def _run_prompt_agent_streaming(
        self,
        agent,
        action_id: str,
        messages: list,
        session_id: str,
        source_message_id: str,
        parent_id: str,
        current_user_message_id: str,
        prefill: dict,
        run: RunSchema,
        context_warnings: list,
        llm_config,
    ) -> RunResult:
        draft_message_id = f"draft-{run.run_id}"
        resolution = _public_llm_resolution(llm_config)
        self.event_bus.emit(
            "message_started",
            session_id=session_id,
            run_id=run.run_id,
            message_id=draft_message_id,
            payload={
                "message_id": draft_message_id,
                "role": "assistant",
                "agent_id": agent.id,
                "agent_name": agent.name,
                "created_at": datetime.utcnow().isoformat(),
                "llm_resolution": resolution,
            },
        )
        metrics_recorder = LLMMetricsRecorder(streamed=True)
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage = None
        try:
            async for chunk in _call_chat_stream(self.llm_runtime, messages, llm_config.values):
                normalized = _normalize_stream_chunk(chunk)
                if normalized.usage:
                    usage = normalized.usage
                if normalized.reasoning_delta:
                    metrics_recorder.mark_first_token()
                    reasoning_parts.append(normalized.reasoning_delta)
                    self.event_bus.emit(
                        "message_delta",
                        session_id=session_id,
                        run_id=run.run_id,
                        message_id=draft_message_id,
                        payload={"delta": "", "reasoning_delta": normalized.reasoning_delta},
                    )
                if normalized.content_delta:
                    metrics_recorder.mark_first_token()
                    content_parts.append(normalized.content_delta)
                    self.event_bus.emit(
                        "message_delta",
                        session_id=session_id,
                        run_id=run.run_id,
                        message_id=draft_message_id,
                        payload={"delta": normalized.content_delta, "reasoning_delta": None},
                    )
        except asyncio.CancelledError:
            content = "".join(content_parts)
            llm_metrics = metrics_recorder.complete(content, usage)
            message = None
            if content or reasoning_parts:
                message = self._persist_prompt_message(
                    agent=agent,
                    action_id=action_id,
                    content=content,
                    session_id=session_id,
                    run_id=run.run_id,
                    parent_id=parent_id,
                    source_message_id=source_message_id,
                    current_user_message_id=current_user_message_id,
                    prefill=prefill,
                    context_warnings=context_warnings,
                    llm_config=llm_config,
                    llm_metrics=llm_metrics,
                    reasoning_content="".join(reasoning_parts),
                    interrupted=True,
                )
                self.event_bus.emit(
                    "message_completed",
                    session_id=session_id,
                    run_id=run.run_id,
                    message_id=message.message_id,
                    payload={"message": message.model_dump(mode="json"), "draft_message_id": draft_message_id},
                )
                self.event_bus.emit(
                    "message_done",
                    session_id=session_id,
                    run_id=run.run_id,
                    message_id=message.message_id,
                    payload={"available_actions": message.available_actions},
                )
            cancelled_run = self.run_store.update_status(run.run_id, RunStatus.CANCELLED, current_step="cancelled")
            self._record_llm_metadata(run.run_id, llm_config, llm_metrics)
            self.event_bus.emit(
                "run_metrics",
                session_id=session_id,
                run_id=run.run_id,
                payload={"metrics": llm_metrics},
            )
            self.event_bus.emit("run_cancelled", session_id=session_id, run_id=cancelled_run.run_id)
            return RunResult(success=False, run_id=cancelled_run.run_id, error="Run was cancelled.", data=content)
        except Exception as exc:
            error = str(exc) or "Prompt agent failed."
            failed_run = self.run_store.update_status(run.run_id, RunStatus.FAILED, current_step="failed", error=error)
            self.event_bus.emit(
                "run_failed",
                session_id=session_id,
                run_id=failed_run.run_id,
                message_id=draft_message_id,
                payload={"error": error},
            )
            return RunResult(success=False, run_id=failed_run.run_id, error=error)

        content = "".join(content_parts)
        llm_metrics = metrics_recorder.complete(content, usage)
        message = self._persist_prompt_message(
            agent=agent,
            action_id=action_id,
            content=content,
            session_id=session_id,
            run_id=run.run_id,
            parent_id=parent_id,
            source_message_id=source_message_id,
            current_user_message_id=current_user_message_id,
            prefill=prefill,
            context_warnings=context_warnings,
            llm_config=llm_config,
            llm_metrics=llm_metrics,
            reasoning_content="".join(reasoning_parts),
        )
        done_run = self.run_store.update_status(run.run_id, RunStatus.DONE, current_step="done")
        self._record_llm_metadata(run.run_id, llm_config, llm_metrics)
        self.event_bus.emit("run_done", session_id=session_id, run_id=done_run.run_id)
        self.event_bus.emit(
            "run_metrics",
            session_id=session_id,
            run_id=done_run.run_id,
            payload={"metrics": llm_metrics},
        )
        self.event_bus.emit(
            "message_completed",
            session_id=session_id,
            run_id=done_run.run_id,
            message_id=message.message_id,
            payload={"message": message.model_dump(mode="json"), "draft_message_id": draft_message_id},
        )
        self.event_bus.emit(
            "message_done",
            session_id=session_id,
            run_id=done_run.run_id,
            message_id=message.message_id,
            payload={"available_actions": message.available_actions},
        )
        lifecycle_result = self._apply_model_lifecycle(agent.model_lifecycle, llm_config.values, done_run.run_id, session_id)
        if lifecycle_result:
            done_run = self.run_store.get_run(done_run.run_id)
            if done_run.status == RunStatus.FAILED:
                return RunResult(success=False, run_id=done_run.run_id, data=content, error=done_run.error)
        return RunResult(success=True, run_id=done_run.run_id, data=content)

    def _persist_prompt_message(
        self,
        agent,
        action_id: str,
        content: str,
        session_id: str,
        run_id: str,
        parent_id: str,
        source_message_id: str,
        current_user_message_id: str,
        prefill: dict,
        context_warnings: list,
        llm_config,
        llm_metrics: dict,
        reasoning_content: str = "",
        interrupted: bool = False,
    ):
        original_user_message_id = self._find_original_user_message_id(source_message_id)
        source_user_message_id = current_user_message_id or original_user_message_id
        metadata = {
            "success": True,
            "context_warnings": context_warnings,
            "original_user_message_id": original_user_message_id,
            "source_user_message_id": source_user_message_id,
            "prefill": prefill or {},
            "llm_resolution": _public_llm_resolution(llm_config),
            "llm_metrics": llm_metrics,
            "reasoning": _reasoning_metadata(llm_config, reasoning_content),
        }
        if reasoning_content:
            metadata["reasoning_content"] = reasoning_content
        if interrupted:
            metadata["interrupted"] = True
        message = self.message_store.add_message(
            session_id=session_id,
            role="assistant",
            content=content,
            agent_id=agent.id,
            action_id=action_id,
            run_id=run_id,
            output_type="text",
            parent_message_id=parent_id or None,
            available_actions=self._available_actions(agent, source_message_id=""),
            metadata=metadata,
        )
        message_actions = self._available_actions(agent, source_message_id=message.message_id)
        if message_actions:
            message = message.model_copy(update={"available_actions": message_actions})
            self.message_store.update_message(message)
        return message

    def _resolve_llm_model_config(self, agent, action, session_id: str):
        capability = None
        capability_config = {}
        if self.capability_registry is not None:
            try:
                capability = self.capability_registry.get("llm")
            except KeyError:
                capability = None
        if self.capability_config_store is not None:
            capability_config = self.capability_config_store.get_config("llm")
        session_llm_profile_id = None
        if self.session_store is not None:
            session_llm_profile_id = self.session_store.get_session(session_id).llm_profile_id
        return resolve_llm_config(
            agent_schema=agent,
            action_schema=action,
            capability_schema=capability,
            capability_config=capability_config,
            llm_profile_store=self.llm_profile_store,
            session_llm_profile_id=session_llm_profile_id,
        )

    def _record_llm_resolution(self, run_id: str, llm_config) -> None:
        run = self.run_store.get_run(run_id)
        metadata = dict(run.metadata)
        metadata["llm_resolution"] = _public_llm_resolution(llm_config)
        self.run_store.update_metadata(run_id, metadata)

    def _record_llm_metadata(self, run_id: str, llm_config, llm_metrics: dict) -> None:
        run = self.run_store.get_run(run_id)
        metadata = dict(run.metadata)
        metadata["llm_resolution"] = _public_llm_resolution(llm_config)
        metadata["llm_metrics"] = llm_metrics
        self.run_store.update_metadata(run_id, metadata)

    def _is_cancelled(self, run_id: str) -> bool:
        try:
            return self.run_store.get_run(run_id).status == RunStatus.CANCELLED
        except KeyError:
            return False

    def _available_actions(self, agent, source_message_id: str):
        actions = []
        for action in agent.actions:
            if action.id == "default" or not action.callable or not action.label:
                continue
            actions.append(
                {
                    "agent_id": agent.id,
                    "action_id": action.id,
                    "label": action.label,
                    "source_message_id": source_message_id,
                    "prefill": {},
                }
            )
        return actions

    def _find_original_user_message_id(self, source_message_id: str):
        if not source_message_id:
            return None
        try:
            source = self.message_store.get_message(source_message_id)
        except KeyError:
            return None
        return source.parent_message_id

    def _apply_model_lifecycle(self, lifecycle, model_config, run_id: str, session_id: str) -> bool:
        if lifecycle.unload != "after_run":
            return False

        unload = getattr(self.llm_runtime, "unload", None)
        if not callable(unload):
            result = {"success": False, "unsupported": True, "message": "LLM runtime does not support unload."}
        else:
            try:
                result = unload(model_config=model_config)
            except Exception as exc:
                result = {"success": False, "unsupported": False, "message": str(exc) or "Unload failed."}

        if result.get("success"):
            return True

        message = result.get("message") or "LLM unload failed or is unsupported."
        if lifecycle.unload_failure == "ignore":
            return True
        if lifecycle.unload_failure == "warn":
            run = self.run_store.get_run(run_id)
            metadata = dict(run.metadata)
            warnings = list(metadata.get("warnings", []))
            warnings.append(message)
            metadata["warnings"] = warnings
            self.run_store.update_metadata(run_id, metadata)
            self.event_bus.emit(
                "run_warning",
                session_id=session_id,
                run_id=run_id,
                payload={"warning": message},
            )
            return True

        self.run_store.update_status(run_id, RunStatus.FAILED, current_step="unload_failed", error=message)
        self.event_bus.emit("run_failed", session_id=session_id, run_id=run_id, payload={"error": message})
        return True


def _public_llm_resolution(llm_config) -> dict:
    metadata = dict(getattr(llm_config, "metadata", {}) or {})
    values = getattr(llm_config, "values", {}) or {}
    return {
        "source": metadata.get("source"),
        "profile_id": metadata.get("profile_id"),
        "profile_alias": metadata.get("profile_alias"),
        "profile_key": metadata.get("profile_key") or metadata.get("profile_alias"),
        "profile_name": metadata.get("profile_name"),
        "provider": metadata.get("provider") or values.get("provider"),
        "model_id": values.get("model_id") or values.get("model"),
        "base_url": values.get("base_url", ""),
        "session_override_requested": metadata.get("session_override_requested"),
        "session_override_applied": bool(metadata.get("session_override_applied", False)),
        "allow_session_override": bool(metadata.get("allow_session_override", True)),
        "supports_vision": bool(values.get("supports_vision", False)),
        "supports_tools": bool(values.get("supports_tools", False)),
        "supports_reasoning": bool(values.get("supports_reasoning", False)),
        "supports_streaming": bool(values.get("supports_streaming", False)),
        "supports_json_mode": bool(values.get("supports_json_mode", False)),
    }


def _streaming_enabled(llm_config) -> bool:
    values = getattr(llm_config, "values", {}) or {}
    return values.get("supports_streaming") is True


async def _call_chat_nonstream(llm_runtime: object, messages: list, model_config: dict) -> Any:
    raw_method = getattr(llm_runtime, "chat_raw", None)
    if callable(raw_method):
        return await asyncio.to_thread(
            raw_method,
            messages=messages,
            model_config=model_config,
            stream=False,
        )
    return await asyncio.to_thread(
        llm_runtime.chat,
        messages=messages,
        model_config=model_config,
        stream=False,
    )


async def _call_chat_stream(llm_runtime: object, messages: list, model_config: dict) -> AsyncIterator[Any]:
    stream_method = getattr(llm_runtime, "chat_stream", None)
    if callable(stream_method):
        stream = stream_method(messages=messages, model_config=model_config)
    else:
        stream = llm_runtime.chat(messages=messages, model_config=model_config, stream=True)
    if inspect.isawaitable(stream):
        stream = await stream
    if hasattr(stream, "__aiter__"):
        async for chunk in stream:
            yield chunk
        return
    iterator = iter(stream)
    sentinel = object()
    while True:
        chunk = await asyncio.to_thread(next, iterator, sentinel)
        if chunk is sentinel:
            return
        yield chunk


def _normalize_stream_chunk(chunk: Any) -> LLMStreamChunk:
    if isinstance(chunk, LLMStreamChunk):
        return chunk
    if isinstance(chunk, str):
        return LLMStreamChunk(content_delta=chunk)
    if isinstance(chunk, dict):
        choice_delta = _first_choice_delta(chunk)
        if choice_delta is not None:
            usage = chunk.get("usage") if isinstance(chunk.get("usage"), dict) else None
            first_choice = chunk.get("choices")[0] if isinstance(chunk.get("choices"), list) and chunk.get("choices") else {}
            finish_reason = first_choice.get("finish_reason") if isinstance(first_choice, dict) else None
            return LLMStreamChunk(
                content_delta=_non_empty_string(choice_delta.get("content")),
                reasoning_delta=_non_empty_string(choice_delta.get("reasoning_content") or choice_delta.get("reasoning_delta")),
                finish_reason=finish_reason,
                usage=usage,
                raw=chunk,
            )
        return LLMStreamChunk(
            content_delta=chunk.get("content_delta") or chunk.get("delta"),
            reasoning_delta=chunk.get("reasoning_delta") or chunk.get("reasoning_content"),
            finish_reason=chunk.get("finish_reason"),
            usage=chunk.get("usage") if isinstance(chunk.get("usage"), dict) else None,
            raw=chunk.get("raw") if isinstance(chunk.get("raw"), dict) else chunk,
        )
    return LLMStreamChunk(content_delta=str(chunk) if chunk is not None else None)


def _extract_llm_result(value: Any) -> LLMResult:
    if isinstance(value, LLMResult):
        return value
    if isinstance(value, str):
        return LLMResult(content=value)
    if isinstance(value, dict):
        content = _extract_content(value)
        reasoning_content = _extract_reasoning_content(value)
        return LLMResult(
            content=content,
            reasoning_content=reasoning_content,
            usage=_extract_usage(value),
            raw=value,
        )
    return LLMResult(content="" if value is None else str(value))


def _extract_usage(value: Any) -> dict | None:
    if isinstance(value, dict) and isinstance(value.get("usage"), dict):
        return value.get("usage")
    return None


def _extract_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("content"), str):
            return value["content"]
        choices = value.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    return "" if value is None else str(value)


def _extract_reasoning_content(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    direct = _non_empty_string(value.get("reasoning_content") or value.get("reasoning"))
    if direct is not None:
        return direct
    choices = value.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            return _non_empty_string(message.get("reasoning_content") or message.get("reasoning"))
    return None


def _first_choice_delta(value: dict) -> dict | None:
    choices = value.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    delta = first.get("delta")
    return delta if isinstance(delta, dict) else None


def _non_empty_string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _reasoning_metadata(llm_config, reasoning_content: str | None) -> dict:
    values = getattr(llm_config, "values", {}) or {}
    content = reasoning_content if isinstance(reasoning_content, str) and reasoning_content else None
    return {
        # Reasoning is a profile-level output declaration: this profile is expected
        # to return reasoning content. It does not change provider request parameters.
        "expected": bool(values.get("supports_reasoning", False)),
        "received": bool(content),
        "content": content,
    }


class CommandRunner:
    def __init__(
        self,
        command_registry: CommandRegistry,
        runtime_registry: CapabilityRuntimeRegistry,
        run_store: RunStore,
        message_store: MessageStore,
        event_bus: EventBus,
        capability_config_store=None,
        capability_registry: CapabilityRegistry = None,
    ) -> None:
        self.command_registry = command_registry
        self.runtime_registry = runtime_registry
        self.run_store = run_store
        self.message_store = message_store
        self.event_bus = event_bus
        self.capability_config_store = capability_config_store
        self.capability_registry = capability_registry

    async def run(self, command_name: str, args: str, session_id: str, input_message_id: str = "") -> CommandResult:
        try:
            command = self.command_registry.get(command_name)
        except KeyError:
            return CommandResult(
                success=False,
                run_id="",
                error=f"Unknown command: {command_name}",
                error_code="COMMAND_NOT_FOUND",
            )

        if self.capability_config_store is not None and not self.capability_config_store.is_enabled(command.capability_id):
            return CommandResult(
                success=False,
                run_id="",
                error=f"Capability is disabled: {command.capability_id}",
                error_code="CAPABILITY_DISABLED",
            )

        run = self.run_store.create_run(
            kind="command",
            target_id=command_name,
            session_id=session_id,
            metadata={"args": args, "input_message_id": input_message_id or None, "parent_message_id": input_message_id or None},
        )
        self.event_bus.emit("run_started", session_id=session_id, run_id=run.run_id)
        self.run_store.update_status(run.run_id, RunStatus.RUNNING, current_step="running")

        try:
            method = self.runtime_registry.get_method(command.capability_id, command.method)
            data = method(args)
            output_type = self._normalize_output_type(command, data)
            self._validate_output_payload(output_type, data)
        except Exception as exc:
            error = str(exc) or "Command failed."
            failed_run = self.run_store.update_status(
                run.run_id,
                RunStatus.FAILED,
                current_step="failed",
                error=error,
            )
            message = self.message_store.add_message(
                session_id=session_id,
                role="command",
                content=error,
                command_name=command_name,
                run_id=failed_run.run_id,
                output_type="text",
                metadata={"success": False},
            )
            self.event_bus.emit(
                "run_failed",
                session_id=session_id,
                run_id=failed_run.run_id,
                payload={"error": error},
            )
            self.event_bus.emit(
                "message_done",
                session_id=session_id,
                run_id=failed_run.run_id,
                message_id=message.message_id,
            )
            return CommandResult(success=False, run_id=failed_run.run_id, error=error)

        done_run = self.run_store.update_status(run.run_id, RunStatus.DONE, current_step="done")
        message = self.message_store.add_message(
            session_id=session_id,
            role="command",
            content=data,
            command_name=command_name,
            run_id=done_run.run_id,
            output_type=output_type,
            metadata={"success": True},
        )
        self.event_bus.emit("run_done", session_id=session_id, run_id=done_run.run_id)
        self.event_bus.emit(
            "message_done",
            session_id=session_id,
            run_id=done_run.run_id,
            message_id=message.message_id,
        )
        return CommandResult(success=True, run_id=done_run.run_id, data=data, output_type=output_type)

    def _normalize_output_type(self, command, data: Any) -> str:
        declared = self._declared_output_type(command)
        if declared:
            return declared
        if isinstance(data, dict):
            if "url" in data:
                return "image"
            if "images" in data:
                return "image_gallery"
            if "blocks" in data:
                return "rich_content"
            return "json"
        if isinstance(data, list):
            return "json"
        return "text"

    def _declared_output_type(self, command) -> str:
        if self.capability_registry is None:
            return ""
        try:
            capability = self.capability_registry.get(command.capability_id)
        except KeyError:
            return ""
        method = next((item for item in capability.methods if item.id == command.method), None)
        if method is None or not isinstance(method.output, dict):
            return ""
        output_type = method.output.get("type")
        return output_type.strip() if isinstance(output_type, str) and output_type.strip() else ""

    def _validate_output_payload(self, output_type: str, data: Any) -> None:
        if output_type == "image":
            ImagePayload.model_validate(data)
        elif output_type == "image_gallery":
            ImageGalleryPayload.model_validate(data)
        elif output_type == "rich_content":
            RichContentPayload.model_validate(data)
