"""Bounded rolling history shared by automatic and manual compaction."""
from __future__ import annotations

import asyncio
from copy import deepcopy

from sqlalchemy.exc import SQLAlchemyError

from ai_workbench.core.compaction_generation import SummaryGenerator, summary_output
from ai_workbench.core.context_history import ConversationHistory
from ai_workbench.core.context_snapshot import append_system_block, omit_context_images, prepend_system_block
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.chat_support import chat_reasoning_mode
from ai_workbench.core.models.images import resolve_context_images
from ai_workbench.core.models.schema import ChatRequest
from ai_workbench.core.schema.compaction import CompactionOutcome, ContextCheckpoint
from ai_workbench.core.schema.context_snapshot import ContextExclusion, ContextSource, ContextTrace


def message_key(message):
    return message.created_at, message.message_id


class ContextCompactionService:
    def __init__(self, *, sessions, messages, runs, events, model_manager):
        self.sessions, self.messages, self.runs = sessions, messages, runs
        self.events, self.models = events, model_manager

    async def prepare(self, *, session, config, run, base, trace, current, profile, support,
                      tools=None, instruction="", runtime_instruction="", max_image_bytes, reasoning,
                      manual=False, through=None, history=None, on_dispatch=None):
        policy = config.context_policy
        if not policy.history_enabled:
            return base, trace, None
        trace = trace.model_copy(deep=True)
        history = history or ConversationHistory(self.messages, session.session_id, policy, current, through)
        total, eligible = history.counts()
        if total > eligible:
            trace.exclusions.append(ContextExclusion(kind="history", reason="ineligible_history", count=total - eligible))
        checkpoint = self.sessions.get_context_checkpoint(session.session_id) if policy.strategy == "token_budget" else None
        if checkpoint and (checkpoint.history_version != session.history_version
                           or checkpoint.memory_version != getattr(session, "memory_version", 0)
                           or checkpoint.include_attachments != policy.include_attachments):
            self.sessions.discard_context_checkpoint(session.session_id)
            checkpoint = None
        images = profile.request_options.skip_vision_capability_check or support.vision.state != "unsupported"

        def compose(rows, summary=checkpoint):
            result, provenance = deepcopy(base), trace.model_copy(deep=True)
            index = len(result) if manual else len(result) - 1
            inserted, sources = [], ContextTrace()
            if summary:
                inserted.append({"role": "user", "content": "[Historical summary; conversation data]\n" + summary.summary})
                sources.sources.append(ContextSource(id="summary:" + summary.checkpoint_id, kind="summary",
                    message_index=index, role="user", compaction=summary.reference()))
                sources.exclusions.append(ContextExclusion(kind="history", reason="compacted", count=summary.covered_messages))
            for row in rows:
                sources.sources.extend(source.model_copy(update={"message_index": index + len(inserted) + source.message_index})
                    for source in row.trace.sources)
                sources.exclusions.extend(row.trace.exclusions)
                inserted.extend(row.messages)
            for source in provenance.sources:
                if source.message_index is not None and source.message_index >= index:
                    source.message_index += len(inserted)
            result[index:index] = inserted
            provenance.sources.extend(sources.sources)
            provenance.exclusions.extend(sources.exclusions)
            if not images:
                result = omit_context_images(result, provenance)
            provenance.sources.sort(key=lambda source: (source.message_index is None, source.message_index or 0))
            return result, provenance

        async def measure(rows, summary=checkpoint):
            context, provenance = compose(rows, summary)
            if instruction:
                context, _ = prepend_system_block(context, provenance, instruction, "instruction")
            if runtime_instruction:
                context, _ = append_system_block(context, provenance, runtime_instruction, "qq_runtime")
            context = await resolve_context_images(context, max_image_bytes=max_image_bytes)
            # Fixed-only idle prefixes have no user turn. Native templates such
            # as Qwen3.5 reject that shape, so count its empty protocol frame too.
            # It is never composed into history, saved, or dispatched for inference.
            if manual and not any(message["role"] == "user" for message in context):
                context = [*context, {"role": "user", "content": ""}]
            request = ChatRequest(model=profile.alias, messages=context, tools=tools, reasoning=reasoning,
                                  **config.generation.model_dump(exclude_none=True))
            return await self.models.measure_chat(profile.id, request, config.context_limits)

        fixed = await measure([], None)
        if fixed.input_tokens > fixed.input_budget_tokens:
            raise ModelError("CONTEXT_WINDOW_EXCEEDED", "Current input, instructions, knowledge and tools exceed the context window.", 422)
        after = history.checkpoint_key(checkpoint) if checkpoint else None
        recent = []
        used = 0
        original = await measure([])
        exhausted = True
        cutoff_reason = "token_limit"
        message_limit = policy.message_window.max_messages if policy.strategy == "message_window" else None
        # At most a window plus one small database batch is retained. Older rows
        # are read again chronologically only if summarization is necessary.
        for row in history.iterate(after=after):
            if not row.messages:
                continue
            if message_limit is not None and used + row.count > message_limit:
                if recent and row.turn_id == recent[-1].turn_id:
                    while recent and recent[-1].turn_id == row.turn_id:
                        used -= recent.pop().count
                exhausted, cutoff_reason = False, "message_limit"
                original = await measure(list(reversed(recent)))
                break
            recent.append(row)
            used += row.count
            if len(recent) % 8 == 0 or row.qq_batch_id is not None:
                original = await measure(list(reversed(recent)))
                if original.input_tokens > original.input_budget_tokens:
                    exhausted = False
                    # The bounded reverse page may start inside a turn. Drop that
                    # whole candidate group; the forward summary pass reads it in full.
                    oldest_turn = recent[-1].turn_id
                    while recent and recent[-1].turn_id == oldest_turn:
                        used -= recent.pop().count
                    break
        else:
            original = await measure(list(reversed(recent)))
        rows = list(reversed(recent))
        original_fits = exhausted and original.input_tokens <= original.input_budget_tokens
        enabled = policy.strategy == "token_budget" and (manual or policy.compaction.enabled)
        threshold = policy.compaction.target_percent if manual else policy.compaction.trigger_percent
        if not enabled or original.input_tokens <= original.input_budget_tokens * threshold / 100:
            context, provenance = compose(rows)
            if not exhausted:
                missing = eligible - used - (checkpoint.covered_messages if checkpoint else 0)
                if missing > 0:
                    provenance.exclusions.append(ContextExclusion(kind="history", reason=cutoff_reason, count=missing))
            if manual:
                self.record_outcome(run, CompactionOutcome(status="not_needed", reason="below_target" if eligible else "no_history"))
            return context, provenance, None

        output = summary_output(policy.compaction, original.input_budget_tokens)
        target = original.input_budget_tokens * policy.compaction.target_percent // 100 - output
        boundaries = [0]
        previous_turn = None
        for i, row in enumerate(rows):
            turn = row.turn_id
            if i and turn != previous_turn:
                boundaries.append(i)
            previous_turn = turn
        boundaries.append(len(rows))
        low, high = 0, len(boundaries) - 1
        while low < high:
            middle = (low + high) // 2
            if (await measure(rows[boundaries[middle]:], None)).input_tokens <= target:
                high = middle
            else:
                low = middle + 1
        kept = rows[boundaries[low]:]
        prefix_end = kept[0].key if kept else history.before
        boundary = None
        covered = checkpoint.covered_messages if checkpoint else 0
        generator = SummaryGenerator(runs=self.runs, events=self.events, models=self.models, run=run,
            profile=profile, policy=policy, limits=config.context_limits, reasoning=chat_reasoning_mode(profile, support, False),
            output=output, on_dispatch=on_dispatch)

        def texts():
            nonlocal boundary, covered
            for row in history.iterate(after=after, before=prefix_end, ascending=True):
                boundary = row
                covered += row.count
                if row.summary_text:
                    yield row.summary_text

        try:
            summary = await generator.summarize(checkpoint.summary if checkpoint else "", texts())
            if generator.last_step is None or (boundary is None and checkpoint is None):
                if manual:
                    self.record_outcome(run, CompactionOutcome(status="not_needed", reason="no_history"))
                return (*compose(rows), None)
            candidate = ContextCheckpoint(session_id=session.session_id, summary=summary,
                boundary_created_at=boundary.created_at if boundary else checkpoint.boundary_created_at,
                boundary_message_id=boundary.message_id if boundary else checkpoint.boundary_message_id,
                boundary_qq_batch_id=boundary.qq_batch_id if boundary else checkpoint.boundary_qq_batch_id, covered_messages=covered,
                history_version=session.history_version, include_attachments=policy.include_attachments,
                memory_version=getattr(session, "memory_version", 0),
                model_profile_id=profile.id, step_id=generator.last_step, input_tokens_before=original.input_tokens if exhausted else None,
                input_tokens_after=0, counting=original.counting)
            final = await measure(kept, candidate)
            if final.input_tokens > final.input_budget_tokens or final.input_tokens >= original.input_tokens:
                raise ModelError("CONTEXT_COMPACTION_FAILED", "The summary did not reduce this request enough to fit.", 422)
            candidate.input_tokens_after = final.input_tokens
            if self.runs.get_run(run.run_id).cancel_requested:
                raise asyncio.CancelledError()
            if not self.sessions.save_context_checkpoint(candidate):
                raise ModelError("CONTEXT_COMPACTION_FAILED", "History changed before the summary could be saved.", 409)
            self.runs.update_step(generator.last_step, metadata={"compaction": candidate.reference().model_dump(),
                "input_tokens_before": candidate.input_tokens_before, "input_tokens_after": final.input_tokens})
            generator.emit()
            if manual:
                self.record_outcome(run, CompactionOutcome(status="compacted", checkpoint=candidate.reference(),
                    input_tokens_before=candidate.input_tokens_before, input_tokens_after=final.input_tokens))
            return (*compose(kept, candidate), None)
        except (ModelError, SQLAlchemyError) as exc:
            generator.fail(exc.message if isinstance(exc, ModelError) else "Context compaction could not be saved.")
            if manual:
                raise ModelError("CONTEXT_COMPACTION_FAILED", exc.message if isinstance(exc, ModelError)
                    else "Context compaction could not be saved.", 422) from exc
            if not original_fits:
                raise ModelError("CONTEXT_COMPACTION_FAILED", "Context compaction failed and the original history exceeds the window.", 422) from exc
            return (*compose(rows), "context_compaction_failed")

    def record_outcome(self, run, outcome: CompactionOutcome):
        self.runs.update_metadata(run.run_id, {**self.runs.get_run(run.run_id).metadata,
            "compaction": outcome.model_dump(mode="json")})
