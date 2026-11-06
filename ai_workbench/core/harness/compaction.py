"""Compact model-visible completed rounds without changing execution state."""
import asyncio
import json

from ai_workbench.core.assistant_output import ThinkParser
from ai_workbench.core.compaction_generation import SummaryGenerator, summary_output
from ai_workbench.core.models.context_budget import ChatContextBudget
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import ChatMessage
from ai_workbench.core.schema.compaction import RunCompactionState
from ai_workbench.core.schema.context_snapshot import ContextExclusion, ContextSource
from ai_workbench.core.memory_context import strip_memory_transcript


class HarnessCompaction:
    def __init__(self, models, runs, events):
        self.models, self.runs, self.events = models, runs, events

    async def prepare(self, *, base, trace, config, profile, run, state, on_dispatch=None):
        old = state.compaction
        start = old.transcript_end if old else 0

        def compose(summary=old, end=start):
            messages = list(base.messages)
            provenance = trace.model_copy(deep=True)
            if summary:
                provenance.sources.append(ContextSource(id="run-summary:" + summary.checkpoint_id, kind="summary",
                    message_index=len(messages), role="user", run_compaction=summary.reference()))
                provenance.exclusions.append(ContextExclusion(kind="tool_call", reason="compacted",
                    count=summary.covered_tool_calls))
                messages.append(ChatMessage(role="user", content="[Current run summary; completed tool data]\n" + summary.summary))
            messages.extend(ChatMessage.model_validate(item) for item in state.transcript[end:])
            return base.model_copy(update={"messages": messages}), provenance

        async def select(request, provenance):
            budget = ChatContextBudget(config.context_limits, provenance)
            selected = await self.models.select_chat_context(profile.id, request, budget)
            return selected, budget

        original, original_trace = compose()
        original, original_trace = await self.models.limit_memory_context(profile.id, original, config.context_limits, original_trace)
        policy = config.context_policy
        if policy.strategy != "token_budget" or not policy.compaction.enabled or not state.transcript:
            return original, original_trace, None
        initial = await self.models.measure_chat(profile.id, original, config.context_limits)
        if initial.input_tokens <= initial.input_budget_tokens * policy.compaction.trigger_percent / 100:
            return original, original_trace, None

        original_fits = True
        try:
            await select(original, original_trace)
        except ModelError as exc:
            if exc.code != "CONTEXT_WINDOW_EXCEEDED":
                raise
            original_fits = False
            # A summary cannot repair an oversized current input or fixed prompt.
            await select(base, trace)

        starts = [i for i, item in enumerate(state.transcript) if item["role"] == "assistant"]
        latest = starts[-1]
        ends = [index for index in starts if index > start]
        output = summary_output(policy.compaction, initial.input_budget_tokens)
        target = initial.input_budget_tokens * policy.compaction.target_percent // 100 - output
        if not ends:
            if original_fits:
                return original, original_trace, None
            end = len(state.transcript)
        else:
            # Prefer the smallest completed prefix that leaves a recent suffix.
            end = latest
            for candidate_end in ends:
                candidate_request, candidate_trace = compose(None, candidate_end)
                candidate_request, _ = await self.models.limit_memory_context(profile.id, candidate_request, config.context_limits, candidate_trace)
                count = await self.models.measure_chat(profile.id, candidate_request, config.context_limits)
                if count.input_tokens <= target:
                    end = candidate_end
                    break

        generator = SummaryGenerator(models=self.models, runs=self.runs, events=self.events, run=run,
            profile=profile, policy=policy, limits=config.context_limits, reasoning=state.summary_reasoning,
            output=output, scope="run", on_dispatch=on_dispatch)

        def texts(begin, stop):
            for message in strip_memory_transcript(state.transcript[begin:stop]):
                # Tool results already contain the bounded web evidence projection.
                projected = {key: value for key, value in message.items() if key != "reasoning_content"}
                if message["role"] == "assistant" and message.get("content"):
                    pieces = []
                    ThinkParser(lambda kind, text: pieces.append(text) if kind == "text" else None).feed(message["content"], final=True)
                    projected["content"] = "".join(pieces) or None
                yield json.dumps(projected, ensure_ascii=False, allow_nan=False) + "\n"

        try:
            summary = await generator.summarize(old.summary if old else "", texts(start, end))
            while True:
                candidate = RunCompactionState(run_id=run.run_id, summary=summary, transcript_end=end,
                    through_round=sum(index < end for index in starts),
                    covered_tool_calls=sum(len(item.get("tool_calls", [])) for item in state.transcript[:end]),
                    model_profile_id=profile.id, step_id=generator.last_step)
                request, provenance = compose(candidate, end)
                request, provenance = await self.models.limit_memory_context(profile.id, request, config.context_limits, provenance)
                full = await self.models.measure_chat(profile.id, request, config.context_limits)
                if full.input_tokens >= initial.input_tokens:
                    raise ModelError("CONTEXT_COMPACTION_FAILED", "The summary did not reduce this tool transcript.", 422)
                try:
                    selected, budget = await select(request, provenance)
                except ModelError as exc:
                    if exc.code != "CONTEXT_WINDOW_EXCEEDED" or end == len(state.transcript):
                        raise
                    # The newest batch is eligible only after old-history pruning
                    # still cannot fit it alongside the successfully generated memory.
                    summary = await generator.summarize(summary, texts(end, len(state.transcript)))
                    end = len(state.transcript)
                    continue
                if self.runs.get_run(run.run_id).cancel_requested:
                    raise asyncio.CancelledError()
                state.compaction = candidate
                self.runs.update_step(generator.last_step, metadata={"run_compaction": candidate.reference().model_dump(),
                    "input_tokens_before": initial.input_tokens, "input_tokens_after": budget.stats.input_tokens})
                generator.emit()
                return request, provenance, None
        except ModelError as exc:
            generator.fail(exc.message)
            if not original_fits:
                raise ModelError("CONTEXT_COMPACTION_FAILED", "Compaction failed and the active tool context exceeds the window.", 422) from exc
            return original, original_trace, "context_compaction_failed"
