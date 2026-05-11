from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from tests.test_api import create_session
from tests.test_prompt_agent_execution import FakeLLMRuntime


def make_client() -> TestClient:
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(response="ok"), use_memory=True))


def test_runtime_memory_summary_lists_targets() -> None:
    client = make_client()
    session = create_session(client)

    response = client.get(f"/api/runtime/memory?session_id={session['session_id']}")

    assert response.status_code == 200
    targets = {item["target"]: item for item in response.json()["targets"]}
    assert set(targets) == {"llm", "comfyui", "embedding", "reranker"}
    assert targets["embedding"]["status"] == "not_loaded"
    assert targets["reranker"]["status"] == "not_loaded"


def test_free_memory_embedding_and_reranker_skip_when_not_loaded() -> None:
    client = make_client()

    response = client.post("/api/runtime/free-memory", json={"targets": ["embedding", "reranker"]})

    assert response.status_code == 200
    assert response.json()["results"] == [
        {"target": "embedding", "status": "skipped", "message": "No model loaded."},
        {"target": "reranker", "status": "skipped", "message": "No model loaded."},
    ]


def test_free_memory_all_expands_and_continues_independently() -> None:
    client = make_client()
    state = client.app.state.runtime_state
    state.knowledge_model_backend._embedding_cache[("embedding-path", "cpu")] = object()
    state.knowledge_model_backend._reranker_cache[("reranker-path", "cpu")] = object()

    response = client.post("/api/runtime/free-memory", json={"targets": ["all"]})

    assert response.status_code == 200
    results = {item["target"]: item for item in response.json()["results"]}
    assert set(results) == {"llm", "comfyui", "embedding", "reranker"}
    assert results["embedding"]["status"] == "freed"
    assert results["reranker"]["status"] == "freed"


def test_free_memory_returns_busy_for_active_embedding() -> None:
    client = make_client()
    state = client.app.state.runtime_state
    state.knowledge_model_backend._embedding_cache[("embedding-path", "cpu")] = object()
    state.knowledge_model_backend._active_embedding_calls = 1

    response = client.post("/api/runtime/free-memory", json={"targets": ["embedding"]})

    assert response.status_code == 200
    assert response.json()["results"] == [
        {"target": "embedding", "status": "busy", "message": "Embedding is busy."}
    ]
    assert state.knowledge_model_backend._embedding_cache


def test_free_memory_invalid_target_is_structured_error() -> None:
    client = make_client()

    response = client.post("/api/runtime/free-memory", json={"targets": ["gpu"]})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_RUNTIME_MEMORY_TARGET"


def test_free_memory_command_usage_and_result() -> None:
    client = make_client()
    session = create_session(client)

    usage = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/free-memory"})
    assert usage.status_code == 200
    usage_messages = usage.json()["messages"]
    assert usage_messages[-1]["content"] == "/free-memory [llm|comfyui|embedding|reranker|all]"

    result = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/free-memory embedding"})
    assert result.status_code == 200
    messages = result.json()["messages"]
    assert messages[-1]["command_name"] == "/free-memory"
    assert "Memory release result" in messages[-1]["content"]
    assert "Embedding: skipped" in messages[-1]["content"]
