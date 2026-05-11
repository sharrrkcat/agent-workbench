from ai_workbench.core.worldbook import MemoryWorldbookStore, Worldbook, WorldbookEntry
from ai_workbench.core.worldbook_context import build_session_worldbook_context


def test_worldbook_context_applies_entry_and_context_limits() -> None:
    store = MemoryWorldbookStore()
    store.patch_settings({"worldbook_max_entries_per_call": 1, "worldbook_max_context_chars": 1000})
    worldbook = store.create_worldbook(Worldbook(name="Lore"))
    first = store.create_entry(
        WorldbookEntry(worldbook_id=worldbook.id, name="Always", activation_mode="always", content="A" * 1200)
    )
    store.create_entry(
        WorldbookEntry(worldbook_id=worldbook.id, name="Keyword", keywords_text="dragon", content="Dragon lore.")
    )
    store.replace_session_bindings("session-1", [worldbook.id])

    result = build_session_worldbook_context(
        worldbook_store=store,
        session_id="session-1",
        user_text="dragon",
        source="prompt_agent",
    )

    assert result.metadata["matched_entry_count"] == 2
    assert result.metadata["injected_entry_count"] == 1
    assert result.metadata["truncated"] is True
    assert result.metadata["entry_refs"][0]["entry_id"] == first.id
    assert len(result.rendered_text) <= 1000
    assert "A" * 1200 not in str(result.metadata)


def test_worldbook_context_invalid_regex_warns_and_continues() -> None:
    store = MemoryWorldbookStore()
    worldbook = store.create_worldbook(Worldbook(name="Lore"))
    bad = WorldbookEntry.model_construct(
        id="bad",
        worldbook_id=worldbook.id,
        name="Bad",
        keywords_text="[",
        content="Bad lore.",
        activation_mode="keyword",
        enabled=True,
        sort_order=10,
    )
    store._entries[bad.id] = bad
    always = store.create_entry(
        WorldbookEntry(worldbook_id=worldbook.id, name="Always", activation_mode="always", content="Always lore.")
    )
    store.replace_session_bindings("session-1", [worldbook.id])

    result = build_session_worldbook_context(
        worldbook_store=store,
        session_id="session-1",
        user_text="anything",
        source="prompt_agent",
    )

    assert result.metadata["matched_entry_count"] == 1
    assert result.metadata["entry_refs"][0]["entry_id"] == always.id
    assert any("Invalid worldbook regex" in warning for warning in result.metadata["warnings"])
    assert "Bad lore." not in result.rendered_text
