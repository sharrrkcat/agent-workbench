import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from ai_workbench.core.schema.persona import COGITA_PERSONA_ID, USER_PERSONA_ID
from ai_workbench.core.schema.qq import QQ_TOOLS
from tests.model_fixtures import configure_model
from tests.tool_fixtures import ToolOpenAI, completion, ok, tool_call


GENERAL_TOOLS = {"base64_encode", "base64_decode", "web_search", "web_fetch"}
REMOVED_TOOLS = ("read_file", "fetch_url", "knowledge_search")


@pytest.fixture
def catalog_client(tmp_path):
    upstream = ToolOpenAI()
    app = create_app(root=tmp_path, use_memory=True, adapter_factory=upstream.factory)
    with TestClient(app) as client:
        yield client, upstream


def test_catalog_scopes_and_general_defaults(catalog_client):
    client, _ = catalog_client
    catalog = ok(client.get("/api/tools"))
    assert len(catalog) == 8
    assert {tool["name"] for tool in catalog if tool["scope"] == "general"} == GENERAL_TOOLS
    assert {tool["name"] for tool in catalog if tool["scope"] == "qqbot"} == set(QQ_TOOLS)
    assert all(tool["direct_callable"] == (tool["scope"] == "general") for tool in catalog)
    assert all(tool["parameters"]["type"] == "object" for tool in catalog)
    session = ok(client.post("/api/sessions", json={}))
    assert set(session["tools_allowed"]) == GENERAL_TOOLS
    for name in QQ_TOOLS:
        response = client.patch(f"/api/sessions/{session['session_id']}", json={"tools_allowed": [name]})
        assert response.status_code == 422 and response.json()["error"]["code"] == "TOOL_NOT_ALLOWED"
        response = client.post(f"/api/tools/{name}/call", json={"session_id": session["session_id"], "arguments": {}})
        assert response.status_code == 400 and response.json()["error"]["code"] == "TOOL_NOT_DIRECT_CALLABLE"
        response = client.post("/api/projects", json={"kind": "workspace", "name": "Tools",
            "agent_persona_id": COGITA_PERSONA_ID, "cogita_persona_id": USER_PERSONA_ID,
            "context_policy": {}, "harness_enabled": True, "tools_allowed": [name]})
        assert response.status_code == 422 and response.json()["error"]["code"] == "TOOL_NOT_ALLOWED"
    schema = ok(client.get("/openapi.json"))
    assert schema["components"]["schemas"]["ToolCatalogItem"]["properties"]["scope"]["enum"] == ["general", "qqbot"]
    assert "/api/tools/settings" not in schema["paths"]
    assert "HarnessSettings" not in schema["components"]["schemas"]


@pytest.mark.parametrize("name", REMOVED_TOOLS)
def test_removed_tools_are_unavailable_to_direct_and_model_calls(catalog_client, name):
    client, upstream = catalog_client
    configure_model(client, request_options={"streaming": False})
    session = ok(client.post("/api/sessions", json={"harness_enabled": True}))
    path = f"/api/sessions/{session['session_id']}"
    response = client.post(f"/api/tools/{name}/call", json={"session_id": session["session_id"], "arguments": {}})
    assert response.status_code == 404 and response.json()["error"]["code"] == "TOOL_NOT_FOUND"
    assert client.patch(path, json={"tools_allowed": [name]}).json()["error"]["code"] == "TOOL_NOT_FOUND"
    upstream.turns = [completion(tool_call(name, "{}")), completion(content="Tool unavailable")]
    response = ok(client.post(path + "/messages", json={"content": "use a tool"}))
    result = next(part for message in response["messages"] for part in message["parts"] if part["type"] == "tool_result")
    assert result["status"] == "error" and result["error_code"] == "TOOL_NOT_FOUND"
    assert all({tool["function"]["name"] for tool in call["tools"]} == GENERAL_TOOLS for call in upstream.calls)
    slash = f"/{name} example"
    response = ok(client.post(path + "/messages", json={"content": slash}))
    assert response["messages"][0]["parts"][0]["text"] == slash
    assert not any(part["type"] == "tool_call" for message in response["messages"] for part in message["parts"])
