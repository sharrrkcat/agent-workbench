from pathlib import Path

from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from tests.test_prompt_agent_execution import FakeLLMRuntime


def test_worldbook_settings_validate_and_persist(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'worldbook.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))

    response = client.get("/api/worldbook/settings")
    assert response.status_code == 200
    assert response.json()["worldbook_enabled_for_prompt_agents"] is True
    assert response.json()["worldbook_enabled_for_script_agents"] is False
    assert response.json()["worldbook_max_entries_per_call"] == 20
    assert response.json()["worldbook_max_context_chars"] == 8000
    assert response.json()["worldbook_regex_case_insensitive"] is True

    patched = client.patch(
        "/api/worldbook/settings",
        json={
            "worldbook_enabled_for_prompt_agents": False,
            "worldbook_enabled_for_script_agents": True,
            "worldbook_max_entries_per_call": 2,
            "worldbook_max_context_chars": 1000,
            "worldbook_regex_case_insensitive": False,
        },
    )
    assert patched.status_code == 200
    assert patched.json()["worldbook_max_entries_per_call"] == 2
    assert client.patch("/api/worldbook/settings", json={"worldbook_max_entries_per_call": 0}).status_code == 422
    assert client.patch("/api/worldbook/settings", json={"unknown": True}).status_code == 422

    restarted = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))
    assert restarted.get("/api/worldbook/settings").json()["worldbook_max_entries_per_call"] == 2


def test_worldbook_crud_entries_reorder_session_bindings_and_match(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'worldbook-api.db'}"))
    session = client.post("/api/sessions", json={"title": "Worldbook test", "default_agent_id": "chat"}).json()

    created = client.post("/api/worldbooks", json={"name": "Lore", "description": "campaign", "enabled": True})
    assert created.status_code == 200
    wb = created.json()
    assert wb["entry_count"] == 0
    wb_id = wb["id"]

    always = client.post(
        f"/api/worldbooks/{wb_id}/entries",
        json={"name": "Always", "content": "Always include this.", "activation_mode": "always", "enabled": True},
    )
    keyword = client.post(
        f"/api/worldbooks/{wb_id}/entries",
        json={"name": "Dragon", "keywords_text": "dragon\nwyvern", "content": "Dragons breathe fire.", "activation_mode": "keyword", "enabled": True},
    )
    assert always.status_code == 200
    assert keyword.status_code == 200

    entries = client.get(f"/api/worldbooks/{wb_id}/entries").json()
    assert [entry["name"] for entry in entries] == ["Always", "Dragon"]
    reordered = client.patch(f"/api/worldbooks/{wb_id}/entries/reorder", json={"entry_ids": [keyword.json()["id"], always.json()["id"]]})
    assert reordered.status_code == 200
    assert [entry["name"] for entry in reordered.json()["entries"]] == ["Dragon", "Always"]

    bindings = client.patch(f"/api/sessions/{session['session_id']}/worldbooks", json={"worldbook_ids": [wb_id]})
    assert bindings.status_code == 200
    assert bindings.json()["enabled_worldbooks"][0]["worldbook_id"] == wb_id
    assert client.get(f"/api/sessions/{session['session_id']}/worldbooks").json()["enabled_worldbooks"][0]["worldbook"]["name"] == "Lore"

    match = client.post("/api/worldbooks/match-test", json={"text": "The dragon arrives.", "session_id": session["session_id"]})
    assert match.status_code == 200
    payload = match.json()
    assert payload["matched_count"] == 2
    assert [result["entry_name"] for result in payload["results"]] == ["Dragon", "Always"]
    assert payload["results"][0]["matched_keywords"] == ["dragon"]

    invalid = client.post(
        f"/api/worldbooks/{wb_id}/entries",
        json={"name": "Bad", "keywords_text": "[", "content": "bad", "activation_mode": "keyword"},
    )
    assert invalid.status_code == 422

    deleted = client.delete(f"/api/worldbooks/{wb_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/sessions/{session['session_id']}/worldbooks").json()["enabled_worldbooks"] == []
