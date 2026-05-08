import asyncio
import inspect
from typing import Any, AsyncIterator

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.agent_settings import resolved_agent_settings, resolved_context_policy, resolved_model_lifecycle, resolved_prompt, resolved_runtime_override
from ai_workbench.core.attachments import ImageAttachment, is_text_attachment, language_for_filename, read_attachment_as_data_url, read_attachment_text
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.config_schema import resolve_config
from ai_workbench.core.context import ContextBuilder, LLMContextError, group_transcript_identity_instruction, validate_llm_context_messages
from ai_workbench.core.events import EventBus
from ai_workbench.core.llm_config import LLMConfigError, require_llm_model, resolve_llm_config
from ai_workbench.core.llm_stream import LLMResult, LLMStreamChunk, LLMMetricsRecorder
from ai_workbench.core.provider_status import (
    MODEL_MISMATCH,
    MODEL_NOT_AVAILABLE,
    MODEL_STATUS_UNKNOWN,
    PROVIDER_UNREACHABLE,
    refresh_provider_status_for_profile,
    unload_model_for_profile,
)
from ai_workbench.core.run_lifecycle import RunLifecycle
from ai_workbench.core.schema.message import FileContentPayload, ImageGalleryPayload, ImagePayload, RichContentPayload
from ai_workbench.core.schema.result import CommandResult, RunResult
from ai_workbench.core.schema.run import RunSchema, RunStatus
from ai_workbench.core.script import ScriptAgentRunner
from ai_workbench.core.settings import AppSettings
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore
from ai_workbench.core.time import isoformat_utc, utc_now


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

    def active_count(self) -> int:
        return sum(1 for task in self._tasks.values() if not task.done())

    async def cancel_all(self, timeout: float = 2.0) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        self._tasks.clear()


class ActiveLLMUseRegistry:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}

    def acquire(self, provider_profile_id: str, model_id: str) -> tuple[str, str] | None:
        if not provider_profile_id or not model_id:
            return None
        key = (provider_profile_id, model_id)
        self._counts[key] = self._counts.get(key, 0) + 1
        return key

    def release(self, key: tuple[str, str] | None) -> int:
        if key is None:
            return 0
        count = max(0, self._counts.get(key, 0) - 1)
        if count:
            self._counts[key] = count
        else:
            self._counts.pop(key, None)
        return count

    def active_count(self, provider_profile_id: str, model_id: str) -> int:
        return self._counts.get((provider_profile_id, model_id), 0)


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
        provider_profile_store=None,
        llm_defaults_store=None,
        app_settings_store=None,
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
        self.provider_profile_store = provider_profile_store
        self.llm_defaults_store = llm_defaults_store
        self.app_settings_store = app_settings_store
        self.active_runs = active_runs or ActiveRunRegistry()
        self.run_lifecycle = RunLifecycle(run_store, event_bus)
        self.active_llm_uses = ActiveLLMUseRegistry()
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
                provider_profile_store=provider_profile_store,
                llm_defaults_store=llm_defaults_store,
                agent_config_store=agent_config_store,
                run_lifecycle=self.run_lifecycle,
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
        form_id: str = "",
        input_message_id: str = "",
        create_user_message: bool = True,
        display_input: str = "",
        attachments: list[dict] = None,
    ) -> RunResult:
        attachments = attachments or []
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
                form_id=form_id or "",
                input_message_id=input_message_id,
                create_user_message=create_user_message,
                display_input=display_input,
                attachments=attachments,
            )

        if agent.type != "prompt":
            return RunResult(success=False, run_id="", error=f"Unsupported agent type: {agent.type}")

        action = next(item for item in agent.actions if item.id == action_id)
        parent_id = parent_message_id or source_message_id or ""
        current_user_message_id = ""
        if input_message_id and not create_user_message:
            user_message = self.message_store.get_message(input_message_id)
            current_user_message_id = user_message.message_id
        elif create_user_message and (action_id == "default" or display_input):
            raw_text = display_input or args
            user_message = self.message_store.add_message(
                session_id=session_id,
                role="user",
                content=raw_text,
                agent_id=agent_id,
                action_id=action_id,
                metadata={
                    "attachments": attachments,
                    "input_source": "text",
                    "invocation": {
                        "route_type": "agent",
                        "agent_id": agent_id,
                        "action_id": action_id,
                        "raw_text": raw_text,
                        "args": args,
                    },
                },
                speaker_type="user",
                speaker_id="local_user",
                speaker_name="User",
                origin="user_message",
            )
            current_user_message_id = user_message.message_id
        if current_user_message_id and not parent_id:
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
        self._emit_prompt_message_started(
            agent=agent,
            action_id=action_id,
            session_id=session_id,
            run=run,
            parent_id=parent_id,
        )
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
        self.run_lifecycle.start_run(run.run_id, stage="running")
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
        except asyncio.CancelledError:
            try:
                current_run = self.run_store.get_run(run.run_id)
                if current_run.status in {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.CANCELLING, RunStatus.WAITING_FOR_USER}:
                    self.run_lifecycle.cancel_run(run.run_id)
            except KeyError:
                pass
            return RunResult(success=False, run_id=run.run_id, error="Run was cancelled.", data=None)
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
        resolving_agent_step = self.run_lifecycle.start_step(run.run_id, "Resolving agent")
        agent_config = self.agent_config_store.get_config(agent.id) if self.agent_config_store is not None else {}
        lifecycle = resolved_model_lifecycle(agent, agent_config)
        run_metadata = dict(self.run_store.get_run(run.run_id).metadata)
        run_metadata["resolved_runtime"] = resolved_agent_settings(agent, agent_config)["runtime"]
        self.run_store.update_metadata(run.run_id, run_metadata)
        self.run_lifecycle.complete_step(resolving_agent_step.step_id)
        context_policy = resolved_context_policy(agent, action, agent_config)
        context_step = self.run_lifecycle.start_step(run.run_id, "Building context")
        session = self.session_store.get_session(session_id) if self.session_store is not None else None
        context_mode = getattr(session, "context_mode", "single_assistant") or "single_assistant"
        app_settings = self._app_settings()
        try:
            context = self.context_builder.build(
                session_id=session_id,
                args=args,
                policy=context_policy,
                source_message_id=source_message_id or None,
                current_message_id=current_user_message_id or None,
                context_mode=context_mode,
                current_agent_id=agent.id,
                current_agent_name=agent.name,
                command_result_context_instruction=app_settings.command_result_context_instruction,
            )
        except KeyError as exc:
            error = str(exc)
            self.run_lifecycle.fail_step(context_step.step_id, error_message=error)
            failed_run = self.run_lifecycle.fail_run(run.run_id, "CONTEXT_BUILD_FAILED", error)
            return RunResult(success=False, run_id=failed_run.run_id, error=error)
        self.run_lifecycle.complete_step(context_step.step_id)

        messages = []
        prompt = resolved_prompt(agent, agent_config)
        if prompt:
            if action.instruction:
                prompt = f"{prompt.rstrip()}\n\n{action.instruction}"
            if context_mode == "group_transcript":
                prompt = f"{prompt.rstrip()}\n\n{group_transcript_identity_instruction(agent.name, agent.id, app_settings.group_transcript_system_instruction)}"
            messages.append({"role": "system", "content": prompt})
        messages.extend(context.messages)

        llm_config = None
        llm_use_key = None
        llm_started = False
        cleanup_done = False
        resolving_model_step = None
        calling_llm_step = None
        try:
            resolving_model_step = self.run_lifecycle.start_step(run.run_id, "Resolving model")
            llm_config = self._resolve_llm_model_config(agent, action, session_id)
            require_llm_model(llm_config)
            file_context = _prepare_file_context_messages(
                messages=messages,
                message_store=self.message_store,
                current_user_message_id=current_user_message_id,
                settings=self._app_settings(),
            )
            messages = file_context["messages"]
            vision_input = _prepare_vision_messages(
                messages=messages,
                message_store=self.message_store,
                current_user_message_id=current_user_message_id,
                llm_config=llm_config,
            )
            messages = vision_input["messages"]
            messages = validate_llm_context_messages(messages)
            context_warnings = [*context.warnings, *file_context["warnings"], *vision_input["warnings"]]
            self._record_llm_resolution(run.run_id, llm_config)
            self._record_file_context_metadata(run.run_id, file_context["metadata"])
            self._record_vision_metadata(run.run_id, vision_input["metadata"])
            self.run_lifecycle.complete_step(resolving_model_step.step_id)
            llm_use_key = self._begin_llm_use(llm_config)
            llm_started = True
            calling_llm_step = self.run_lifecycle.start_step(run.run_id, "Calling LLM", message="Waiting for model response...")
            if _streaming_enabled(llm_config):
                cleanup_done = True
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
                    context_warnings=context_warnings,
                    llm_config=llm_config,
                    vision_input=vision_input["metadata"],
                    file_context=file_context["metadata"],
                    lifecycle=lifecycle,
                    llm_use_key=llm_use_key,
                    calling_llm_step_id=calling_llm_step.step_id,
                )
            metrics_recorder = LLMMetricsRecorder(streamed=False)
            raw_content = await _call_chat_nonstream(self.llm_runtime, messages, llm_config.values)
            llm_result = _extract_llm_result(raw_content)
            content = llm_result.content
            llm_metrics = metrics_recorder.complete(content, llm_result.usage)
            self.run_lifecycle.complete_step(calling_llm_step.step_id)
        except LLMConfigError as exc:
            if resolving_model_step is not None:
                self.run_lifecycle.fail_step(resolving_model_step.step_id, error_code=exc.code, error_message=exc.message)
            failed_run = self.run_lifecycle.fail_run(run.run_id, exc.code, exc.message)
            return RunResult(success=False, run_id=failed_run.run_id, error=exc.message, error_code=exc.code)
        except LLMContextError as exc:
            if resolving_model_step is not None:
                self.run_lifecycle.fail_step(resolving_model_step.step_id, error_code=exc.code, error_message=exc.message)
            failed_run = self.run_lifecycle.fail_run(run.run_id, exc.code, exc.message)
            return RunResult(success=False, run_id=failed_run.run_id, error=exc.message, error_code=exc.code)
        except asyncio.CancelledError:
            if llm_started and not cleanup_done and llm_config is not None:
                self._finish_llm_use_and_apply_lifecycle(lifecycle, llm_config, llm_use_key, run.run_id, session_id)
                cleanup_done = True
            raise
        except Exception as exc:
            friendly = _friendly_llm_error(exc, locals().get("llm_config", None))
            error = friendly["message"]
            if calling_llm_step is not None:
                self.run_lifecycle.fail_step(calling_llm_step.step_id, error_code=friendly["code"], error_message=error)
            elif resolving_model_step is not None:
                self.run_lifecycle.fail_step(resolving_model_step.step_id, error_code=friendly["code"], error_message=error)
            failed_run = self.run_lifecycle.fail_run(run.run_id, friendly["code"], error)
            self._record_run_error_metadata(run.run_id, friendly)
            if llm_started and not cleanup_done and llm_config is not None:
                self._finish_llm_use_and_apply_lifecycle(lifecycle, llm_config, llm_use_key, failed_run.run_id, session_id)
                cleanup_done = True
            return RunResult(success=False, run_id=failed_run.run_id, error=error, error_code=friendly["code"])

        if self._is_cancelled(run.run_id):
            cancelled_run = self.run_lifecycle.cancel_run(run.run_id)
            return RunResult(success=False, run_id=cancelled_run.run_id, error="Run was cancelled.", data=None)

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
            "vision_input": vision_input["metadata"],
            "file_context": file_context["metadata"],
            "reasoning": _reasoning_metadata(llm_config, llm_result.reasoning_content),
            "llm": _llm_message_metadata(llm_config, llm_result.raw),
        }
        if llm_result.reasoning_content:
            metadata["reasoning_content"] = llm_result.reasoning_content
        self._record_llm_metadata(run.run_id, llm_config, llm_metrics, vision_input["metadata"], file_context["metadata"], llm_raw=llm_result.raw)
        saving_step = self.run_lifecycle.start_step(run.run_id, "Saving response")
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
            speaker_type="agent",
            speaker_id=agent.id,
            speaker_name=agent.name,
            origin="agent_reply",
        )
        message_actions = self._available_actions(agent, source_message_id=message.message_id)
        if message_actions:
            message = message.model_copy(update={"available_actions": message_actions})
            self.message_store.update_message(message)
        self.run_lifecycle.complete_step(saving_step.step_id)
        cleanup_step = self.run_lifecycle.start_step(run.run_id, "Cleanup")
        unload_message = None
        if llm_started and not cleanup_done:
            unload_result = self._finish_llm_use_and_apply_lifecycle(lifecycle, llm_config, llm_use_key, run.run_id, session_id)
            unload_message = _llm_unload_message(unload_result) if unload_result else None
        self.run_lifecycle.complete_step(cleanup_step.step_id, message=unload_message, metadata={"llm_unload": unload_result} if unload_message else None)
        done_run = self.run_lifecycle.complete_run(run.run_id)
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

        return RunResult(success=True, run_id=done_run.run_id, data=content)

    def _emit_prompt_message_started(self, agent, action_id: str, session_id: str, run: RunSchema, parent_id: str = "", llm_resolution: dict | None = None) -> str:
        draft_message_id = f"draft-{run.run_id}"
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
                "action_id": action_id,
                "parent_message_id": parent_id or None,
                "created_at": isoformat_utc(utc_now()),
                "llm_resolution": llm_resolution or None,
            },
        )
        return draft_message_id

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
        vision_input: dict,
        file_context: dict,
        lifecycle,
        llm_use_key: tuple[str, str] | None,
        calling_llm_step_id: str,
    ) -> RunResult:
        resolution = _public_llm_resolution(llm_config)
        draft_message_id = self._emit_prompt_message_started(
            agent=agent,
            action_id=action_id,
            session_id=session_id,
            run=run,
            parent_id=parent_id,
            llm_resolution=resolution,
        )
        metrics_recorder = LLMMetricsRecorder(streamed=True)
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage = None
        actual_raw = None
        seq = 0
        try:
            async for chunk in _call_chat_stream(self.llm_runtime, messages, llm_config.values):
                normalized = _normalize_stream_chunk(chunk)
                if normalized.raw:
                    actual_raw = _merge_stream_metadata(actual_raw, normalized.raw)
                if normalized.usage:
                    usage = normalized.usage
                if normalized.reasoning_delta:
                    metrics_recorder.mark_first_token()
                    reasoning_parts.append(normalized.reasoning_delta)
                    seq += 1
                    self.event_bus.emit(
                        "message_delta",
                        session_id=session_id,
                        run_id=run.run_id,
                        message_id=draft_message_id,
                        payload={"seq": seq, "delta": "", "reasoning_delta": normalized.reasoning_delta},
                    )
                if normalized.content_delta:
                    metrics_recorder.mark_first_token()
                    content_parts.append(normalized.content_delta)
                    seq += 1
                    self.event_bus.emit(
                        "message_delta",
                        session_id=session_id,
                        run_id=run.run_id,
                        message_id=draft_message_id,
                        payload={"seq": seq, "delta": normalized.content_delta, "reasoning_delta": None},
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
                    vision_input=vision_input,
                    file_context=file_context,
                    reasoning_content="".join(reasoning_parts),
                    interrupted=True,
                    llm_raw=actual_raw,
                )
                self.event_bus.emit(
                    "message_completed",
                    session_id=session_id,
                    run_id=run.run_id,
                    message_id=message.message_id,
                    payload={"seq": seq + 1, "message": message.model_dump(mode="json"), "draft_message_id": draft_message_id},
                )
                self.event_bus.emit(
                    "message_done",
                    session_id=session_id,
                    run_id=run.run_id,
                    message_id=message.message_id,
                    payload={"available_actions": message.available_actions},
                )
            self.run_lifecycle.fail_step(calling_llm_step_id, error_code="RUN_CANCELLED", error_message="Run was cancelled.")
            cancelled_run = self.run_lifecycle.cancel_run(run.run_id)
            self._record_llm_metadata(run.run_id, llm_config, llm_metrics, vision_input, file_context, llm_raw=actual_raw)
            self.event_bus.emit(
                "run_metrics",
                session_id=session_id,
                run_id=run.run_id,
                payload={"metrics": llm_metrics},
            )
            self._finish_llm_use_and_apply_lifecycle(lifecycle, llm_config, llm_use_key, cancelled_run.run_id, session_id)
            return RunResult(success=False, run_id=cancelled_run.run_id, error="Run was cancelled.", data=content)
        except Exception as exc:
            friendly = _friendly_llm_error(exc, llm_config)
            error = friendly["message"]
            self.run_lifecycle.fail_step(calling_llm_step_id, error_code=friendly["code"], error_message=error)
            failed_run = self.run_lifecycle.fail_run(run.run_id, friendly["code"], error)
            self._record_run_error_metadata(run.run_id, friendly)
            self._finish_llm_use_and_apply_lifecycle(lifecycle, llm_config, llm_use_key, failed_run.run_id, session_id)
            return RunResult(success=False, run_id=failed_run.run_id, error=error, error_code=friendly["code"])

        content = "".join(content_parts)
        llm_metrics = metrics_recorder.complete(content, usage)
        self.run_lifecycle.complete_step(calling_llm_step_id)
        saving_step = self.run_lifecycle.start_step(run.run_id, "Saving response")
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
            vision_input=vision_input,
            file_context=file_context,
            reasoning_content="".join(reasoning_parts),
            llm_raw=actual_raw,
        )
        self.run_lifecycle.complete_step(saving_step.step_id)
        self._record_llm_metadata(run.run_id, llm_config, llm_metrics, vision_input, file_context, llm_raw=actual_raw)
        cleanup_step = self.run_lifecycle.start_step(run.run_id, "Cleanup")
        unload_result = self._finish_llm_use_and_apply_lifecycle(lifecycle, llm_config, llm_use_key, run.run_id, session_id)
        unload_message = _llm_unload_message(unload_result) if unload_result else None
        self.run_lifecycle.complete_step(cleanup_step.step_id, message=unload_message, metadata={"llm_unload": unload_result} if unload_message else None)
        done_run = self.run_lifecycle.complete_run(run.run_id)
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
            payload={"seq": seq + 1, "message": message.model_dump(mode="json"), "draft_message_id": draft_message_id},
        )
        self.event_bus.emit(
            "message_done",
            session_id=session_id,
            run_id=done_run.run_id,
            message_id=message.message_id,
            payload={"available_actions": message.available_actions},
        )
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
        vision_input: dict,
        file_context: dict,
        reasoning_content: str = "",
        interrupted: bool = False,
        llm_raw: dict | None = None,
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
            "vision_input": vision_input,
            "file_context": file_context,
            "reasoning": _reasoning_metadata(llm_config, reasoning_content),
            "llm": _llm_message_metadata(llm_config, llm_raw),
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
            speaker_type="agent",
            speaker_id=agent.id,
            speaker_name=agent.name,
            origin="agent_reply",
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
            provider_profile_store=self.provider_profile_store,
            llm_defaults_store=self.llm_defaults_store,
            session_llm_profile_id=session_llm_profile_id,
            agent_runtime=resolved_runtime_override(self.agent_config_store.get_config(agent.id) if self.agent_config_store is not None else {}),
        )

    def _record_llm_resolution(self, run_id: str, llm_config) -> None:
        run = self.run_store.get_run(run_id)
        metadata = dict(run.metadata)
        metadata["llm_resolution"] = _public_llm_resolution(llm_config)
        self.run_store.update_metadata(run_id, metadata)

    def _record_vision_metadata(self, run_id: str, vision_input: dict) -> None:
        run = self.run_store.get_run(run_id)
        metadata = dict(run.metadata)
        metadata["vision_input"] = vision_input
        self.run_store.update_metadata(run_id, metadata)

    def _record_file_context_metadata(self, run_id: str, file_context: dict) -> None:
        run = self.run_store.get_run(run_id)
        metadata = dict(run.metadata)
        metadata["file_context"] = file_context
        self.run_store.update_metadata(run_id, metadata)

    def _record_llm_metadata(self, run_id: str, llm_config, llm_metrics: dict, vision_input: dict | None = None, file_context: dict | None = None, llm_raw: dict | None = None) -> None:
        run = self.run_store.get_run(run_id)
        metadata = dict(run.metadata)
        metadata["llm_resolution"] = _public_llm_resolution(llm_config)
        metadata["llm"] = _llm_message_metadata(llm_config, llm_raw)
        metadata["llm_metrics"] = llm_metrics
        if vision_input is not None:
            metadata["vision_input"] = vision_input
        if file_context is not None:
            metadata["file_context"] = file_context
        self.run_store.update_metadata(run_id, metadata)

    def _record_run_error_metadata(self, run_id: str, friendly: dict) -> None:
        run = self.run_store.get_run(run_id)
        metadata = dict(run.metadata)
        metadata["error"] = friendly
        self.run_store.update_metadata(run_id, metadata)

    def _app_settings(self):
        if self.app_settings_store is None:
            return AppSettings()
        return self.app_settings_store.get()

    def _is_cancelled(self, run_id: str) -> bool:
        try:
            run = self.run_store.get_run(run_id)
            return run.status in {RunStatus.CANCELLED, RunStatus.CANCELLING} or run.cancel_requested
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

    def _begin_llm_use(self, llm_config) -> tuple[str, str] | None:
        target = _llm_unload_target(llm_config)
        return self.active_llm_uses.acquire(target["provider_profile_id"], target["model_id"])

    def _finish_llm_use_and_apply_lifecycle(self, lifecycle, llm_config, llm_use_key: tuple[str, str] | None, run_id: str, session_id: str) -> dict | None:
        remaining = self.active_llm_uses.release(llm_use_key)
        if lifecycle.unload != "after_run":
            return None
        target = _llm_unload_target(llm_config)
        if remaining > 0:
            result = {
                "ok": True,
                "provider": target["provider"],
                "provider_profile_id": target["provider_profile_id"],
                "provider_profile_name": target["provider_profile_name"],
                "model_profile_id": target["model_profile_id"],
                "model_profile_name": target["model_profile_name"],
                "requested_model_id": target["model_id"],
                "model_id": target["model_id"],
                "unloaded": [],
                "skipped": True,
                "skip_reason": "model still in use by another active run",
                "errors": [],
                "reason": "after_run",
            }
        else:
            result = self._unload_model_for_llm_config(llm_config, reason="after_run")
            _enrich_unload_result(result, target)
            self._refresh_provider_status_after_unload(result, session_id=session_id, run_id=run_id)
        self._record_llm_unload_metadata(run_id, lifecycle, result)
        if not result.get("ok") and lifecycle.unload_failure == "warn":
            self.event_bus.emit(
                "run_warning",
                session_id=session_id,
                run_id=run_id,
                payload={"warning": _first_unload_message(result)},
            )
        return result

    def _unload_model_for_llm_config(self, llm_config, reason: str = "after_run") -> dict:
        target = _llm_unload_target(llm_config)
        if self.provider_profile_store is not None and self.llm_profile_store is not None:
            return unload_model_for_profile(
                provider_profile_store=self.provider_profile_store,
                llm_profile_store=self.llm_profile_store,
                provider_profile_id=target["provider_profile_id"],
                model_profile_id=target["model_profile_id"],
                model_id=target["model_id"],
                reason=reason,
            )
        unload = getattr(self.llm_runtime, "unload", None)
        if callable(unload):
            try:
                legacy = unload(model_config=getattr(llm_config, "values", {}) or {})
                ok = bool(legacy.get("success")) if isinstance(legacy, dict) else bool(legacy)
                return {
                    "ok": ok,
                    "provider": target["provider"],
                    "provider_profile_id": target["provider_profile_id"],
                    "model_id": target["model_id"],
                    "unloaded": [],
                    "skipped": False,
                    "skip_reason": None,
                    "errors": [] if ok else [{"code": "MODEL_UNLOAD_FAILED", "message": str((legacy or {}).get("message") or "Model unload failed.")}],
                    "reason": reason,
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "provider": target["provider"],
                    "provider_profile_id": target["provider_profile_id"],
                    "model_id": target["model_id"],
                    "unloaded": [],
                    "skipped": False,
                    "skip_reason": None,
                    "errors": [{"code": "MODEL_UNLOAD_FAILED", "message": str(exc) or "Model unload failed."}],
                    "reason": reason,
                }
        return {
            "ok": False,
            "code": "MODEL_UNLOAD_UNSUPPORTED",
            "provider": target["provider"],
            "provider_profile_id": target["provider_profile_id"],
            "model_id": target["model_id"],
            "unloaded": [],
            "skipped": False,
            "skip_reason": None,
            "errors": [{"code": "MODEL_UNLOAD_UNSUPPORTED", "message": "Model unload is not supported by this runtime."}],
            "reason": reason,
        }

    def _refresh_provider_status_after_unload(self, result: dict, session_id: str, run_id: str) -> None:
        provider_profile_id = str(result.get("provider_profile_id") or "")
        status_refresh = {
            "attempted": False,
            "ok": False,
            "provider_profile_id": provider_profile_id,
        }
        result["status_refresh"] = status_refresh
        if not provider_profile_id or self.provider_profile_store is None or self.llm_profile_store is None:
            status_refresh["error"] = "Provider stores are not available."
            return
        try:
            status = refresh_provider_status_for_profile(self.provider_profile_store, self.llm_profile_store, provider_profile_id)
            status_refresh.update({"attempted": True, "ok": True, "status": status})
            self.event_bus.emit(
                "llm_provider_status_updated",
                session_id=session_id,
                run_id=run_id,
                payload={"provider": status},
            )
        except Exception as exc:
            status_refresh.update({"attempted": True, "ok": False, "error": str(exc) or "Provider status refresh failed."})

    def _record_llm_unload_metadata(self, run_id: str, lifecycle, result: dict) -> None:
        run = self.run_store.get_run(run_id)
        metadata = dict(run.metadata)
        status_refresh = result.get("status_refresh") if isinstance(result.get("status_refresh"), dict) else {}
        metadata["llm_unload"] = {
            "policy": lifecycle.unload,
            "attempted": not bool(result.get("skipped")),
            "ok": bool(result.get("ok")),
            "status_refresh_attempted": bool(status_refresh.get("attempted")),
            "status_refresh_ok": bool(status_refresh.get("ok")),
            "status_refresh_error": status_refresh.get("error"),
            "provider": result.get("provider"),
            "provider_profile_id": result.get("provider_profile_id"),
            "provider_profile_name": result.get("provider_profile_name"),
            "model_profile_id": result.get("model_profile_id"),
            "model_profile_name": result.get("model_profile_name"),
            "requested_model_id": result.get("requested_model_id") or result.get("model_id"),
            "actual_model_id": result.get("actual_model_id"),
            "model_id": result.get("model_id"),
            "unloaded_count": len(result.get("unloaded") or []),
            "skipped": bool(result.get("skipped")),
            "skip_reason": result.get("skip_reason"),
            "code": result.get("code"),
            "errors": result.get("errors") or [],
            "result": result,
        }
        if not result.get("ok") and lifecycle.unload_failure == "warn":
            warnings = list(metadata.get("warnings", []))
            warnings.append(_first_unload_message(result))
            metadata["warnings"] = warnings
        self.run_store.update_metadata(run_id, metadata)

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
        "provider_profile_id": metadata.get("provider_profile_id"),
        "provider_profile_name": metadata.get("provider_profile_name"),
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


def _llm_unload_target(llm_config) -> dict:
    metadata = dict(getattr(llm_config, "metadata", {}) or {})
    values = getattr(llm_config, "values", {}) or {}
    return {
        "provider": metadata.get("provider") or values.get("provider") or "",
        "provider_profile_id": metadata.get("provider_profile_id") or values.get("provider_profile_id") or "",
        "model_profile_id": metadata.get("profile_id") or values.get("model_profile_id") or "",
        "model_profile_name": metadata.get("profile_name") or values.get("model_profile_name") or "",
        "provider_profile_name": metadata.get("provider_profile_name") or values.get("provider_profile_name") or "",
        "model_id": values.get("model_id") or values.get("model") or "",
    }


def _enrich_unload_result(result: dict, target: dict) -> dict:
    result.setdefault("provider", target.get("provider") or "")
    result.setdefault("provider_profile_id", target.get("provider_profile_id") or "")
    result.setdefault("provider_profile_name", target.get("provider_profile_name") or "")
    result.setdefault("model_profile_id", target.get("model_profile_id") or "")
    result.setdefault("model_profile_name", target.get("model_profile_name") or "")
    result.setdefault("requested_model_id", target.get("model_id") or "")
    result.setdefault("model_id", target.get("model_id") or "")
    return result


def _first_unload_message(result: dict) -> str:
    errors = result.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("message") or first.get("code") or "Model unload failed.")
    if result.get("skip_reason"):
        return str(result["skip_reason"])
    if result.get("message"):
        return str(result["message"])
    return "Model unload failed or is unsupported."


def _llm_display_name(result: dict | None) -> str:
    if not isinstance(result, dict):
        return "model"
    return str(
        result.get("model_profile_name")
        or result.get("requested_model_id")
        or result.get("model_id")
        or result.get("actual_model_id")
        or "model"
    )


def _llm_unload_message(result: dict | None) -> str | None:
    if not isinstance(result, dict):
        return None
    if result.get("skipped"):
        return "Unload skipped: model still in use."
    code = result.get("code") or _first_error_code(result)
    if code == "MODEL_UNLOAD_UNSUPPORTED":
        return "Unload unsupported by provider."
    if result.get("ok"):
        return f"Unloaded local LLM: {_llm_display_name(result)}"
    return f"Unload failed: {_first_unload_message(result)}"


def _first_error_code(result: dict) -> str:
    errors = result.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("code") or "")
    return ""


def _llm_message_metadata(llm_config, raw: dict | None = None) -> dict:
    resolution = _public_llm_resolution(llm_config)
    requested = str(resolution.get("model_id") or "")
    actual = _actual_model_id(raw) or requested
    actual_missing = not bool(_actual_model_id(raw))
    system_fingerprint = _system_fingerprint(raw)
    return {
        "provider_profile_id": resolution.get("provider_profile_id"),
        "provider_profile_name": resolution.get("provider_profile_name"),
        "model_profile_id": resolution.get("profile_id"),
        "model_profile_name": resolution.get("profile_name"),
        "requested_model_id": requested,
        "actual_model_id": actual,
        "actual_model_missing": actual_missing,
        "system_fingerprint": system_fingerprint,
        "model_mismatch": bool(actual and requested and actual != requested),
        "resolution_source": resolution.get("source"),
    }


def _actual_model_id(raw: dict | None) -> str | None:
    if not isinstance(raw, dict):
        return None
    direct = raw.get("model")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    for key in ("response", "final", "metadata"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            value = nested.get("model")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _system_fingerprint(raw: dict | None) -> str | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get("system_fingerprint")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _merge_stream_metadata(current: dict | None, raw: dict) -> dict:
    result = dict(current or {})
    if _actual_model_id(raw) and not _actual_model_id(result):
        result["model"] = _actual_model_id(raw)
    if _system_fingerprint(raw) and not _system_fingerprint(result):
        result["system_fingerprint"] = _system_fingerprint(raw)
    if isinstance(raw.get("usage"), dict):
        result["usage"] = raw.get("usage")
    return result


def _friendly_llm_error(exc: Exception, llm_config=None) -> dict:
    values = getattr(llm_config, "values", {}) or {}
    resolution = _public_llm_resolution(llm_config) if llm_config is not None else {}
    raw = str(exc) or exc.__class__.__name__
    provider_name = resolution.get("provider_profile_name") or values.get("provider") or "provider"
    base_url = values.get("base_url") or resolution.get("base_url") or ""
    requested = values.get("model_id") or values.get("model") or resolution.get("model_id") or ""
    lowered = raw.lower()
    code = "RUN_FAILED"
    message = raw or "Prompt agent failed."
    if "connect" in lowered or "connection" in lowered or "unreachable" in lowered or "refused" in lowered:
        code = PROVIDER_UNREACHABLE
        message = f"Cannot connect to {provider_name} at {base_url}."
    elif "model_not_available" in lowered or "model not available" in lowered or "not found" in lowered:
        code = MODEL_NOT_AVAILABLE
        message = "The requested model is not available from this provider.\nChoose a model from the refreshed provider model list or update the Model ID."
    elif "model_mismatch" in lowered or "different model" in lowered:
        code = MODEL_MISMATCH
        message = f"The provider replied with a different model than requested.\nRequested: {requested}"
    elif "model_status_unknown" in lowered:
        code = MODEL_STATUS_UNKNOWN
        message = "The provider status is unknown. Refresh the provider status and try again."
    return {
        "code": code,
        "message": message,
        "details": {
            "raw_error": raw,
            "provider_profile_id": resolution.get("provider_profile_id"),
            "provider_profile_name": resolution.get("provider_profile_name"),
            "requested_model_id": requested,
            "base_url": base_url,
        },
    }


def _streaming_enabled(llm_config) -> bool:
    values = getattr(llm_config, "values", {}) or {}
    return values.get("supports_streaming") is True


MAX_LLM_TEXT_ATTACHMENT_BYTES = 200 * 1024
MAX_LLM_TEXT_ATTACHMENTS_BYTES = 500 * 1024


def _prepare_file_context_messages(messages: list, message_store: MessageStore, current_user_message_id: str, settings=None) -> dict:
    enabled = True if settings is None else bool(settings.send_text_file_attachments_to_llm)
    attachments, warnings = _current_file_attachments(message_store, current_user_message_id, settings=settings)
    text_attachments = [item for item in attachments if item.get("text")]
    files_attached = len(attachments)
    files_sent = len(text_attachments)
    files_ignored = files_attached - files_sent
    total_chars = sum(len(item["text"]["content"]) for item in text_attachments)
    metadata = {
        "enabled": enabled,
        "files_attached": files_attached,
        "files_sent": files_sent,
        "files_ignored": files_ignored,
        "total_chars": total_chars,
    }
    if warnings:
        metadata["warnings"] = warnings
    if not attachments:
        return {"messages": messages, "metadata": metadata, "warnings": warnings}

    next_messages = [dict(message) for message in messages]
    target_index = _last_user_message_index(next_messages)
    if target_index is None:
        return {"messages": next_messages, "metadata": metadata, "warnings": warnings}

    current = next_messages[target_index]
    text = str(current.get("content") or "")
    additions = []
    if files_attached and not enabled:
        suffix = "" if files_attached == 1 else "s"
        additions.append(f"User attached {files_attached} text file{suffix}, but file context is disabled.")
    elif text_attachments:
        if not text.strip():
            suffix = "" if files_sent == 1 else "s"
            additions.append(f"User attached {files_sent} text file{suffix}.")
        for item in text_attachments:
            payload = item["text"]
            additions.append(_format_text_attachment_for_llm(payload))
    if files_ignored:
        suffix = "" if files_ignored == 1 else "s"
        additions.append(f"User attached {files_ignored} file{suffix} that {'is' if files_ignored == 1 else 'are'} not readable as text.")
    if additions:
        current["content"] = "\n\n".join(part for part in [text.strip(), *additions] if part)
    return {"messages": next_messages, "metadata": metadata, "warnings": warnings}


def _current_file_attachments(message_store: MessageStore, current_user_message_id: str, settings=None) -> tuple[list[dict[str, Any]], list[str]]:
    if not current_user_message_id:
        return [], []
    try:
        message = message_store.get_message(current_user_message_id)
    except KeyError:
        return [], ["current user message was not found for file context"]
    raw_attachments = (message.metadata or {}).get("attachments")
    if not isinstance(raw_attachments, list):
        return [], []

    attachments: list[dict[str, Any]] = []
    warnings: list[str] = []
    enabled = True if settings is None else bool(settings.send_text_file_attachments_to_llm)
    per_file_limit = getattr(settings, "max_file_context_per_file_bytes", MAX_LLM_TEXT_ATTACHMENT_BYTES)
    total_limit = getattr(settings, "max_total_file_context_per_message_bytes", MAX_LLM_TEXT_ATTACHMENTS_BYTES)
    remaining = total_limit
    for index, raw_attachment in enumerate(raw_attachments, start=1):
        if not isinstance(raw_attachment, dict) or raw_attachment.get("type") != "file":
            continue
        item = {"text": None}
        try:
            if not is_text_attachment(raw_attachment):
                attachments.append(item)
                continue
            if not enabled:
                attachments.append(item)
                continue
            limit = max(0, min(per_file_limit, remaining))
            if limit <= 0:
                warnings.append(f"file attachment {index} was ignored: text attachment context limit reached")
                attachments.append(item)
                continue
            payload = read_attachment_text(raw_attachment, limit=limit)
            remaining = max(0, remaining - min(int(payload.get("size") or 0), limit))
            item["text"] = payload
            attachments.append(item)
        except Exception as exc:
            attachments.append(item)
            warnings.append(f"file attachment {index} was ignored: {str(exc) or 'unreadable text attachment'}")
    return attachments, warnings


def _format_text_attachment_for_llm(payload: dict[str, Any]) -> str:
    filename = str(payload.get("filename") or "attached file")
    mime_type = str(payload.get("mime_type") or "text/plain")
    size = int(payload.get("size") or 0)
    truncated = bool(payload.get("truncated"))
    language = str(payload.get("language") or language_for_filename(filename) or "text")
    content = str(payload.get("content") or "")
    return (
        f"User attached file: {filename}\n"
        f"MIME: {mime_type}\n"
        f"Size: {_format_attachment_size(size)}\n"
        f"Truncated: {'true' if truncated else 'false'}\n\n"
        f"```{language}\n{content}\n```"
    )


def _format_attachment_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _prepare_vision_messages(messages: list, message_store: MessageStore, current_user_message_id: str, llm_config) -> dict:
    supported = bool((getattr(llm_config, "values", {}) or {}).get("supports_vision", False))
    attachments, warnings = _current_image_attachments(message_store, current_user_message_id, resolve_data=supported)
    valid_attachments = [item for item in attachments if item.get("valid")]
    images_attached = len(attachments)
    images_sent = len(valid_attachments) if supported else 0
    images_ignored = images_attached - images_sent
    metadata = {
        "supported": supported,
        "images_attached": images_attached,
        "images_sent": images_sent,
        "images_ignored": images_ignored,
    }
    if warnings:
        metadata["warnings"] = warnings
    if not images_attached:
        return {"messages": messages, "metadata": metadata, "warnings": warnings}

    next_messages = [dict(message) for message in messages]
    target_index = _last_user_message_index(next_messages)
    if target_index is None:
        return {"messages": next_messages, "metadata": metadata, "warnings": warnings}

    current = next_messages[target_index]
    text = str(current.get("content") or "")
    if text == _generic_image_placeholder(images_attached):
        text = ""
    if supported and images_attached and not valid_attachments and not text.strip():
        raise ValueError("No readable image attachments were available for the vision model.")
    if supported and valid_attachments:
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": text.strip() or "Please analyze the attached image."}]
        content_parts.extend(
            {"type": "image_url", "image_url": {"url": attachment["data_url"]}}
            for attachment in valid_attachments
        )
        current["content"] = content_parts
    elif images_attached:
        current["content"] = _append_image_placeholder(text, images_attached)
    return {"messages": next_messages, "metadata": metadata, "warnings": warnings}


def _current_image_attachments(message_store: MessageStore, current_user_message_id: str, resolve_data: bool = True) -> tuple[list[dict[str, Any]], list[str]]:
    if not current_user_message_id:
        return [], []
    try:
        message = message_store.get_message(current_user_message_id)
    except KeyError:
        return [], ["current user message was not found for vision input"]
    raw_attachments = (message.metadata or {}).get("attachments")
    if not isinstance(raw_attachments, list):
        return [], []

    attachments: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, raw_attachment in enumerate(raw_attachments, start=1):
        if not isinstance(raw_attachment, dict) or raw_attachment.get("type") != "image":
            continue
        try:
            attachment = ImageAttachment.model_validate(raw_attachment)
            data = attachment.model_dump(exclude_none=True)
            if resolve_data:
                data_url = read_attachment_as_data_url(data)
                if _vision_data_url_mime_type(data_url) != attachment.mime_type:
                    raise ValueError("Attachment MIME type does not match image data.")
                data["data_url"] = data_url
            else:
                data.pop("data_url", None)
            data["valid"] = True
            attachments.append(data)
        except Exception as exc:
            attachments.append({"valid": False})
            warnings.append(f"image attachment {index} was ignored: {str(exc) or 'invalid image attachment'}")
    return attachments, warnings


def _last_user_message_index(messages: list) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index
    return None


def _vision_data_url_mime_type(data_url: str) -> str:
    prefix = str(data_url or "").split(";", 1)[0]
    if not prefix.startswith("data:"):
        return ""
    return prefix.removeprefix("data:").lower()


def _append_image_placeholder(text: str, image_count: int) -> str:
    suffix = "s" if image_count != 1 else ""
    placeholder = f"User attached {image_count} image{suffix}, but the selected model does not support vision."
    if text.strip():
        return f"{text.rstrip()}\n\n{placeholder}"
    return placeholder


def _generic_image_placeholder(image_count: int) -> str:
    suffix = "s" if image_count != 1 else ""
    return f"User attached {image_count} image{suffix}."


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
            raw=value.get("raw") if isinstance(value.get("raw"), dict) else value,
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
            data = self._call_method(method, args, self._command_context(session_id, input_message_id, command.capability_id))
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
            command_metadata = self._command_result_metadata(
                command_name=command_name,
                command=command,
                output_type="text",
                input_message_id=input_message_id,
                success=False,
            )
            message = self.message_store.add_message(
                session_id=session_id,
                role="assistant",
                content=error,
                command_name=command_name,
                run_id=failed_run.run_id,
                output_type="text",
                parent_message_id=input_message_id or None,
                metadata=command_metadata,
                speaker_type="capability",
                speaker_id=command.capability_id,
                speaker_name=command_metadata.get("capability_name") or command_name,
                origin="command_result",
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
        command_metadata = self._command_result_metadata(
            command_name=command_name,
            command=command,
            output_type=output_type,
            input_message_id=input_message_id,
            success=True,
        )
        message = self.message_store.add_message(
            session_id=session_id,
            role="assistant",
            content=data,
            command_name=command_name,
            run_id=done_run.run_id,
            output_type=output_type,
            parent_message_id=input_message_id or None,
            metadata=command_metadata,
            speaker_type="capability",
            speaker_id=command.capability_id,
            speaker_name=command_metadata.get("capability_name") or command_name,
            origin="command_result",
        )
        self.event_bus.emit("run_done", session_id=session_id, run_id=done_run.run_id)
        self.event_bus.emit(
            "message_done",
            session_id=session_id,
            run_id=done_run.run_id,
            message_id=message.message_id,
        )
        return CommandResult(success=True, run_id=done_run.run_id, data=data, output_type=output_type)

    def _command_result_metadata(self, command_name: str, command, output_type: str, input_message_id: str, success: bool) -> dict:
        capability_name = command.capability_id
        if self.capability_registry is not None:
            try:
                capability_name = self.capability_registry.get(command.capability_id).name or command.capability_id
            except KeyError:
                capability_name = command.capability_id
        return {
            "success": success,
            "kind": "command_result",
            "producer": "capability",
            "command": command_name,
            "capability_id": command.capability_id,
            "capability_name": capability_name,
            "output_type": output_type,
            "source_user_message_id": input_message_id or None,
            "parent_message_id": input_message_id or None,
        }

    def _command_context(self, session_id: str, input_message_id: str, capability_id: str) -> dict:
        attachments = []
        if input_message_id:
            try:
                message = self.message_store.get_message(input_message_id)
                attachments = list((message.metadata or {}).get("attachments") or [])
            except KeyError:
                attachments = []
        capability_config = {}
        if self.capability_config_store is not None and self.capability_registry is not None:
            try:
                capability = self.capability_registry.get(capability_id)
                stored = self.capability_config_store.get_config(capability_id)
                capability_config = resolve_config(capability.config_schema, stored.get("user_config") or {})
            except Exception:
                capability_config = {}
        return {
            "session_id": session_id,
            "input_message_id": input_message_id or "",
            "attachments": attachments,
            "capability_id": capability_id,
            "capability_config": capability_config,
        }

    def _call_method(self, method, args: str, context: dict):
        parameters = inspect.signature(method).parameters
        if len(parameters) >= 2:
            return method(args, context)
        return method(args)

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
        elif output_type == "file_content":
            FileContentPayload.model_validate(data)
