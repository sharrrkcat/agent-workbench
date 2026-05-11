from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_workbench.core.worldbook import WorldbookSettings, collect_worldbook_matches


@dataclass
class WorldbookContextResult:
    rendered_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def build_session_worldbook_context(
    *,
    worldbook_store: Any,
    session_id: str,
    user_text: str,
    source: str,
) -> WorldbookContextResult:
    input_text = str(user_text or "")
    input_empty = not input_text.strip()
    if worldbook_store is None:
        return WorldbookContextResult(metadata=_skipped("no_store", source=source, input_empty=input_empty))

    try:
        settings = worldbook_store.get_settings()
    except Exception as exc:
        warning = f"Worldbook settings unavailable: {exc}"
        return WorldbookContextResult(
            metadata={**_skipped("settings_error", source=source, input_empty=input_empty), "warnings": [warning]},
            warnings=[warning],
        )

    if not _enabled_for_source(settings, source):
        return WorldbookContextResult(metadata=_skipped("disabled", source=source, input_empty=input_empty))
    if not session_id:
        return WorldbookContextResult(metadata=_skipped("no_session", source=source, input_empty=input_empty))

    warnings: list[str] = []
    try:
        bindings = [
            binding
            for binding in worldbook_store.list_session_bindings(session_id)
            if getattr(binding, "enabled", False) and getattr(binding, "worldbook", None) is not None
        ]
    except Exception as exc:
        warning = f"Worldbook bindings unavailable: {exc}"
        return WorldbookContextResult(
            metadata={**_skipped("bindings_error", source=source, input_empty=input_empty), "warnings": [warning]},
            warnings=[warning],
        )
    bindings.sort(key=lambda item: (getattr(item, "sort_order", 0), getattr(item, "created_at", None)))
    bindings = [binding for binding in bindings if getattr(binding.worldbook, "enabled", False)]
    if not bindings:
        return WorldbookContextResult(metadata=_skipped("no_bound_worldbooks", source=source, input_empty=input_empty))

    worldbook_ids: list[str] = []
    for binding in bindings:
        worldbook_ids.append(binding.worldbook.id)
    match_data = collect_worldbook_matches(
        worldbook_store=worldbook_store,
        worldbook_ids=worldbook_ids,
        text=input_text,
        settings=settings,
    )
    warnings.extend(_warning_messages(match_data["warnings"]))
    matched: list[dict[str, Any]] = match_data["matched"]

    rendered_text, entry_refs, truncated = _render_entries(matched, settings)
    metadata = {
        "enabled": True,
        "injected": bool(rendered_text),
        "source": source,
        "worldbook_ids": match_data["worldbook_ids"],
        "matched_entry_count": len(matched),
        "injected_entry_count": len(entry_refs),
        "truncated": truncated,
        "input_empty": input_empty,
        "recursion_depth": match_data["recursion_depth"],
        "recursion_rounds_used": match_data["recursion_rounds_used"],
        "case_sensitive": match_data["case_sensitive"],
        "whole_words": match_data["whole_words"],
        "warnings": warnings,
        "entry_refs": entry_refs,
    }
    if truncated:
        warning = "Worldbook context truncated by max entries or max context chars."
        warnings.append(warning)
        metadata["warnings"] = warnings
    if not rendered_text:
        metadata["skipped_reason"] = "no_matching_entries" if not matched else "context_budget_exhausted"
    return WorldbookContextResult(rendered_text=rendered_text, metadata=metadata, warnings=warnings)


def worldbook_step_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "enabled",
        "injected",
        "source",
        "worldbook_ids",
        "matched_entry_count",
        "injected_entry_count",
        "truncated",
        "input_empty",
        "recursion_depth",
        "recursion_rounds_used",
        "case_sensitive",
        "whole_words",
        "skipped_reason",
        "warnings",
        "entry_refs",
    }
    return {key: value for key, value in (metadata or {}).items() if key in allowed}


def _enabled_for_source(settings: WorldbookSettings, source: str) -> bool:
    if source == "script_agent":
        return bool(settings.worldbook_enabled_for_script_agents)
    return bool(settings.worldbook_enabled_for_prompt_agents)


def _render_entries(items: list[dict[str, Any]], settings: WorldbookSettings) -> tuple[str, list[dict[str, Any]], bool]:
    max_entries = int(getattr(settings, "worldbook_max_entries_per_call", 20) or 20)
    max_chars = int(getattr(settings, "worldbook_max_context_chars", 8000) or 8000)
    header = (
        "# Worldbook\n\n"
        "The following entries are user-maintained world/context information.\n"
        "Use them when relevant and keep the final answer consistent with them."
    )
    parts = [header]
    entry_refs: list[dict[str, Any]] = []
    truncated = False
    total_chars = len(header)
    for matched_index, item in enumerate(items, start=1):
        if len(entry_refs) >= max_entries:
            truncated = True
            break
        worldbook = item["worldbook"]
        entry = item["entry"]
        injected_index = f"W{len(entry_refs) + 1}"
        block_prefix = (
            f"[{injected_index}]\n"
            f"Worldbook: {worldbook.name}\n"
            f"Entry: {entry.name}\n"
            "Content:\n"
        )
        content = str(entry.content or "").strip()
        separator_chars = 2
        available = max_chars - total_chars - separator_chars - len(block_prefix)
        if available <= 0:
            truncated = True
            break
        block_truncated = len(content) > available
        if block_truncated:
            content = content[: max(0, available - 15)].rstrip() + "\n[truncated]"
            truncated = True
        block = f"{block_prefix}{content}".strip()
        parts.append(block)
        total_chars += separator_chars + len(block)
        entry_refs.append(
            {
                "index": injected_index,
                "worldbook_id": worldbook.id,
                "worldbook_name": worldbook.name,
                "entry_id": entry.id,
                "entry_name": entry.name,
                "activation_mode": entry.activation_mode,
                "matched_by_recursion": bool(item.get("matched_by_recursion", False)),
                "recursion_depth": int(item.get("recursion_depth", 0) or 0),
                "injected_index": matched_index,
            }
        )
        if block_truncated:
            break
    return ("\n\n".join(parts) if entry_refs else ""), entry_refs, truncated


def _skipped(reason: str, *, source: str, input_empty: bool) -> dict[str, Any]:
    return {
        "enabled": False,
        "injected": False,
        "source": source,
        "worldbook_ids": [],
        "matched_entry_count": 0,
        "injected_entry_count": 0,
        "truncated": False,
        "input_empty": input_empty,
        "recursion_depth": 0,
        "recursion_rounds_used": 0,
        "case_sensitive": False,
        "whole_words": True,
        "skipped_reason": reason,
        "warnings": [],
        "entry_refs": [],
    }


def _warning_messages(warnings: list[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for warning in warnings:
        code = warning.get("code")
        message = str(warning.get("message") or code or "Worldbook warning.")
        if code == "WORLDBOOK_INVALID_REGEX":
            message = f"Invalid worldbook regex skipped for entry {warning.get('entry_id', '')}: {message.removeprefix('Invalid regex: ')}"
        messages.append(message)
    return messages
