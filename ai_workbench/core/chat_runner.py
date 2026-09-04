"""The single ordinary-chat execution path."""

from __future__ import annotations

import asyncio
from typing import Any

from ai_workbench.core.chat_targets import ChatTargetCatalog
from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.knowledge_context import append_knowledge_to_system, build_session_knowledge_context
from ai_workbench.core.llm_config import LLMConfigError, public_llm_config_status, require_llm_model, resolve_llm_config
from ai_workbench.core.llm_service import LLMService
from ai_workbench.core.memory_context import append_system_context, build_core_memory_context
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.result import RunResult
from ai_workbench.core.schema.run import RunStatus, RunStepStatus
from ai_workbench.core.settings import DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION
from ai_workbench.core.worldbook_context import build_session_worldbook_context


class ChatRunner:
    target_id = "chat"

    def __init__(
        self,
        *,
        sessions: Any,
        messages: Any,
        runs: Any,
        events: Any,
        llm: Any = None,
        llm_profiles: Any = None,
        provider_profiles: Any = None,
        llm_defaults: Any = None,
        app_settings: Any = None,
        utility_llm: Any = None,
        knowledge: Any = None,
        knowledge_model_backend: Any = None,
        worldbooks: Any = None,
        active_runs: Any = None,
        target_catalog: ChatTargetCatalog | None = None,
    ) -> None:
        self.sessions = sessions
        self.messages = messages
        self.runs = runs
        self.events = events
        self.llm = llm if isinstance(llm, LLMService) else LLMService(llm)
        self.llm_profiles = llm_profiles
        self.provider_profiles = provider_profiles
        self.llm_defaults = llm_defaults
        self.app_settings = app_settings
        self.utility_llm = utility_llm
        self.knowledge = knowledge
        self.knowledge_model_backend = knowledge_model_backend
        self.worldbooks = worldbooks
        self.active_runs = active_runs
        self.targets = target_catalog or ChatTargetCatalog()
        self.context_builder = ContextBuilder(messages)

    async def run(
        self,
        *,
        session_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        input_message_id: str | None = None,
        client_message_id: str | None = None,
        run_id: str | None = None,
        resume: bool = False,
    ) -> RunResult:
        session = self.sessions.get_session(session_id)
        raw_text = str(text)
        attachments = list(attachments or [])

        if run_id:
            run = self.runs.get_run(run_id)
            if run.session_id != session_id:
                return RunResult(success=False, run_id=run_id, error="Run belongs to another session.", error_code="RUN_SESSION_MISMATCH")
            if run.status in {RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.DONE, RunStatus.INTERRUPTED}:
                return RunResult(success=False, run_id=run_id, error="Run is no longer resumable.", error_code="RUN_NOT_RESUMABLE")
            if input_message_id:
                user = self.messages.get_message(input_message_id)
            else:
                user = self.messages.add_message(
                    session_id=session_id,
                    role="user",
                    content=raw_text,
                    metadata={
                        "attachments": attachments,
                        "client_message_id": client_message_id or None,
                        "input_source": "chat_resume",
                    },
                    run_id=run_id,
                )
                metadata = dict(run.metadata or {})
                metadata["resume_message_id"] = user.message_id
                self.runs.update_metadata(run_id, metadata)
        else:
            if input_message_id:
                user = self.messages.get_message(input_message_id)
            else:
                user = self.messages.add_message(
                    session_id=session_id,
                    role="user",
                    content=raw_text,
                    metadata={
                        "attachments": attachments,
                        "client_message_id": client_message_id or None,
                        "input_source": "chat",
                    },
                )
            run = self.runs.create_run(
                kind="resume" if resume else "chat",
                target=self.target_id,
                session_id=session_id,
                metadata={"input_message_id": user.message_id, "input_text": raw_text},
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
        try:
            context_step = self.runs.create_step(
                run.run_id,
                kind="context",
                label="Building context",
                status=RunStepStatus.RUNNING,
            )
            active_step_id = context_step.step_id
            context, context_meta = self._build_context(
                session,
                raw_text,
                (run.metadata or {}).get("input_message_id"),
                attachments,
            )
            self.runs.update_step(
                context_step.step_id,
                status=RunStepStatus.COMPLETED,
                metadata=context_meta,
            )
            self._emit_step(run.run_id, context_step.step_id)
            active_step_id = None
            if self._cancelled(run.run_id):
                return self._cancel_result(run.run_id, session_id)

            model_step = self.runs.create_step(
                run.run_id,
                kind="model",
                label="Generating response",
                status=RunStepStatus.RUNNING,
            )
            active_step_id = model_step.step_id
            config = resolve_llm_config(
                session_llm_profile_id=session.llm_profile_id,
                llm_profile_store=self.llm_profiles,
                provider_profile_store=self.provider_profiles,
                llm_defaults_store=self.llm_defaults,
            )
            require_llm_model(config)
            self.runs.update_metadata(
                run.run_id,
                {**(self.runs.get_run(run.run_id).metadata or {}), "llm_resolution": public_llm_config_status(config)},
            )
            output = ""
            streamed = False
            if config.values.get("supports_streaming", True) and callable(getattr(self.llm.runtime, "chat_stream", None)):
                streamed = True
                async for delta in self.llm.chat_stream(context, config.values):
                    if self._cancelled(run.run_id):
                        return self._cancel_result(run.run_id, session_id)
                    value = str(delta or "")
                    output += value
                    self.events.emit(
                        "message_delta",
                        session_id=session_id,
                        run_id=run.run_id,
                        payload={"delta": value, "text": output},
                    )
            else:
                output = await self.llm.chat(context, config.values)
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
                run_id=run.run_id,
                parent_message_id=(self.runs.get_run(run.run_id).metadata or {}).get("input_message_id"),
                metadata={
                    "target": self.target_id,
                    "llm_resolution": public_llm_config_status(config),
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
            await self._maybe_title(session_id, raw_text)
            return RunResult(success=True, run_id=run.run_id, data=output)
        except LLMConfigError as exc:
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

    async def resume_run(
        self,
        *,
        session_id: str,
        run_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> RunResult:
        self.sessions.set_waiting_run(session_id, None)
        return await self.run(
            session_id=session_id,
            text=text,
            attachments=attachments,
            run_id=run_id,
            resume=True,
        )

    def _build_context(
        self,
        session: Any,
        text: str,
        current_message_id: str | None,
        attachments: list[dict[str, Any]],
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        target = self.targets.get(self.target_id)
        policy = target.context_policy or ContextPolicy(mode="session")
        current_text = _with_current_attachments(text, attachments)
        result = self.context_builder.build(
            session.session_id,
            current_text,
            policy,
            current_message_id=current_message_id,
            context_mode=session.context_mode,
        )
        messages = list(result.messages)
        metadata: dict[str, Any] = {
            "context_mode": session.context_mode,
            "message_count": len(messages),
            "warnings": result.warnings,
            "target": target.id,
        }
        if target.system_prompt:
            messages.insert(0, {"role": "system", "content": target.system_prompt})
        if session.context_mode == "group_transcript" and self.app_settings is not None:
            custom = self.app_settings.get().group_transcript_system_instruction
            if custom:
                messages.insert(0, {"role": "system", "content": custom})
        memory = build_core_memory_context(app_settings_store=self.app_settings, source="chat")
        messages = append_system_context(messages, memory.rendered_text)
        metadata["memory"] = memory.metadata
        if self.worldbooks is not None:
            worldbook = build_session_worldbook_context(
                worldbook_store=self.worldbooks,
                session_id=session.session_id,
                user_text=text,
                source="chat",
            )
            messages = append_system_context(messages, worldbook.rendered_text)
            metadata["worldbook"] = worldbook.metadata
        if self.knowledge is not None:
            knowledge = build_session_knowledge_context(
                knowledge_store=self.knowledge,
                model_backend=self.knowledge_model_backend,
                query=text,
                session_id=session.session_id,
                source="chat",
                provider_profile_store=self.provider_profiles,
            )
            messages = append_knowledge_to_system(messages, knowledge.rendered_text)
            metadata["knowledge"] = knowledge.metadata
        return messages, metadata

    async def _maybe_title(self, session_id: str, text: str) -> None:
        settings = self.app_settings.get() if self.app_settings is not None else None
        if not settings or not settings.auto_generate_session_titles or self.utility_llm is None:
            return
        try:
            session = self.sessions.get_session(session_id)
            if session.title and session.title not in {"New session", "新会话"}:
                return
            title = await self.utility_llm.generate_title(text)
            if title:
                self.sessions.set_generated_title(session_id, title, {"source": "utility"})
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
        self.runs.update_status(
            run_id,
            RunStatus.CANCELLED,
            current_step="cancelled",
            error="Run was cancelled.",
            error_code="RUN_CANCELLED",
            cancel_requested=True,
        )
        self.events.emit("run_cancelled", session_id=session_id, run_id=run_id)
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


def _with_current_attachments(text: str, attachments: list[dict[str, Any]]) -> str:
    blocks = [str(text)] if text else []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        label = str(attachment.get("name") or attachment.get("id") or "file")
        context_text = attachment.get("context_text") or attachment.get("text")
        if context_text:
            blocks.append(f"[Attachment: {label}]\n{context_text}")
        else:
            kind = str(attachment.get("type") or "file")
            blocks.append(f"[{kind} attachment: {label}]")
    return "\n\n".join(blocks)
