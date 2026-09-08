import asyncio
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from ai_workbench.api.main import create_app
from ai_workbench.api.schemas.inference import ModelList
from scripts.openapi import build_document, render_document, resolve_ref
from tests.model_fixtures import MockOpenAI, configure_model


def validate_response(document, path, method, response):
    schema = document["paths"][path][method]["responses"][str(response.status_code)]["content"]["application/json"]["schema"]
    Draft202012Validator({**schema, "components": document["components"]},
                         format_checker=FormatChecker()).validate(response.json())


def test_document_endpoints_and_manual_request_schemas(tmp_path):
    with TestClient(create_app(use_memory=True, root=tmp_path)) as client:
        document = client.get("/openapi.json").json()
        assert document["openapi"] == "3.1.0"
        assert client.get("/docs").status_code == client.get("/redoc").status_code == 200
        for path, field in (("/v1/chat/completions", "messages"), ("/v1/embeddings", "input")):
            operation = document["paths"][path]["post"]
            body = operation["requestBody"]["content"]["application/json"]["schema"]
            schema = resolve_ref(document, body["$ref"])
            assert field in schema["required"] and schema["additionalProperties"] is False
            assert operation["security"] == [{"BearerAuth": []}, {"ApiKeyAuth": []}]
            assert "X-Request-Id" in operation["responses"]["200"]["headers"]
        assert "security" not in document["paths"]["/api/models/profiles"]["get"]
        content = document["paths"]["/v1/chat/completions"]["post"]["responses"]["200"]["content"]
        assert set(content) == {"application/json", "text/event-stream"}
        for example in content["text/event-stream"]["examples"].values():
            assert example["value"].endswith("data: [DONE]\n\n")
        assert "HTTPValidationError" not in json.dumps(document)


def test_inference_responses_match_contract_and_preserve_optional_fields(tmp_path):
    upstream = MockOpenAI()
    with TestClient(create_app(use_memory=True, root=tmp_path, adapter_factory=upstream.factory),
                    client=("127.0.0.1", 40000)) as client:
        configure_model(client, capabilities={"tools": True, "streaming": True})
        client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "test-key"})
        headers = {"Authorization": "Bearer test-key"}
        document = client.get("/openapi.json").json()
        models = client.get("/v1/models", headers=headers)
        validate_response(document, "/v1/models", "get", models)
        completion = client.post("/v1/chat/completions", headers=headers,
            json={"model": "local", "messages": [{"role": "user", "content": "Hello"}]})
        validate_response(document, "/v1/chat/completions", "post", completion)
        assert "tool_calls" not in completion.json()["choices"][0]["message"]
        invalid = client.post("/v1/chat/completions", headers=headers, json={"unexpected": "private-value"})
        assert invalid.status_code == 400
        validate_response(document, "/v1/chat/completions", "post", invalid)
        assert "private-value" not in invalid.text
        configure_model(client, kind="embedding", alias="embed")
        for encoding in ("float", "base64"):
            embedding = client.post("/v1/embeddings", headers=headers,
                json={"model": "embed", "input": ["Hello"], "encoding_format": encoding})
            validate_response(document, "/v1/embeddings", "post", embedding)
            assert "completion_tokens" not in embedding.json()["usage"]


def test_response_validation_failure_omits_internal_values(tmp_path):
    app = create_app(use_memory=True, root=tmp_path)

    @app.get("/api/invalid-output", response_model=ModelList)
    def invalid_output():
        return {"secret": "private-provider-key"}

    with TestClient(app) as client:
        response = client.get("/api/invalid-output")
        assert response.status_code == 500
        assert response.json() == {"error": {"code": "INTERNAL_ERROR", "message": "Response validation failed."}}
        assert "private-provider-key" not in response.text


def test_isolated_schema_generation_is_deterministic_and_skips_database_and_inference():
    with patch("ai_workbench.api.deps.init_db", side_effect=AssertionError("database access")), \
         patch("ai_workbench.core.models.manager.ModelManager.load", side_effect=AssertionError("model load")), \
         patch("httpx.AsyncClient.send", side_effect=AssertionError("network access")):
        first, first_routes = asyncio.run(build_document())
        second, second_routes = asyncio.run(build_document())
    assert first_routes == second_routes
    assert render_document(first) == render_document(second)
    assert render_document(first).endswith(b"\n")
