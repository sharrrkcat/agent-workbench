"""Per-call window selection; raw conversation history is never mutated."""
import asyncio

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.schema import LocalSource, ModelProfile
from ai_workbench.core.models.token_counting import estimate_input_tokens
from ai_workbench.core.schema.context_budget import ContextBudgetStats, ContextLimits
from ai_workbench.core.schema.context_snapshot import ContextExclusion, ContextTrace


def configured_limits(profile: ModelProfile) -> ContextLimits:
    window = (int(profile.source.execution_options.get("context_size", 4096))
              if isinstance(profile.source, LocalSource) else profile.context_window_tokens)
    output = profile.parameters.get("max_tokens")
    if output is None and window is not None:
        output = min(4096, window // 4)
    return ContextLimits(window_tokens=window, output_tokens=output)


class ChatContextBudget:
    def __init__(self, limits: ContextLimits, trace: ContextTrace):
        self.limits = limits
        self.trace = trace.model_copy(deep=True)
        self.stats: ContextBudgetStats | None = None

    async def prepare(self, profile, request, adapter):
        configured = self.limits.window_tokens
        if configured is None:
            raise ModelError("CONTEXT_WINDOW_REQUIRED", "Set this model's context window before chatting.", 422)
        local = isinstance(profile.source, LocalSource)
        native_window = await adapter.context_window() if local else None
        window = min(configured, native_window) if native_window is not None else configured
        output = self.limits.output_tokens
        margin = 32 if local else max(128, (window + 9) // 10)
        available = window - output - margin
        if available < 0:
            raise ModelError("CONTEXT_WINDOW_EXCEEDED", "The output reserve leaves no room for this model input.", 422)
        request = request.model_copy(update={"max_tokens": output})
        wire_profile = profile.model_copy(update={"model_ref": "managed"}) if local else profile
        payload = OpenAIAdapter._payload(wire_profile, request)
        groups = self._history_groups()
        group_positions = {index: position for position, group in enumerate(groups) for index in group}

        def retained_indices(cut):
            return [i for i in range(len(request.messages)) if group_positions.get(i, len(groups)) >= cut]

        async def count(cut):
            body = {**payload, "messages": [payload["messages"][i] for i in retained_indices(cut)]}
            if local:
                return await adapter.count_input_tokens(body)
            try:
                return await asyncio.to_thread(estimate_input_tokens, body)
            except (OSError, ValueError) as exc:
                raise ModelError("CONTEXT_COUNT_FAILED", "The offline reference tokenizer could not count this input.", 500) from exc

        cut, tokens = 0, await count(0)
        if tokens > available:
            last = len(groups)
            tokens = await count(last) if last else tokens
            if tokens > available:
                raise ModelError("CONTEXT_WINDOW_EXCEEDED",
                    "Current input, instructions, knowledge and active tool data exceed the context window even without history.",
                    422, {"window_tokens": window, "input_tokens": tokens, "output_tokens": output, "margin_tokens": margin})
            low, high = 0, last
            while low + 1 < high:
                middle = (low + high) // 2
                if await count(middle) <= available:
                    high = middle
                else:
                    low = middle
            cut = high
            # The dispatched suffix must be measured, independently of the search.
            tokens = await count(cut)
            if tokens > available:
                raise ModelError("CONTEXT_WINDOW_EXCEEDED", "The final input exceeds the context budget.", 422)
        retained = retained_indices(cut)
        self._remap_trace(retained)
        self.stats = ContextBudgetStats(configured_window_tokens=configured, window_tokens=window,
            input_budget_tokens=available, input_tokens=tokens, counting="native" if local else "estimated",
            output_tokens=output, margin_tokens=margin, removed_turns=cut)
        return request.model_copy(update={"messages": [request.messages[i] for i in retained]})

    def _history_groups(self):
        # An old system message can share its slot with newly appended instructions.
        fixed = {s.message_index for s in self.trace.sources if s.kind in {
            "agent_persona", "project_prompt", "cogita_persona", "knowledge", "current_input", "qq_runtime"}}
        groups = {}
        for source in self.trace.sources:
            if source.kind == "history" and source.message_index not in fixed:
                groups.setdefault(source.turn_id, []).append(source.message_index)
        return list(groups.values())

    def _remap_trace(self, retained):
        positions = {old: new for new, old in enumerate(retained)}
        sources = []
        for source in self.trace.sources:
            if source.message_index is None:
                sources.append(source)
            elif source.message_index in positions:
                sources.append(source.model_copy(update={"message_index": positions[source.message_index]}))
            else:
                self.trace.exclusions.append(ContextExclusion(kind=source.kind, reason="token_limit",
                    reference_id=source.reference_id or (source.attachment.id if source.attachment else None), name=source.name))
        self.trace.sources = sources
