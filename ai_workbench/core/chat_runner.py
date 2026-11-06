"""The single ordinary-chat execution path."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable
from uuid import uuid4
from contextlib import AsyncExitStack, aclosing
from datetime import date

from ai_workbench.core.assistant_output import AssistantDraft
from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.harness.agent_loop import ACTIVE_BUDGET_SECONDS, HarnessAgentLoop, request_tools
from ai_workbench.core.context import ContextBuilder, add_chat_instructions
from ai_workbench.core.context_compaction import ContextCompactionService
from ai_workbench.core.history_retrieval import HistoryRetrieval
from ai_workbench.core.retrieval_tools import RetrievalTools
from ai_workbench.core.qq_context import QQContextHistory, build_qq_context, runtime_prompt
from ai_workbench.core.models.context_budget import ChatContextBudget
from ai_workbench.core.context_snapshot import append_system_block, capture_context, omit_context_images, snapshot_attachment
from ai_workbench.core.schema.context_snapshot import ContextExclusion, ContextSource, ContextTrace
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.chat_support import chat_reasoning_mode, local_chat_support
from ai_workbench.core.models.images import has_context_images, resolve_context_images
from ai_workbench.core.models.schema import ChatRequest, ProviderSource
from ai_workbench.core.models.llm_metrics import LLMCallMetrics
from ai_workbench.core.attachments import read_attachment_text, is_text_attachment
from ai_workbench.core.schema.chat_config import ResolvedChatConfig
from ai_workbench.core.schema.result import RunResult
from ai_workbench.core.schema.run import RunStatus, RunStepStatus
from ai_workbench.core.instructions import UiLanguage, date_instruction
from ai_workbench.core.time import utc_now
from ai_workbench.core.web_tools import WEB_TOOL_NAMES
from ai_workbench.core.durable_memory import DurableMemory, MEMORY_INSTRUCTION
from ai_workbench.core.schema.memory import MEMORY_TOOL_NAMES
from ai_workbench.core.harness.schema import ToolExecutionError


class ChatRunner:
    def __init__(
        self,
        *,
        sessions: Any,
        messages: Any,
        runs: Any,
        events: Any,
        model_manager: Any,
        chat_service: Any,
        app_settings: Any = None,
        utility_llm: Any = None,
        active_runs: Any = None,
        tool_registry: Any = None,
        qq_store: Any = None,
        web_tools: Any = None,
    ) -> None:
        self.sessions = sessions
        self.messages = messages
        self.runs = runs
        self.events = events
        self.model_manager = model_manager
        self.app_settings = app_settings
        self.utility_llm = utility_llm
        self.active_runs = active_runs
        self.chat_service = chat_service
        self.qq_store = qq_store
        self.durable_memory = DurableMemory(chat_service.memory, runs, model_manager)
        self.harness_loop = HarnessAgentLoop(
            sessions=sessions, messages=messages, runs=runs, events=events, model_manager=model_manager,
            registry=tool_registry, active_runs=active_runs, web_tools=web_tools,
            allowed_tools=chat_service.tools_for_run,
            durable_memory=self.durable_memory,
        ) if tool_registry is not None else None
        self.retrieval = HistoryRetrieval(sessions, messages, runs, events, model_manager)
        if tool_registry is not None:
            self.durable_memory.register(tool_registry)
            RetrievalTools(sessions, messages, runs, qq_store, self.retrieval).register(tool_registry)
            self.harness_loop.retrieval = self.retrieval
        self.context_builder = ContextBuilder(messages)
        self.compaction = ContextCompactionService(sessions=sessions, messages=messages, runs=runs,
            events=events, model_manager=model_manager)

    async def run(
        self,
        *,
        session_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        input_message_id: str | None = None,
        client_message_id: str | None = None,
        persona_id: str | None = None,
        on_run_created: Callable[[str], None] | None = None,
        on_context_ready: Callable[[ContextTrace], None] | None = None,
        on_dispatch: Callable[[], None] | None = None,
        resolved_config: ResolvedChatConfig | None = None,
        ui_language: UiLanguage = "en",
    ) -> RunResult:
        session = self.sessions.get_session(session_id)
        raw_text = str(text)
        attachments = list(attachments or [])
        if input_message_id:
            existing = self.messages.get_message(input_message_id)
            if existing.session_id != session_id or existing.role != "user":
                raise ChatError("MESSAGE_SESSION_MISMATCH", "Input must be a user message from this session.")

        config, user, run = self.chat_service.acceptance.accept(session_id, text=raw_text, attachments=attachments,
            input_message_id=input_message_id, client_message_id=client_message_id,
            persona_id=persona_id, resolved_config=resolved_config)
        memory_work = self.durable_memory.start(run, config)
        if on_run_created:
            on_run_created(run.run_id)
        self.set_input_title(session_id, raw_text, attachments, user.message_id)

        self.runs.update_status(run.run_id, RunStatus.RUNNING, current_step="context")
        self.events.emit(
            "run_started",
            session_id=session_id,
            run_id=run.run_id,
            payload={"run": self.runs.get_run(run.run_id).model_dump(mode="json")},
        )
        current_task = asyncio.current_task()
        if current_task is not None and self.active_runs is not None:
            self.active_runs.register(run.run_id, current_task)
        active_step_id: str | None = None
        draft: AssistantDraft | None = None
        checks = AsyncExitStack()
        first_metrics = LLMCallMetrics()
        self._input_warnings(user, run.run_id, [])
        context_started = time.monotonic()
        try:
            context_step = self.runs.create_step(
                run.run_id,
                kind="context",
                label="Building context",
                status=RunStepStatus.RUNNING,
            )
            active_step_id = context_step.step_id
            build_context = self._build_context(
                session,
                config,
                raw_text,
                user.message_id,
                attachments,
            )
            if config.harness_enabled and config.tools_allowed:
                try:
                    context, context_meta, context_trace = await asyncio.wait_for(build_context, timeout=ACTIVE_BUDGET_SECONDS)
                except asyncio.TimeoutError as exc:
                    raise ModelError("TOOL_RUN_TIMEOUT", "Harness execution exceeded 5 minutes.", 408) from exc
            else:
                context, context_meta, context_trace = await build_context
            if not config.model_profile_id:
                raise ModelError("MODEL_NOT_CONFIGURED", "Select a model for this session.", 503)
            profile = self.model_manager.profile(config.model_profile_id, "llm")
            if session.kind == "qqbot" and (not profile.source or profile.source.type != "provider"):
                raise ModelError("QQ_EXTERNAL_MODEL_REQUIRED", "QQBot requires an external LLM profile.", 422)
            if config.context_policy.strategy == "history_retrieval" and not config.harness_enabled:
                raise ModelError("HISTORY_RETRIEVAL_REQUIRES_HARNESS", "Enable Harness to use on-demand history.", 422)
            use_harness = bool(config.harness_enabled and self.chat_service.tools_for_run(config) and self.harness_loop)
            has_images = has_context_images(context)
            current = context[-1]["content"]
            current_text = current if isinstance(current, str) else "\n".join(
                part["text"] for part in current if part["type"] == "text")
            rejected_image = (has_images and not current_text.strip() and not profile.request_options.skip_vision_capability_check
                              and local_chat_support(profile).vision.state == "unsupported")
            first_metrics.start()
            preflight = checks.enter_async_context(self.model_manager.check_chat_inputs(
                profile, tools=use_harness, vision=has_images or (session.kind != "qqbot" and config.context_policy.history_enabled
                    and config.context_policy.include_attachments == "explicit"),
                reasoning=None if rejected_image else config.reasoning, metrics=first_metrics))
            if use_harness:
                try:
                    support = await asyncio.wait_for(preflight, timeout=ACTIVE_BUDGET_SECONDS - (time.monotonic() - context_started))
                except asyncio.TimeoutError as exc:
                    raise ModelError("TOOL_RUN_TIMEOUT", "Harness execution exceeded 5 minutes.", 408) from exc
            else:
                support = await preflight
            warnings = []
            reasoning = chat_reasoning_mode(profile, support, config.reasoning)
            if reasoning != config.reasoning:
                warnings.append("reasoning_enabled" if reasoning else "reasoning_disabled")
            image_only = False
            if has_images and not profile.request_options.skip_vision_capability_check and support.vision.state == "unsupported":
                image_only = not current_text.strip()
                context = omit_context_images(context, context_trace)
                warnings.append("images_require_text" if image_only else "images_ignored")
            if use_harness and not profile.request_options.skip_tool_capability_check and support.tools.state == "unsupported":
                if session.kind == "qqbot" or config.context_policy.strategy == "history_retrieval":
                    raise ModelError("UNSUPPORTED_CAPABILITY", "This context strategy requires model tool support.", 422)
                use_harness = False
                warnings.append("tools_ignored")
            self._input_warnings(user, run.run_id, warnings)
            self.runs.update_metadata(run.run_id, {**self.runs.get_run(run.run_id).metadata, "harness": use_harness,
                "reasoning": {"requested": config.reasoning, "effective": reasoning}})
            if image_only:
                raise ModelError("UNSUPPORTED_CAPABILITY", "This model cannot read images. Add text or select another model.", 422)
            web_date = utc_now().astimezone().date().isoformat()
            allowed = self.chat_service.tools_for_run(config) if use_harness else []
            qq = session.kind == "qqbot"
            if qq and user.metadata["qq_trigger_kind"] not in {"followup", "icebreaker"}:
                allowed = [name for name in allowed if name != "qq_skip_reply"]
            tools = request_tools(self.harness_loop.registry, allowed, qq=qq) if use_harness else None
            if MEMORY_TOOL_NAMES.intersection(allowed):
                context, memory_source = append_system_block(context, context_trace, MEMORY_INSTRUCTION, "instruction")
                memory_source.id = "memory-instruction"
            instruction = date_instruction(ui_language, date.fromisoformat(web_date)) if WEB_TOOL_NAMES.intersection(allowed) else ""
            max_image_bytes = self.app_settings.get().max_image_size_mb * 1024 * 1024
            context_service = self.retrieval if config.context_policy.strategy == "history_retrieval" else self.compaction
            prepare = context_service.prepare(session=session, config=config, run=run, base=context,
                trace=context_trace, current=user, profile=profile, support=support, tools=tools,
                instruction=instruction, runtime_instruction=runtime_prompt(config, user.metadata["qq_batch_id"], 0,
                    user.metadata["qq_trigger_kind"]) if qq else "", max_image_bytes=max_image_bytes,
                history=QQContextHistory(self.qq_store, self.messages, session_id, config.context_policy, user,
                    max_image_bytes) if qq else None, reasoning=reasoning, on_dispatch=on_dispatch)
            try:
                context, context_trace, warning = (await asyncio.wait_for(prepare,
                    timeout=max(0, ACTIVE_BUDGET_SECONDS - (time.monotonic() - context_started))) if use_harness else await prepare)
            except asyncio.TimeoutError as exc:
                raise ModelError("TOOL_RUN_TIMEOUT", "Harness execution exceeded 5 minutes.", 408) from exc
            if warning:
                warnings.append(warning)
            if memory_work is not None:
                window = config.context_limits.window_tokens or 0
                margin = 32 if profile.source.type == "local" else max(128, (window + 9) // 10)
                capacity = max(0, window - (config.context_limits.output_tokens or 0) - margin)
                context, context_trace = self.durable_memory.recall(context, context_trace, memory_work, raw_text, capacity)
            if any(item.reason == "images_unsupported" for item in context_trace.exclusions) and "images_ignored" not in warnings:
                warnings.append("images_ignored")
            if warnings:
                self._input_warnings(user, run.run_id, warnings)
            context_meta["message_count"] = len(context)
            first_metrics.start()
            self.runs.update_step(
                context_step.step_id,
                status=RunStepStatus.COMPLETED,
                metadata=context_meta,
            )
            self._emit_step(run.run_id, context_step.step_id)
            active_step_id = None
            if self._cancelled(run.run_id):
                return self._cancel_result(run.run_id, session_id)

            if on_context_ready is not None:
                on_context_ready(context_trace)

            if use_harness:
                result = await self.harness_loop.run(session=session, config=config, run=run, user=user, context=context, trace=context_trace,
                                                     reasoning=reasoning, ui_language=ui_language,
                                                     max_image_bytes=self.app_settings.get().max_image_size_mb * 1024 * 1024,
                                                     active_seconds=time.monotonic() - context_started, first_metrics=first_metrics,
                                                     web_date=web_date, summary_reasoning=chat_reasoning_mode(profile, support, False),
                                                     memory_work=memory_work,
                                                     on_dispatch=on_dispatch)
                if result.success and self.runs.get_run(run.run_id).status == RunStatus.DONE:
                    await self.maybe_title(session_id, raw_text, user.message_id)
                return result

            model_step = self.runs.create_step(
                run.run_id,
                kind="model",
                label="Generating response",
                status=RunStepStatus.RUNNING,
            )
            active_step_id = model_step.step_id
            if not config.model_profile_id:
                raise ModelError("MODEL_NOT_CONFIGURED", "Select a model for this session.", 503)
            profile = self.model_manager.profile(config.model_profile_id, "llm")
            resolution = {"model_profile_id": profile.id, "alias": profile.alias,
                          "source_type": profile.source.type if profile.source else None,
                          "provider_profile_id": profile.source.provider_profile_id if profile.source and profile.source.type == "provider" else None, "model_ref": profile.model_ref}
            self.runs.update_metadata(run.run_id, {**self.runs.get_run(run.run_id).metadata, "model_resolution": resolution})
            streamed = profile.request_options.streaming
            messages = await resolve_context_images(context,
                max_image_bytes=self.app_settings.get().max_image_size_mb * 1024 * 1024)
            request = ChatRequest(model=profile.alias, messages=messages, stream=streamed, reasoning=reasoning,
                                  **config.generation.model_dump(exclude_none=True))
            self.model_manager.validate_chat(profile, request)
            draft = AssistantDraft(messages=self.messages, events=self.events, session_id=session_id,
                                   run_id=run.run_id, message_id=str(uuid4()), config=config,
                                   parent_message_id=user.message_id, streamed=streamed,
                                   parse_think_tags=isinstance(profile.source, ProviderSource))
            metrics = first_metrics
            budget = ChatContextBudget(config.context_limits, context_trace,
                allow_pruning=config.context_policy.strategy == "message_window" or not config.context_policy.compaction.enabled)
            save_capture = capture_context(self.runs, model_step.step_id, budget.trace, profile, config.context_policy, budget=budget)
            def capture(payload):
                self.durable_memory.check(memory_work)
                save_capture(payload)
            try:
                if streamed:
                    async with aclosing(self.model_manager.chat_stream(profile.id, request, metrics=metrics, capture=capture, budget=budget)) as stream:
                        async for chunk in stream:
                            if self._cancelled(run.run_id):
                                raise asyncio.CancelledError()
                            draft.append(chunk.delta.content, chunk.delta.reasoning_content)
                            if chunk.finish_reason:
                                draft.finish()
                            if chunk.finish_reason == "content_filter":
                                raise ModelError("MODEL_REFUSAL", "Provider refused this request.", 422)
                            if chunk.delta.tool_calls:
                                raise ModelError("UNEXPECTED_TOOL_CALL", "Ordinary chat cannot execute tool calls.", 502)
                else:
                    response = await self.model_manager.chat(profile.id, request, metrics=metrics, capture=capture, budget=budget)
                    if response.message.content is not None and not isinstance(response.message.content, str):
                        raise ModelError("UNEXPECTED_TOOL_CALL", "Ordinary chat requires a text response.", 502)
                    draft.append(response.message.content, response.message.reasoning_content)
                    if response.finish_reason == "content_filter":
                        raise ModelError("MODEL_REFUSAL", "Provider refused this request.", 422)
                    if response.message.tool_calls:
                        raise ModelError("UNEXPECTED_TOOL_CALL", "Ordinary chat requires a text response.", 502)
            finally:
                self.runs.update_step(model_step.step_id, metadata={"llm": metrics.snapshot(
                    profile.id, profile.alias, draft.message.message_id).model_dump(mode="json")})
                self._emit_step(run.run_id, model_step.step_id)
            if self._cancelled(run.run_id):
                raise asyncio.CancelledError()
            self.runs.update_step(
                model_step.step_id,
                status=RunStepStatus.COMPLETED,
                message="Response generated",
                metadata={"streamed": streamed},
            )
            self._emit_step(run.run_id, model_step.step_id)
            active_step_id = None

            save_step = self.runs.create_step(
                run.run_id,
                kind="save",
                label="Saving response",
                status=RunStepStatus.RUNNING,
            )
            active_step_id = save_step.step_id
            draft.persist(metadata={"model_resolution": resolution})
            self.runs.update_step(save_step.step_id, status=RunStepStatus.COMPLETED, message="Response saved")
            self._emit_step(run.run_id, save_step.step_id)
            active_step_id = None
            self.runs.update_status(run.run_id, RunStatus.DONE, current_step="done")
            final_run = self.runs.get_run(run.run_id)
            self.events.emit(
                "run_completed",
                session_id=session_id,
                run_id=run.run_id,
                payload={"run": final_run.model_dump(mode="json")},
            )
            await self.maybe_title(session_id, raw_text, user.message_id)
            return RunResult(success=True, run_id=run.run_id, data=draft.text)
        except (ModelError, ChatError, ToolExecutionError) as exc:
            if draft is not None:
                draft.persist(incomplete=True)
            self._fail_step(active_step_id, exc.code, exc.message)
            return self._fail(run.run_id, session_id, exc.code, exc.message)
        except asyncio.CancelledError:
            requested = self._cancelled(run.run_id)
            if draft is not None:
                draft.persist(incomplete=True)
            self._fail_step(active_step_id, "RUN_CANCELLED", "Run was cancelled.")
            result = self._cancel_result(run.run_id, session_id)
            if requested:
                return result
            raise
        except Exception as exc:
            if draft is not None:
                draft.persist(incomplete=True)
            message = str(exc) or "Chat generation failed."
            self._fail_step(active_step_id, "LLM_GENERATION_FAILED", message)
            return self._fail(run.run_id, session_id, "LLM_GENERATION_FAILED", message)
        finally:
            try:
                await checks.aclose()
            finally:
                if self.active_runs is not None:
                    self.active_runs.unregister(run.run_id)

    def _input_warnings(self, user, run_id: str, codes: list[str]) -> None:
        if not codes and "request_warnings" not in user.metadata:
            return
        user.metadata = {key: value for key, value in user.metadata.items() if key != "request_warnings"}
        if codes:
            user.metadata["request_warnings"] = {"run_id": run_id, "codes": codes}
        self.messages.update_message(user)
        self.events.emit("message_updated", session_id=user.session_id, run_id=run_id, message_id=user.message_id,
                         payload={"message": user.model_dump(mode="json")})

    async def _build_context(
        self,
        session: Any,
        config: ResolvedChatConfig,
        text: str,
        current_message_id: str | None,
        attachments: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], ContextTrace]:
        policy = config.context_policy
        if policy.include_attachments == "none":
            attachments = []
        attachment_trace = ContextTrace()
        current_text = _with_current_attachments(text, attachments, self.app_settings.get(), attachment_trace)
        result = (build_qq_context(self.qq_store, self.messages, session.session_id, current_text, policy, current_message_id,
                      max_image_bytes=self.app_settings.get().max_image_size_mb * 1024 * 1024)
                  if session.kind == "qqbot" else self.context_builder.build(
                      session.session_id, current_text, policy, current_message_id=current_message_id))
        messages = list(result.messages)
        trace = result.trace
        current_index = len(messages) - 1
        for source in attachment_trace.sources:
            source.message_index = current_index
            source.parent_id = "message:" + current_message_id
        trace.sources.extend(attachment_trace.sources)
        trace.exclusions.extend(attachment_trace.exclusions)
        metadata: dict[str, Any] = {
            "message_count": len(messages),
            "warnings": result.warnings,
            "character_id": config.character_id, "persona_id": config.persona_id,
        }
        messages, metadata["user_persona"] = add_chat_instructions(config, messages, trace)
        return messages, metadata, trace

    def set_input_title(self, session_id: str, text: str, attachments: list[dict[str, Any]],
                        input_id: str, *, auxiliary: bool = True) -> None:
        session = self.sessions.get_session(session_id)
        if session.title_generation_state != "pending" or session.title_generation_metadata or (
            session.title.strip() and session.title not in {"New session", "新会话"}
        ):
            return
        source = text if text.strip() else (attachments[0].get("name", "") if attachments else "")
        excerpt = " ".join(str(source).split())
        title = excerpt[:15] + ("…" if len(excerpt) > 15 else "")
        settings = self.app_settings.get() if self.app_settings is not None else None
        eligible = auxiliary and bool(text.strip()) and settings and settings.auto_generate_session_titles
        updated = self.sessions.update_session(session_id, {
            "title": title,
            "title_generation_state": "pending" if eligible else "skipped",
            "title_generation_metadata": {"source": "input_excerpt", "input_id": input_id},
        })
        self.events.emit("session_updated", session_id=session_id, payload={"session": self.chat_service.session_response(updated)})

    async def maybe_title(self, session_id: str, text: str, input_id: str) -> None:
        session = self.sessions.get_session(session_id)
        if session.title_generation_state != "pending" or session.title_generation_metadata.get("input_id") != input_id:
            return
        settings = self.app_settings.get() if self.app_settings is not None else None
        title = None
        try:
            if settings and settings.auto_generate_session_titles and self.utility_llm is not None:
                title = await self.utility_llm.generate_title(text)
        except Exception:
            # Auxiliary generation failure is non-blocking; keep the input title.
            title = None
        try:
            current = self.sessions.get_session(session_id)
        except KeyError:
            # A completed conversation may be deleted while the auxiliary model runs.
            return
        if current.title != session.title or current.title_generation_state == "manual":
            return
        updated = self.sessions.set_generated_title(session_id, title, {"source": "utility"}) if title else (
            self.sessions.set_title_generation_state(session_id, "failed", session.title_generation_metadata))
        self.events.emit("session_updated", session_id=session_id, payload={"session": self.chat_service.session_response(updated)})

    def _fail_step(self, step_id: str | None, code: str, message: str) -> None:
        if not step_id:
            return
        try:
            self.runs.update_step(
                step_id,
                status=RunStepStatus.FAILED,
                error_code=code,
                error_message=message,
            )
            self._emit_step(self.runs.get_step(step_id).run_id, step_id)
        except Exception:
            return

    def _emit_step(self, run_id: str, step_id: str) -> None:
        try:
            run = self.runs.get_run(run_id)
            step = self.runs.get_step(step_id)
            self.events.emit(
                "run_step_updated",
                session_id=run.session_id,
                run_id=run_id,
                payload={"step": step.model_dump(mode="json")},
            )
        except Exception:
            return

    def _cancelled(self, run_id: str) -> bool:
        try:
            return bool(self.runs.get_run(run_id).cancel_requested)
        except Exception:
            return False

    def _cancel_result(self, run_id: str, session_id: str) -> RunResult:
        if self.runs.get_run(run_id).status in {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}:
            return RunResult(success=False, run_id=run_id, error="Run was cancelled.", error_code="RUN_CANCELLED")
        self.runs.update_status(
            run_id,
            RunStatus.CANCELLED,
            current_step="cancelled",
            error="Run was cancelled.",
            error_code="RUN_CANCELLED",
            cancel_requested=True,
        )
        self.events.emit("run_cancelled", session_id=session_id, run_id=run_id,
                         payload={"run": self.runs.get_run(run_id).model_dump(mode="json")})
        return RunResult(success=False, run_id=run_id, error="Run was cancelled.", error_code="RUN_CANCELLED")

    def _fail(self, run_id: str, session_id: str, code: str, message: str) -> RunResult:
        self.runs.update_status(
            run_id,
            RunStatus.FAILED,
            current_step="failed",
            error=message,
            error_code=code,
            error_message=message,
        )
        self.events.emit(
            "run_failed",
            session_id=session_id,
            run_id=run_id,
            payload={"error": message, "error_code": code},
        )
        return RunResult(success=False, run_id=run_id, error=message, error_code=code)


def _with_current_attachments(text: str, attachments: list[dict[str, Any]], settings: Any, trace: ContextTrace) -> str:
    blocks = [str(text)] if text else []
    used = 0
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if attachment.get("type") == "image":
            continue
        label = str(attachment.get("name") or attachment.get("id") or "file")
        context_text = ""
        if settings.send_text_file_attachments_to_llm and is_text_attachment(attachment):
            remaining = settings.max_total_file_context_per_message_bytes - used
            if remaining > 0:
                read = read_attachment_text(attachment, limit=min(settings.max_file_context_per_file_bytes, remaining))
                context_text = read["content"]
                used += len(context_text.encode("utf-8"))
                if read["truncated"]:
                    trace.exclusions.append(ContextExclusion(kind="attachment", reason="file_text_limit",
                        reference_id=attachment["id"], name=label))
            else:
                trace.exclusions.append(ContextExclusion(kind="attachment", reason="file_text_limit", reference_id=attachment["id"], name=label))
        elif is_text_attachment(attachment):
            trace.exclusions.append(ContextExclusion(kind="attachment", reason="file_text_disabled", reference_id=attachment["id"], name=label))
        start = len("\n\n".join(blocks)) + (2 if blocks else 0)
        if context_text:
            blocks.append(f"[Attachment: {label}]\n{context_text}")
        else:
            kind = str(attachment.get("type") or "file")
            blocks.append(f"[{kind} attachment: {label}]")
        trace.sources.append(ContextSource(id="attachment:" + attachment["id"], kind="attachment", start=start,
            end=start + len(blocks[-1]), attachment=snapshot_attachment(attachment)))
    return "\n\n".join(blocks)
