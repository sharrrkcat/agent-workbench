"""Inspect QQ projections separately from inference and trigger scheduling."""
from functools import partial

from ai_workbench.core.context import ContextBuildResult
from ai_workbench.core.models.chat_support import ChatSupport
from ai_workbench.core.qq_context import QQContextHistory, build_qq_context
from ai_workbench.core.schema.context_snapshot import ContextTrace


def character_qq_context(store, messages, session_id, text, policy, current_message_id, **options):
    """Character all submitted history; window/compaction behavior uses prepare_qq_context."""
    result = build_qq_context(store, messages, session_id, text, policy, current_message_id, **options)
    current = messages.get_message(current_message_id) if current_message_id else None
    history = QQContextHistory(store, messages, session_id, policy, current, **options)
    projected = []
    trace = ContextTrace()
    if policy.history_enabled:
        for row in history.iterate(ascending=True):
            for source in row.trace.sources:
                trace.sources.append(source.model_copy(update={"message_index": len(projected) + source.message_index}))
            trace.exclusions.extend(row.trace.exclusions)
            projected.extend(row.messages)
    trace.sources.extend(source.model_copy(update={"message_index": len(projected) + source.message_index})
        for source in result.trace.sources)
    trace.exclusions.extend(result.trace.exclusions)
    return ContextBuildResult(messages=[*projected, *result.messages], trace=trace)


def prepare_qq_context(client, state, session_id, policy, *, text="next", current_message_id=None):
    session = state.sessions.get_session(session_id)
    config = state.chat_service.resolve(session).model_copy(update={"context_policy": policy})
    profile = state.model_profiles.get(config.model_profile_id)
    current = state.messages.get_message(current_message_id) if current_message_id else None
    base = build_qq_context(state.qq.store, state.messages, session_id, text, policy, current_message_id)
    history = QQContextHistory(state.qq.store, state.messages, session_id, policy, current)
    run = state.runs.create_run("chat", "00000000-0000-4000-8000-000000000001", config.persona_id, session_id)
    state.runs.update_status(run.run_id, "RUNNING")
    try:
        context, trace, _ = client.portal.call(partial(state.chat_runner.compaction.prepare,
            session=session, config=config, run=run, base=base.messages, trace=base.trace,
            current=current, profile=profile, support=ChatSupport(), history=history,
            max_image_bytes=10 * 1024 * 1024, reasoning=False))
        return ContextBuildResult(messages=context, trace=trace)
    finally:
        state.runs.update_status(run.run_id, "DONE")
