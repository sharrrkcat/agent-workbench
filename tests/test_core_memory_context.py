from ai_workbench.core.memory_context import build_core_memory_context
from ai_workbench.core.settings import AppSettingsStore


def test_core_memory_context_trims_and_records_compact_metadata() -> None:
    settings = AppSettingsStore()
    settings.patch({"core_memory_content": "  stable preference  "})

    result = build_core_memory_context(app_settings_store=settings, source="prompt_agent")

    assert "# Core Memory" in result.rendered_text
    assert "<core_memory>\nstable preference\n</core_memory>" in result.rendered_text
    assert result.metadata == {
        "enabled": True,
        "injected": True,
        "content_chars": len("stable preference"),
        "skipped_reason": None,
        "warnings": [],
    }
    assert "stable preference" not in str(result.metadata)


def test_core_memory_chat_source_injects_enabled_memory() -> None:
    settings = AppSettingsStore()
    settings.patch({"core_memory_content": "script memory"})

    result = build_core_memory_context(app_settings_store=settings, source="chat")

    assert "script memory" in result.rendered_text
    assert result.metadata["injected"] is True
    assert result.metadata["enabled"] is True
    assert result.metadata["skipped_reason"] is None
