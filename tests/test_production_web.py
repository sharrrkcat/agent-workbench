from pathlib import Path

from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from tests.test_prompt_agent_execution import FakeLLMRuntime


def make_client(frontend_dist: Path) -> TestClient:
    return TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True, frontend_dist=frontend_dist))


def test_frontend_missing_root_returns_clear_build_message(tmp_path: Path) -> None:
    client = make_client(tmp_path / "missing-dist")

    response = client.get("/")

    assert response.status_code == 503
    assert "frontend build not found" in response.text
    assert "npm run build" in response.text


def test_frontend_missing_does_not_block_api(tmp_path: Path) -> None:
    client = make_client(tmp_path / "missing-dist")

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_frontend_dist_root_returns_index_html(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    client = make_client(dist)

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<div id=\"root\"></div>" in response.text


def test_api_route_is_not_intercepted_by_spa_fallback(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div>frontend</div>", encoding="utf-8")
    client = make_client(dist)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "frontend" not in response.text


def test_attachments_route_is_not_intercepted_by_spa_fallback(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div>frontend</div>", encoding="utf-8")
    client = make_client(dist)

    response = client.get("/api/attachments/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ATTACHMENT_NOT_FOUND"
    assert "frontend" not in response.text


def test_unknown_frontend_route_returns_index_html(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div>frontend</div>", encoding="utf-8")
    client = make_client(dist)

    response = client.get("/settings/agents/chat")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "frontend" in response.text
