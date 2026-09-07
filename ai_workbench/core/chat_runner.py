"""The single ordinary-chat execution path."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4
from contextlib import aclosing

from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.harness.agent_loop import ACTIVE_BUDGET_SECONDS, HarnessAgentLoop
from ai_workbench.core.context import ContextBuilder, LLMContextError
from ai_workbench.core.knowledge_context import append_knowledge_to_system, build_session_knowledge_context
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import ChatRequest
from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.attachments import read_attachment_as_data_url, read_attachment_text, is_text_attachment
from ai_workbench.core.memory_context import append_system_context, build_core_memory_context
from ai_workbench.core.schema.persona import ResolvedChatConfig
from ai_workbench.core.schema.result import RunResult
from ai_workbench.core.schema.run import RunStatus, RunStepStatus
from ai_workbench.core.worldbook_context import build_session_worldbook_context


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
        knowledge_service: Any = None,
        worldbooks: Any = None,
        active_runs: Any = None,
        tool_registry: Any = None,
        harness_settings: Any = None,
        network_policy: Any = None,
        repo_root: Any = None,
    ) -> None:
        self.sessions = sessions
        self.messages = messages
        self.runs = runs
        self.events = events
        self.model_manager = model_manager
        self.app_settings = app_settings
        self.utility_llm = utility_llm
        self.knowledge_service = knowledge_service
        self.worldbooks = worldbooks
        self.active_runs = active_runs
        self.chat_service = chat_service
        self.harness_loop = HarnessAgentLoop(
            sessions=sessions, messages=messages, runs=runs, events=events, model_manager=model_manager,
            registry=tool_registry, network_policy=network_policy, harness_settings=harness_settings,
            repo_root=repo_root, knowledge_service=knowledge_service, active_runs=active_runs,
        ) if tool_registry is not None else None
        self.context_builder = ContextBuilder(messages)

    async def run(
        self,
        *,
        session_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        input_message_id: str | None = None,
        client_message_id: str | None = None,
        persona_id: str | None = None,
        source_message_id: str | None = None,
    ) -> RunResult:
        session = self.sessions.get_session(session_id)
        raw_text = str(text)
        attachments = list(attachments or [])
        if input_message_id:
            existing = self.messages.get_message(input_message_id)
            if existing.session_id != session_id or existing.role != "user":
                raise ChatError("MESSAGE_SESSION_MISMATCH", "Input must be a user message from this session.")

        self.chat_service.assert_idle(session_id)
        config = self.chat_service.resolve(session, persona_id=persona_id)
        if input_message_id:
            user = self.messages.get_message(input_message_id)
        else:
            user = self.messages.add_message(
                session_id=session_id, role="user", content=raw_text,
                metadata={"attachments": attachments, "client_message_id": client_message_id or None, "input_source": "chat"},
            )
        run = self.runs.create_run(
            kind="chat", persona_id=config.persona_id, session_id=session_id,
            metadata={"input_message_id": user.message_id, "context_source_message_id": source_message_id,
                      "configuration": config.public_summary(), "harness": bool(config.harness_enabled and config.tools_allowed)},
            config_snapshot=config.model_dump(mode="json"),
        )

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
                source_message_id,
            )
            if config.harness_enabled and config.tools_allowed:
                try:
                    context, context_meta = await asyncio.wait_for(build_context, timeout=ACTIVE_BUDGET_SECONDS)
                except asyncio.TimeoutError as exc:
                    raise ModelError("TOOL_RUN_TIMEOUT", "Harness execution exceeded 5 minutes.", 408) from exc
            else:
                context, context_meta = await build_context
            self.runs.update_step(
                context_step.step_id,
                status=RunStepStatus.COMPLETED,
                metadata=context_meta,
            )
            self._emit_step(run.run_id, context_step.step_id)
            active_step_id = None
            if self._cancelled(run.run_id):
                return self._cancel_result(run.run_id, session_id)

            if config.harness_enabled and config.tools_allowed and self.harness_loop is not None:
                result = await self.harness_loop.run(session=session, config=config, run=run, user=user, context=context,
                                                     active_seconds=time.monotonic() - context_started)
                if result.success and self.runs.get_run(run.run_id).status == RunStatus.DONE:
                    await self.maybe_title(session_id, raw_text)
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
                          "provider_profile_id": profile.provider_profile_id, "model_ref": profile.model_ref}
            self.runs.update_metadata(run.run_id, {**self.runs.get_run(run.run_id).metadata, "model_resolution": resolution})
            streamed = profile.capabilities.streaming
            request = ChatRequest(model=profile.alias, messages=context, stream=streamed, **config.generation.model_dump(exclude_none=True))
            self.model_manager.validate_chat(profile, request)
            message_id = str(uuid4())
            pending = MessageSchema(message_id=message_id, session_id=session_id, role="assistant",
                                    speaker_type="assistant", speaker_id=config.persona_id, speaker_name=config.persona_name,
                                    parent_message_id=user.message_id, run_id=run.run_id, parts=[],
                                    metadata={"streaming": True, "speaker_avatar_attachment_id": config.avatar_attachment_id})
            self.events.emit("message_started", session_id=session_id, run_id=run.run_id,
                             message_id=message_id, payload={"message": pending.model_dump(mode="json"), "seq": 0})
            output = ""
            if streamed:
                seq = 0
                async with aclosing(self.model_manager.chat_stream(profile.id, request)) as stream:
                    async for chunk in stream:
                        if self._cancelled(run.run_id):
                            return self._cancel_result(run.run_id, session_id)
                        if chunk.delta.tool_calls:
                            raise ModelError("UNEXPECTED_TOOL_CALL", "Ordinary chat cannot execute tool calls.", 502)
                        if chunk.delta.content:
                            output += chunk.delta.content
                            seq += 1
                            self.events.emit("message_delta", session_id=session_id, run_id=run.run_id,
                                             message_id=message_id, payload={"delta": chunk.delta.content, "seq": seq})
            else:
                response = await self.model_manager.chat(profile.id, request)
                if response.message.tool_calls or not isinstance(response.message.content, str):
                    raise ModelError("UNEXPECTED_TOOL_CALL", "Ordinary chat requires a text response.", 502)
                output = response.message.content
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
            assistant = self.messages.add_message(
                session_id=session_id,
                role="assistant",
                content=output,
                message_id=message_id,
                run_id=run.run_id,
                parent_message_id=user.message_id,
                speaker_type="assistant", speaker_id=config.persona_id, speaker_name=config.persona_name,
                metadata={
                    "speaker_avatar_attachment_id": config.avatar_attachment_id,
                    "model_resolution": resolution,
                    "streamed": streamed,
                },
            )
            self.runs.update_step(save_step.step_id, status=RunStepStatus.COMPLETED, message="Response saved")
            self._emit_step(run.run_id, save_step.step_id)
            active_step_id = None
            self.runs.update_status(run.run_id, RunStatus.DONE, current_step="done")
            final_run = self.runs.get_run(run.run_id)
            self.events.emit(
                "message_completed",
                session_id=session_id,
                run_id=run.run_id,
                message_id=assistant.message_id,
                payload={"message": assistant.model_dump(mode="json")},
            )
            self.events.emit(
                "run_completed",
                session_id=session_id,
                run_id=run.run_id,
                payload={"run": final_run.model_dump(mode="json")},
            )
            await self.maybe_title(session_id, raw_text)
            return RunResult(success=True, run_id=run.run_id, data=output)
        except (ModelError, ChatError, LLMContextError) as exc:
            self._fail_step(active_step_id, exc.code, exc.message)
            return self._fail(run.run_id, session_id, exc.code, exc.message)
        except asyncio.CancelledError:
            self._fail_step(active_step_id, "RUN_CANCELLED", "Run was cancelled.")
            self._cancel_result(run.run_id, session_id)
            raise
        except Exception as exc:
            message = str(exc) or "Chat generation failed."
            self._fail_step(active_step_id, "LLM_GENERATION_FAILED", message)
            return self._fail(run.run_id, session_id, "LLM_GENERATION_FAILED", message)
        finally:
            if self.active_runs is not None:
                self.active_runs.unregister(run.run_id)

    async def _build_context(
        self,
        session: Any,
        config: ResolvedChatConfig,
        text: str,
        current_message_id: str | None,
        attachments: list[dict[str, Any]],
        source_message_id: str | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        policy = config.context_policy
        if policy.include_attachments == "none":
            attachments = []
        current_text = _with_current_attachments(text, attachments, self.app_settings.get())
        result = self.context_builder.build(
            session.session_id,
            current_text,
            policy,
            current_message_id=current_message_id,
            source_message_id=source_message_id,
            context_mode=config.context_mode,
            group_instruction=config.group_transcript_instruction,
            persona_id=config.persona_id, persona_name=config.persona_name,
        )
        messages = list(result.messages)
        metadata: dict[str, Any] = {
            "context_mode": config.context_mode,
            "message_count": len(messages),
            "warnings": result.warnings,
            "persona_id": config.persona_id,
        }
        if config.system_prompt:
            messages.insert(0, {"role": "system", "content": config.system_prompt})
        memory = build_core_memory_context(app_settings_store=self.app_settings, source="chat")
        messages = append_system_context(messages, memory.rendered_text)
        metadata["memory"] = memory.metadata
        if self.worldbooks is not None:
            worldbook = build_session_worldbook_context(
                worldbook_store=self.worldbooks,
                session_id=session.session_id,
                worldbook_ids=config.worldbook_ids,
                user_text=text,
                source="chat",
            )
            messages = append_system_context(messages, worldbook.rendered_text)
            metadata["worldbook"] = worldbook.metadata
        if self.knowledge_service is not None:
            knowledge = await build_session_knowledge_context(
                knowledge_service=self.knowledge_service, query=text, session_id=session.session_id, source="chat",
                knowledge_base_ids=config.knowledge_base_ids,
            )
            messages = append_knowledge_to_system(messages, knowledge.rendered_text)
            metadata["knowledge"] = knowledge.metadata
        images = [item for item in attachments if item.get("type") == "image"]
        if images:
            # ContextBuilder leaves the current user message last in both modes.
            current = messages[-1]
            current["content"] = [{"type": "text", "text": current["content"]}] + [
                {"type": "image_url", "image_url": {"url": read_attachment_as_data_url(item)}} for item in images
            ]
        return messages, metadata

    async def maybe_title(self, session_id: str, text: str) -> None:
        settings = self.app_settings.get() if self.app_settings is not None else None
        if not settings or not settings.auto_generate_session_titles or self.utility_llm is None:
            return
        try:
            session = self.sessions.get_session(session_id)
            if session.title and session.title not in {"New session", "新会话"}:
                return
            title = await self.utility_llm.generate_title(text)
            if title:
                current = self.sessions.get_session(session_id)
                if current.title != session.title or current.title_generation_state == "manual":
                    return
                updated = self.sessions.set_generated_title(session_id, title, {"source": "utility"})
                self.events.emit("session_updated", session_id=session_id, payload={"session": self.chat_service.session_response(updated)})
        except Exception:
            return

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


def _with_current_attachments(text: str, attachments: list[dict[str, Any]], settings: Any) -> str:
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
                context_text = read_attachment_text(attachment, limit=min(settings.max_file_context_per_file_bytes, remaining))["content"]
                used += len(context_text.encode("utf-8"))
        if context_text:
            blocks.append(f"[Attachment: {label}]\n{context_text}")
        else:
            kind = str(attachment.get("type") or "file")
            blocks.append(f"[{kind} attachment: {label}]")
    return "\n\n".join(blocks)
