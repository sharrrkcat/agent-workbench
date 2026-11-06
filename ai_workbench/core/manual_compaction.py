"""Independent, cancellable compaction runs for idle conversations."""
import asyncio
import logging

from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.context import add_chat_instructions
from ai_workbench.core.context_compaction import message_key
from ai_workbench.core.harness.agent_loop import request_tools
from ai_workbench.core.instructions import date_instruction
from ai_workbench.core.models.chat_support import chat_reasoning_mode
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.run_lifecycle import RunLifecycle
from ai_workbench.core.schema.compaction import CompactionOutcome
from ai_workbench.core.schema.context_snapshot import ContextTrace
from ai_workbench.core.schema.run import RunStepStatus
from ai_workbench.core.time import utc_now
from ai_workbench.core.web_tools import WEB_TOOL_NAMES

logger = logging.getLogger(__name__)


def is_compaction_command(text, attachments):
    if text.strip().split(maxsplit=1)[:1] != ["/compact"]:
        return False
    if text.strip() != "/compact" or attachments:
        raise ChatError("INVALID_COMPACTION_COMMAND", "/compact does not accept arguments or attachments.", 422)
    return True


class ManualCompactionRunner:
    def __init__(self, chat, active_runs):
        self.chat, self.active_runs = chat, active_runs
        self.lifecycle = RunLifecycle(chat.runs, chat.events)

    def start(self, session, *, ui_language="en"):
        if session.kind != "normal":
            raise ChatError("COMPACTION_UNAVAILABLE", "This conversation does not support manual compaction.", 409)
        self.chat.chat_service.assert_idle(session.session_id)
        config = self.chat.chat_service.resolve(session)
        if not config.context_policy.history_enabled or config.context_policy.strategy not in {"token_budget", "history_retrieval"}:
            raise ChatError("COMPACTION_UNAVAILABLE", "Enable history and select the token-budget strategy first.", 409)
        if config.context_policy.strategy == "history_retrieval" and not config.harness_enabled:
            raise ChatError("HISTORY_RETRIEVAL_REQUIRES_HARNESS", "Enable Harness to use on-demand history.", 422)
        if not config.model_profile_id:
            raise ChatError("MODEL_NOT_CONFIGURED", "Select a model for this session.", 503)
        profile = self.chat.model_manager.profile(config.model_profile_id, "llm")
        latest = next(iter(self.chat.messages.iter_context_history(session.session_id, None)), None)
        through = message_key(latest) if latest else None
        run = self.chat.runs.create_run(kind="compaction", character_id=config.character_id, persona_id=config.persona_id, session_id=session.session_id,
            metadata={"configuration": config.public_summary()}, config_snapshot=config.model_dump(mode="json"))
        task = asyncio.create_task(self._execute(session, config, profile, run, through, ui_language))
        self.active_runs.register(run.run_id, task)
        task.add_done_callback(lambda completed: self._finished(run, completed))
        self.chat.events.emit("run_started", session_id=session.session_id, run_id=run.run_id,
            payload={"run": run.model_dump(mode="json")})
        return run

    async def _execute(self, session, config, profile, run, through, ui_language):
        self.lifecycle.start_run(run.run_id, "compaction")
        if through is None and config.context_policy.strategy != "history_retrieval":
            self.chat.compaction.record_outcome(run, CompactionOutcome(status="not_needed", reason="no_history"))
            self.lifecycle.complete_run(run.run_id)
            return
        step = self.lifecycle.start_step(run.run_id, "context", "Evaluating context")
        try:
            trace = ContextTrace()
            base, _ = add_chat_instructions(config, [], trace)
            allowed = self.chat.chat_service.tools_for_run(config) if config.harness_enabled and self.chat.harness_loop else []
            async with self.chat.model_manager.check_chat_inputs(profile, tools=bool(allowed),
                    vision=config.context_policy.include_attachments == "explicit", reasoning=config.reasoning) as support:
                if not profile.request_options.skip_tool_capability_check and support.tools.state == "unsupported":
                    if config.context_policy.strategy == "history_retrieval":
                        raise ModelError("UNSUPPORTED_CAPABILITY", "On-demand history requires model tool support.", 422)
                    allowed = []
                tools = request_tools(self.chat.harness_loop.registry, allowed) if allowed else None
                instruction = date_instruction(ui_language, utc_now().astimezone().date()) if WEB_TOOL_NAMES.intersection(allowed) else ""
                service = self.chat.retrieval if config.context_policy.strategy == "history_retrieval" else self.chat.compaction
                await service.prepare(session=session, config=config, run=run, base=base, trace=trace,
                    current=None, profile=profile, support=support, tools=tools, instruction=instruction,
                    max_image_bytes=self.chat.app_settings.get().max_image_size_mb * 1024 * 1024,
                    reasoning=chat_reasoning_mode(profile, support, config.reasoning), manual=True, through=through)
            self.lifecycle.complete_step(step.step_id)
            self.lifecycle.complete_run(run.run_id)
        except asyncio.CancelledError:
            self.lifecycle.fail_step(step.step_id, "RUN_CANCELLED", "Compaction cancelled.")
            self.lifecycle.cancel_run(run.run_id)
        except (ModelError, ChatError) as exc:
            self.lifecycle.fail_step(step.step_id, exc.code, exc.message)
            self.lifecycle.fail_run(run.run_id, exc.code, exc.message)

    def _finished(self, run, task):
        self.active_runs.unregister(run.run_id)
        if task.cancelled():
            self.lifecycle.cancel_run(run.run_id)
        elif (error := task.exception()) is not None:
            # A detached task has no HTTP exception handler. Record an actual failed
            # operation here and retain its traceback instead of losing the task.
            logger.error("Manual compaction failed", exc_info=(type(error), error, error.__traceback__))
            message = "Context compaction failed unexpectedly."
            for step in self.chat.runs.list_steps(run.run_id):
                if step.status in {RunStepStatus.PENDING, RunStepStatus.RUNNING}:
                    self.lifecycle.fail_step(step.step_id, "CONTEXT_COMPACTION_FAILED", message)
            self.lifecycle.fail_run(run.run_id, "CONTEXT_COMPACTION_FAILED", message)
