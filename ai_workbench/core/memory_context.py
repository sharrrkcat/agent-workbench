"""Trim memory index entries and native memory-call pairs without splitting frames."""

from ai_workbench.core.memory_prompt import replace_memory_index
from ai_workbench.core.schema.memory import MEMORY_TOOL_NAMES
from ai_workbench.core.schema.context_snapshot import ContextExclusion


def memory_units(request, trace):
    facts = [("fact", source.id) for source in trace.sources
        if source.kind == "durable_memory" and source.memory is not None and source.role == "system"]
    calls = [("call", call.id) for message in request.messages for call in message.tool_calls or []
        if call.function.name in MEMORY_TOOL_NAMES]
    return list(dict.fromkeys(facts)), calls


def remove_memory(request, trace, units):
    facts = {value for kind, value in units if kind == "fact"}
    calls = {value for kind, value in units if kind == "call"}
    provenance = trace.model_copy(deep=True)
    messages = list(request.messages)
    if facts:
        root = next(source for source in provenance.sources if source.kind == "memory_index")
        entries = [source for source in provenance.sources if source.parent_id == root.id]
        kept = [source for source in entries if source.id not in facts]
        provenance.exclusions.extend(ContextExclusion(kind=source.kind, reason="token_limit", reference_id=source.reference_id)
            for source in entries if source.id in facts)
        message = messages[root.message_index]
        content = replace_memory_index(message.content, provenance, kept, limited=True)
        messages[root.message_index] = message.model_copy(update={"content": content})
    result, positions = [], {}
    for index, message in enumerate(messages):
        if message.tool_call_id in calls:
            continue
        if message.tool_calls and any(call.id in calls for call in message.tool_calls):
            kept = [call for call in message.tool_calls if call.id not in calls]
            if not kept:
                continue
            message = message.model_copy(update={"tool_calls": kept or None})
        positions[index] = len(result)
        result.append(message)
    sources = provenance.sources
    provenance.sources = []
    for source in sources:
        if source.message_index is None:
            provenance.sources.append(source)
        elif source.message_index in positions:
            provenance.sources.append(source.model_copy(update={"message_index": positions[source.message_index]}))
        else:
            provenance.exclusions.append(ContextExclusion(kind=source.kind, reason="token_limit", reference_id=source.reference_id))
    return request.model_copy(update={"messages": result}), provenance


def strip_memory_transcript(transcript):
    """Compaction must not copy private memory payloads into an unbounded summary."""
    call_ids = {call["id"] for message in transcript for call in message.get("tool_calls", [])
        if call["function"]["name"] in MEMORY_TOOL_NAMES}
    for message in transcript:
        if message.get("tool_call_id") in call_ids:
            continue
        if "tool_calls" in message:
            kept = [call for call in message["tool_calls"] if call["id"] not in call_ids]
            if not kept:
                continue
            message = {**message, "tool_calls": kept}
        yield message
