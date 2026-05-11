from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from ai_workbench.core.worldbook import WorldbookSettings, keyword_patterns


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

    flags = re.IGNORECASE if bool(getattr(settings, "worldbook_regex_case_insensitive", True)) else 0
    matched: list[dict[str, Any]] = []
    worldbook_ids: list[str] = []
    for binding in bindings:
        worldbook = binding.worldbook
        worldbook_ids.append(worldbook.id)
        try:
            entries = list(worldbook_store.list_entries(worldbook.id))
        except Exception as exc:
            warnings.append(f"Worldbook entries unavailable for {worldbook.id}: {exc}")
            continue
        entries.sort(key=lambda item: (getattr(item, "sort_order", 0), getattr(item, "created_at", None)))
        for entry in entries:
            if not getattr(entry, "enabled", False):
                continue
            if _entry_matches(entry, input_text, flags, warnings):
                matched.append({"worldbook": worldbook, "entry": entry})

    rendered_text, entry_refs, truncated = _render_entries(matched, settings)
    metadata = {
        "enabled": True,
        "injected": bool(rendered_text),
        "source": source,
        "worldbook_ids": worldbook_ids,
        "matched_entry_count": len(matched),
        "injected_entry_count": len(entry_refs),
        "truncated": truncated,
        "input_empty": input_empty,
        "warnings": warnings,
        "entry_refs": entry_refs,
    }
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
        "skipped_reason",
        "warnings",
        "entry_refs",
    }
    return {key: value for key, value in (metadata or {}).items() if key in allowed}


def _enabled_for_source(settings: WorldbookSettings, source: str) -> bool:
    if source == "script_agent":
        return bool(settings.worldbook_enabled_for_script_agents)
    return bool(settings.worldbook_enabled_for_prompt_agents)


def _entry_matches(entry: Any, user_text: str, flags: int, warnings: list[str]) -> bool:
    mode = getattr(entry, "activation_mode", "keyword")
    if mode == "always":
        return True
    patterns = keyword_patterns(getattr(entry, "keywords_text", ""))
    if not patterns:
        warnings.append(f"Worldbook entry has no keyword patterns: {getattr(entry, 'id', '')}")
        return False
    if not user_text.strip():
        return False
    for pattern in patterns:
        try:
            if re.search(pattern, user_text, flags=flags):
                return True
        except re.error as exc:
            warnings.append(f"Invalid worldbook regex skipped for entry {getattr(entry, 'id', '')}: {exc}")
    return False


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
        "skipped_reason": reason,
        "warnings": [],
        "entry_refs": [],
    }
