import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.worldbook import MemoryWorldbookStore, Worldbook, WorldbookEntry, collect_worldbook_matches


@pytest.mark.parametrize("use_memory", [True, False])
def test_worldbook_match_test_applies_entry_and_context_limits(tmp_path, use_memory):
    app = create_app(root=tmp_path, use_memory=use_memory, database_url=f"sqlite:///{tmp_path / 'worldbook.db'}")
    with TestClient(app) as client:
        book = client.post("/api/worldbooks", json={"name": "Lore"}).json()
        entries = [client.post(f"/api/worldbooks/{book['id']}/entries", json={
            "name": name, "activation_mode": "always", "content": name * 600,
        }).json() for name in ("A", "B")]
        for max_entries, max_chars in ((1, 2000), (2, 1000)):
            assert client.patch("/api/worldbook/settings", json={
                "worldbook_max_entries_per_call": max_entries, "worldbook_max_context_chars": max_chars,
            }).status_code == 200
            response = client.post("/api/worldbooks/match-test", json={"worldbook_ids": [book["id"]]})
            assert response.status_code == 200
            result = response.json()
            assert result["matched_count"] == 2 and result["included_count"] == 1
            assert result["truncated"] is True
            assert result["results"][0]["entry_id"] == entries[0]["id"]


def test_worldbook_matching_invalid_regex_warns_and_continues():
    store = MemoryWorldbookStore()
    book = store.create_worldbook(Worldbook(name="Lore"))
    bad = WorldbookEntry.model_construct(id="bad", worldbook_id=book.id, name="Bad", keywords_text="[",
        content="Bad lore.", activation_mode="keyword", enabled=True, sort_order=10)
    store._entries[bad.id] = bad
    always = store.create_entry(WorldbookEntry(worldbook_id=book.id, name="Always", activation_mode="always", content="Lore"))
    result = collect_worldbook_matches(worldbook_store=store, worldbook_ids=[book.id], text="anything", settings=store.get_settings())
    assert [item["entry"].id for item in result["matched"]] == [always.id]
    assert any(warning["code"] == "WORLDBOOK_INVALID_REGEX" for warning in result["warnings"])
