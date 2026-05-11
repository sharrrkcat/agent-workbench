from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_workbench.core.settings import AppSettings


CORE_MEMORY_BLOCK_TEMPLATE = """# Core Memory

The following user-maintained memory is stable background context.
Use it when relevant. Do not mention it unless it helps answer the user.

<core_memory>
{content}
</core_memory>"""


@dataclass
class CoreMemoryContextResult:
    rendered_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def build_core_memory_context(
    *,
    app_settings_store: Any = None,
    settings: AppSettings | None = None,
    source: str,
) -> CoreMemoryContextResult:
    try:
        resolved = settings or (app_settings_store.get() if app_settings_store is not None else AppSettings())
    except Exception as exc:
        warning = f"Core memory unavailable: {exc}"
        return CoreMemoryContextResult(
            metadata=_metadata(enabled=False, injected=False, content_chars=0, skipped_reason="settings_error", warnings=[warning]),
            warnings=[warning],
        )

    enabled = _enabled_for_source(resolved, source)
    content = str(getattr(resolved, "core_memory_content", "") or "").strip()
    if not enabled:
        return CoreMemoryContextResult(metadata=_metadata(enabled=False, injected=False, content_chars=len(content), skipped_reason="disabled"))
    if not content:
        return CoreMemoryContextResult(metadata=_metadata(enabled=True, injected=False, content_chars=0, skipped_reason="empty"))

    return CoreMemoryContextResult(
        rendered_text=CORE_MEMORY_BLOCK_TEMPLATE.format(content=content),
        metadata=_metadata(enabled=True, injected=True, content_chars=len(content), skipped_reason=None),
    )


def append_system_context(messages: list[dict[str, Any]], rendered_text: str) -> list[dict[str, Any]]:
    if not rendered_text:
        return messages
    next_messages = [dict(message) for message in messages]
    for index, message in enumerate(next_messages):
        if message.get("role") == "system":
            content = str(message.get("content") or "")
            next_messages[index] = {**message, "content": f"{content.rstrip()}\n\n{rendered_text}" if content.strip() else rendered_text}
            return next_messages
    return [{"role": "system", "content": rendered_text}, *next_messages]


def context_metadata_for_step(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = {"enabled", "injected", "content_chars", "skipped_reason", "warnings"}
    return {key: value for key, value in (metadata or {}).items() if key in allowed}


def _enabled_for_source(settings: AppSettings, source: str) -> bool:
    if source == "script_agent":
        return bool(settings.core_memory_enabled_for_script_agents)
    return bool(settings.core_memory_enabled_for_prompt_agents)


def _metadata(
    *,
    enabled: bool,
    injected: bool,
    content_chars: int,
    skipped_reason: str | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "injected": injected,
        "content_chars": content_chars,
        "skipped_reason": skipped_reason,
        "warnings": list(warnings or []),
    }
