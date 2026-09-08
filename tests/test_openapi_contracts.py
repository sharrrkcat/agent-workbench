"""Contract gates and wire-format cases beyond the domain regression suites."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
import pytest

from ai_workbench.api.main import create_app
from ai_workbench.api.schemas.common import DeletedResponse
from ai_workbench.core.models.runtimes.schema import RuntimeJob
from ai_workbench.core.models.schema import ChatMessage
from scripts.openapi import (
    OPAQUE_SCHEMA_PATHS, build_document, check_document, check_route_contracts,
    http_operations, main, render_document, resolve_ref,
)
from tests.model_fixtures import MockOpenAI, configure_model


@pytest.fixture(scope="module")
def contract():
    return asyncio.run(build_document())


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "data/attachments"))
    upstream = MockOpenAI()
    app = create_app(use_memory=True, root=tmp_path, adapter_factory=upstream.factory)
    with TestClient(app, client=("127.0.0.1", 41000)) as client:
        yield client, upstream


def test_complete_contract_and_runtime_models(api):
    client, _ = api
    app = client.app
    document = client.get("/openapi.json").json()
    assert check_document(document, http_operations(app)) == []
    assert check_route_contracts(app, document) == []
    for route in app.routes:
        if getattr(route, "response_model", None) is not None and route.include_in_schema:
            for method in route.methods:
                assert document["paths"][route.path_format][method.lower()]["operationId"] == route.unique_id
    assert client.get("/docs").status_code == client.get("/redoc").status_code == 200


@pytest.mark.parametrize("defect", ["route", "operation_id", "reference", "response", "request", "boolean_schema", "open_field", "tag"])
def test_contract_gate_rejects_incomplete_or_unstructured_contracts(contract, defect):
    original, expected = contract
    document = deepcopy(original)
    operation = document["paths"]["/api/models/providers"]["get"]
    expected_error = ""
    if defect == "route":
        del document["paths"]["/api/models/providers"]["get"]
        expected_error = "Route coverage differs"
    elif defect == "operation_id":
        operation["operationId"] = document["paths"]["/api/models/providers"]["post"]["operationId"]
        expected_error = "duplicate operationId"
    elif defect == "reference":
        operation["responses"]["200"]["content"]["application/json"]["schema"] = {"$ref": "#/components/schemas/Missing"}
        expected_error = "unresolved reference"
    elif defect == "response":
        operation["responses"]["200"]["content"]["application/json"]["schema"] = {"title": "Unspecified"}
        expected_error = "unstructured JSON payload"
    elif defect == "request":
        document["paths"]["/api/personas/{persona_id}"]["patch"]["requestBody"]["content"]["application/json"]["schema"] = {}
        expected_error = "unstructured JSON payload"
    elif defect == "boolean_schema":
        operation["responses"]["200"]["content"]["application/json"]["schema"] = True
        expected_error = "unstructured JSON payload"
    elif defect == "open_field":
        document["components"]["schemas"]["ProviderResponse"]["properties"]["unknown"] = {"$ref": "#/components/schemas/JsonValue-Output"}
        expected_error = "undocumented arbitrary JSON field"
    else:
        operation.pop("tags")
        expected_error = "missing tag or summary"
    assert any(expected_error in error for error in check_document(document, expected))


def test_contract_gate_rejects_stale_json_exceptions(contract, monkeypatch):
    document, expected = contract
    monkeypatch.setitem(OPAQUE_SCHEMA_PATHS, "components/schemas/Missing/properties/data", "Removed field")
    assert any("Stale open JSON exception" in error for error in check_document(document, expected))


def test_hidden_routes_and_documented_only_response_models_fail_gate(api):
    client, _ = api
    app = client.app

    @app.get("/api/hidden-operation", include_in_schema=False)
    def hidden():
        return {"deleted": True}

    @app.get("/api/unchecked-response", responses={200: {"model": DeletedResponse}})
    def unchecked():
        return {"deleted": True}

    app.openapi_schema = None
    document = app.openapi()
    assert any("Route coverage differs" in error for error in check_document(document, http_operations(app)))
    assert any("/api/unchecked-response" in error for error in check_route_contracts(app, document))
    del document["paths"]["/v1/embeddings"]["post"]["requestBody"]
    del document["paths"]["/api/sessions"]["get"]["responses"]["200"]["content"]
    errors = check_route_contracts(app, document)
    assert any("request body is undocumented" in error for error in errors)
    assert any("JSON success schema is missing" in error for error in errors)


def test_cli_exports_are_isolated_deterministic_and_equal_to_served_schema(tmp_path, capsys):
    first, second = tmp_path / "one.json", tmp_path / "nested/two.json"
    with patch("ai_workbench.api.deps.init_db", side_effect=AssertionError("real database access")), \
         patch("ai_workbench.core.models.manager.ModelManager.load", side_effect=AssertionError("model load")), \
         patch("httpx.AsyncClient.send", side_effect=AssertionError("network access")):
        assert main(["export", "--output", str(first)]) == 0
        assert main(["export", "--output", str(second)]) == 0
        with TestClient(create_app(use_memory=True, root=tmp_path / "served")) as client:
            served = client.get("/openapi.json").json()
    assert first.read_bytes() == second.read_bytes() == render_document(served)
    assert first.read_bytes().endswith(b"\n")
    assert str(tmp_path) not in first.read_text(encoding="utf-8")
    assert "Exported" in capsys.readouterr().out


def test_model_kinds_runtime_options_and_secret_patch_semantics(api):
    client, _ = api
    provider = client.post("/api/models/providers", json={
        "name": "Provider", "base_url": "http://provider.test/v1", "api_key": "private-provider-value",
    }).json()
    provider_path = f"/api/models/providers/{provider['id']}"
    assert provider["has_api_key"] and "api_key" not in provider
    assert client.patch(provider_path, json={"name": "Renamed"}).json()["has_api_key"]
    assert not client.patch(provider_path, json={"api_key": ""}).json()["has_api_key"]
    assert client.patch(provider_path, json={"api_key": None}).status_code == 422

    for kind in ("llm", "embedding", "reranker", "image_embedding", "vision"):
        result = client.post("/api/models/profiles", json={"name": kind, "alias": kind, "kind": kind, "model_ref": "fixture"})
        assert result.status_code == 200, result.text
        assert result.json()["runtime_options"] == {}
        if kind == "llm":
            assert result.json()["parameters"] == {}
    for variant, layers in (("cpu", 0), ("cuda", "auto"), ("vulkan", 3)):
        result = client.post("/api/models/profiles", json={"name": variant, "alias": variant, "kind": "llm",
            "model_ref": "llms/fixture.gguf", "runtime_id": "llama-server", "runtime_variant": variant,
            "runtime_options": {"gpu_layers": layers}})
        assert result.status_code == 200, result.text
        assert result.json()["runtime_options"]["gpu_layers"] == layers
    worker = client.post("/api/models/profiles", json={"name": "Worker", "alias": "worker", "kind": "embedding",
        "model_ref": "embeddings/fixture", "runtime_id": "python-worker", "runtime_variant": "torch-cpu"})
    assert worker.status_code == 200 and worker.json()["runtime_options"]["device"] == "cpu"
    assert client.get("/api/models/runtimes/catalog").status_code == 200

    settings = "/api/models/settings"
    assert client.patch(settings, json={"external_api_key": "service-private-value"}).json()["has_external_api_key"]
    assert client.patch(settings, json={"max_request_mb": 2}).json()["has_external_api_key"]
    assert not client.patch(settings, json={"external_api_key": ""}).json()["has_external_api_key"]


def test_external_response_validation_failure_is_sanitized_and_logged(api, monkeypatch):
    client, _ = api
    configure_model(client)
    client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "fixture-key"})
    state = client.app.state.runtime_state

    async def invalid_completion(*args, **kwargs):
        return SimpleNamespace(message=ChatMessage(role="assistant", content="private-output-value"),
                               finish_reason="private-invalid-reason", usage=None)

    monkeypatch.setattr(state.model_manager, "chat", invalid_completion)
    response = client.post("/v1/chat/completions", headers={"x-api-key": "fixture-key"},
        json={"model": "local", "messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "INTERNAL_ERROR", "message": "Response validation failed."}}
    log = (state.repo_root / "data/logs/inference/inference.jsonl").read_text(encoding="utf-8")
    assert response.headers["x-request-id"] in log and "INTERNAL_ERROR" in log
    assert "private-output-value" not in response.text + log
    assert "private-invalid-reason" not in response.text + log


def test_message_parts_preserve_omitted_fields_json_values_and_microseconds(api):
    client, _ = api
    session = client.post("/api/sessions", json={}).json()
    session_id = session["session_id"]
    assert session["generation"] == {}
    assert "temperature" in session["effective"]["generation"]
    state = client.app.state.runtime_state
    contents = [
        {"type": "text", "text": "answer"},
        {"type": "reasoning", "text": "processing"},
        {"type": "json", "data": {"null": None, "values": [True, 1, 0.5, "文字"]}},
        {"type": "file", "mode": "inline_text", "content": "file content"},
        {"type": "file", "mode": "attachment_ref", "attachment_id": "fixture.txt"},
        {"type": "image", "attachment_id": "fixture.png"},
        {"type": "audio", "source": "url", "url": "https://example.test/audio.wav", "mime_type": "audio/wav"},
        {"type": "video", "source": "url", "url": "https://example.test/video.mp4", "mime_type": "video/mp4"},
        {"type": "media_group", "items": [{"attachment_id": "fixture.png"}]},
        {"type": "notice", "text": "notice"},
        {"type": "error", "message": "error"},
        {"type": "tool_call", "tool_call_id": "call-1", "tool_name": "base64_encode", "arguments": {"value": "hello"}},
    ]
    message = state.messages.add_message(session_id, "assistant", parts=contents,
        metadata={"fixture": {"null": None, "list": [True, 1]}})
    frozen = datetime(2026, 9, 8, 1, 2, 3, 120034, tzinfo=timezone.utc)
    state.messages.update_message(message.model_copy(update={"created_at": frozen}))
    state.messages.add_message(session_id, "tool", parts=[{
        "type": "tool_result", "tool_call_id": "call-1", "tool_name": "base64_encode", "status": "success",
    }])
    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    assert messages[0]["created_at"] == "2026-09-08T01:02:03.120034Z"
    assert "run" not in messages[0] and "run_steps" not in messages[0]
    assert messages[0]["metadata"] == {"fixture": {"null": None, "list": [True, 1]}}
    assert messages[0]["parts"][2]["data"] == contents[2]["data"]
    assert "filename" not in messages[0]["parts"][3]
    assert "data" not in messages[1]["parts"][0]
    assert client.get(f"/api/sessions/{session_id}/timeline").status_code == 200


def test_chat_event_variants_and_private_state(api):
    client, upstream = api
    configure_model(client, capabilities={"streaming": True})
    client.patch("/api/settings/general", json={"persist_streaming_message_deltas": True})
    session_id = client.post("/api/sessions", json={}).json()["session_id"]
    reply = client.post(f"/api/sessions/{session_id}/messages", json={"content": "Hello"}).json()
    run = reply["run"]
    assert run["status"] == "DONE"
    assert "config_snapshot_json" not in run and "harness_state_json" not in run
    state = client.app.state.runtime_state
    assert state.runs.get_config_snapshot(run["run_id"])["system_prompt"]
    events = client.get(f"/api/runs/{run['run_id']}/events").json()
    assert {"run_started", "message_started", "message_delta", "message_completed", "run_completed"} <= {event["type"] for event in events}
    assert all("config_snapshot_json" not in event["payload"].get("run", {}) for event in events)
    cancelled = client.post(f"/api/runs/{run['run_id']}/cancel").json()
    assert cancelled["cancelled"] is False and "task_cancelled" not in cancelled
    upstream.failure = 500
    failed = client.post(f"/api/sessions/{session_id}/messages", json={"content": "Fail this request"}).json()
    assert failed["run"]["status"] == "FAILED"
    timeline = client.get(f"/api/sessions/{session_id}/timeline").json()
    notification = next(item["notification"] for item in timeline if item["kind"] == "notification")
    assert notification["created_at"].endswith("+00:00")
    assert "steps" not in notification["run"]
    assert client.post(f"/api/sessions/{session_id}/notifications/{notification['id']}/dismiss").json()["dismissed"]


def test_attachment_multipart_range_and_empty_416(api):
    client, _ = api
    response = client.post("/api/attachments", files={"file": ("fixture.txt", b"hello world!", "text/plain")})
    assert response.status_code == 200
    attachment = response.json()
    assert "data_url" not in attachment and "metadata" not in attachment
    url = attachment["url"]
    for header, expected in ((None, b"hello world!"), ("bytes=0-4", b"hello"), ("bytes=-6", b"world!")):
        response = client.get(url, headers={"Range": header} if header else {})
        assert response.status_code == (206 if header else 200)
        assert response.content == expected
        assert response.headers["accept-ranges"] == "bytes"
        assert int(response.headers["content-length"]) == len(expected)
        if header:
            assert response.headers["content-range"].endswith("/12")
    response = client.get(url, headers={"Range": "bytes=100-200"})
    assert response.status_code == 416 and response.content == b""
    assert response.headers["content-range"] == "bytes */12"
    assert client.post("/api/attachments", files=[("file", ("one.txt", b"1")), ("file", ("two.txt", b"2"))]).status_code == 422
    assert client.delete(url).json()["deleted"]


def test_runtime_jobs_202_and_storage_diagnostics(api, monkeypatch):
    client, _ = api
    supervisor = client.app.state.runtime_state.runtime_supervisor

    async def submit(runtime_id, variant, operation):
        job = RuntimeJob(runtime_id=runtime_id, variant=variant, version="fixture", operation=operation,
            log_path="private/internal.log")
        supervisor.store.save_job(job)
        return job

    async def submit_cache(mode):
        job = RuntimeJob(operation="cache_" + mode, result={"before": None, "after": None}, log_path="private/cache.log")
        supervisor.store.save_job(job)
        return job

    monkeypatch.setattr(supervisor, "submit", submit)
    monkeypatch.setattr(supervisor, "submit_cache", submit_cache)
    for operation in ("install", "uninstall"):
        response = client.post(f"/api/models/runtimes/llama-server/cpu/{operation}")
        assert response.status_code == 202 and "log_path" not in response.json()
        assert response.json()["finished_at"] is None
        assert client.get(f"/api/models/runtimes/jobs/{response.json()['id']}").status_code == 200
    for mode in ("prune", "clean"):
        response = client.post("/api/models/runtimes/cache/cleanup", json={"mode": mode})
        assert response.status_code == 202
        assert response.json()["runtime_id"] is None
        assert response.json()["result"] == {"before": None, "after": None}
        assert "log_path" not in response.json()
    assert client.get("/api/models/runtimes/jobs").status_code == 200
    for job in supervisor.store.jobs():
        supervisor.store.save_job(job.model_copy(update={"state": "completed"}))
        assert client.get(f"/api/models/runtimes/jobs/{job.id}/log").json() == {"text": ""}
        assert client.post(f"/api/models/runtimes/jobs/{job.id}/cancel").json()["state"] == "completed"
    assert client.get("/api/models/runtimes/storage").status_code == 200
    assert client.get("/api/runtime/resources").status_code == 200
    assert client.get("/api/health/details").json()["status"] == "degraded"

    def unavailable():
        raise RuntimeError("Fixture unavailable")

    monkeypatch.setattr(client.app.state.runtime_state.runtime_resources, "resources", unavailable)
    assert client.get("/api/runtime/resources").json()["updated_at"] is None


def test_documented_patch_types_distinguish_omission_and_null(api):
    client, _ = api
    document = client.get("/openapi.json").json()
    cases = [
        ("/api/settings/general", {"group_transcript_system_instruction": None}, {"show_full_processing": None}),
        ("/api/models/settings", {"default_model_profile_id": None}, {"max_request_mb": None}),
        ("/api/knowledge/settings", {"default_min_score": None}, {"default_chunk_size": None}),
        ("/api/worldbook/settings", {}, {"worldbook_enabled": None}),
    ]
    for path, valid, invalid in cases:
        schema = document["paths"][path]["patch"]["requestBody"]["content"]["application/json"]["schema"]
        validator = Draft202012Validator({**schema, "components": document["components"]}, format_checker=FormatChecker())
        assert validator.is_valid({}) and validator.is_valid(valid)
        assert not validator.is_valid(invalid)
        assert client.patch(path, json=valid).status_code == 200
        assert client.patch(path, json=invalid).status_code == 422
        assert client.patch(path, json={"unknown": True}).status_code == 422
    properties = resolve_ref(document, document["paths"]["/api/models/providers"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["items"]["$ref"])["properties"]
    assert "api_key" not in properties


def test_management_reads_updates_and_deletions_keep_response_shapes(api):
    client, _ = api
    for path in ("/api/health", "/api/data/storage-stats", "/api/models/inventory",
                 "/api/models/runtime/settings", "/api/models/runtimes", "/api/models/runtimes/llama-server/cpu",
                 "/api/sessions", "/api/tools", "/api/tools/settings", "/api/personas"):
        assert client.get(path).status_code == 200
    assert client.patch("/api/models/runtime/settings", json={"http_proxy": ""}).json()["http_proxy"] is None
    assert client.patch("/api/tools/settings", json={"searxng_base_url": None}).status_code == 200
    assert client.post("/api/data/attachments/scan-orphans").json()["orphans"] == []
    assert client.post("/api/data/attachments/cleanup-orphans", json={"confirm": True}).json()["errors"] == []

    persona = client.post("/api/personas", json={"name": "Fixture persona"}).json()
    persona_path = f"/api/personas/{persona['id']}"
    assert client.get(persona_path).json()["name"] == "Fixture persona"
    assert client.patch(persona_path, json={"system_prompt": ""}).json()["system_prompt"] == ""
    for resource, field in (("knowledge-bases", "knowledge_base_ids"), ("worldbooks", "worldbook_ids")):
        assert client.get(persona_path + "/" + resource).json()[field] == []
        assert client.patch(persona_path + "/" + resource, json={field: []}).json()[field] == []
    session = client.post("/api/sessions", json={}).json()
    session_path = f"/api/sessions/{session['session_id']}"
    assert client.get(session_path).status_code == 200
    assert client.get(session_path + "/personas").status_code == 200
    assert client.patch(session_path + "/personas", json={
        "personas": [{"persona_id": persona["id"]}], "current_persona_id": persona["id"],
    }).json()["current_persona_id"] == persona["id"]
    assert client.delete(session_path).json()["deleted"]
    assert client.delete(persona_path).json()["deleted"]

    book = client.post("/api/worldbooks", json={"name": "Fixture book"}).json()
    book_path = f"/api/worldbooks/{book['id']}"
    assert client.get(book_path).status_code == 200
    assert client.patch(book_path, json={"description": None}).json()["description"] == ""
    assert client.get(book_path + "/entries").json() == []
    entry = client.post(book_path + "/entries", json={"name": "Entry", "content": "Text", "activation_mode": "always"}).json()
    assert client.patch(book_path + "/entries/reorder", json={"entry_ids": [entry["id"]]}).status_code == 200
    assert client.delete(f"/api/worldbook-entries/{entry['id']}").json()["deleted"]
    assert client.delete(book_path).json()["deleted"]

    model = configure_model(client)
    model_path = f"/api/models/profiles/{model['id']}"
    provider_path = f"/api/models/providers/{model['provider_profile_id']}"
    assert client.get(provider_path).status_code == 200
    assert client.get(provider_path + "/models").status_code == 200
    assert client.get(model_path).status_code == 200
    assert client.get(model_path + "/log").status_code == 200
    assert client.post(model_path + "/health").status_code == 200
    assert client.post(model_path + "/load").status_code == 200
    assert client.post(model_path + "/unload").json()["error"]["code"] == "UNLOAD_UNSUPPORTED"
    client.patch("/api/models/settings", json={"default_model_profile_id": None})
    assert client.delete(model_path).json()["deleted"]
    assert client.delete(provider_path).json()["deleted"]


@pytest.mark.parametrize("use_memory", [True, False], ids=["memory", "sqlite"])
def test_resource_partial_reindex_and_retrieval_diagnostics(tmp_path, monkeypatch, use_memory):
    from ai_workbench.core.knowledge_indexing import KnowledgeIndexError

    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    upstream = MockOpenAI()
    app = create_app(use_memory=use_memory, root=tmp_path, database_url=f"sqlite:///{tmp_path / 'contract.db'}",
                     adapter_factory=upstream.factory)
    with TestClient(app) as client:
        model = configure_model(client, kind="embedding", alias="embed")
        base = client.post("/api/knowledge/bases", json={"name": "Fixture", "embedding_model_profile_id": model["id"]}).json()
        base_path = f"/api/knowledge/bases/{base['id']}"
        assert client.get(base_path).status_code == 200
        assert client.patch(base_path, json={"aliases_text": None, "final_top_k_override": None}).json()["aliases_text"] == ""
        assert client.get(base_path + "/sources").json() == []
        first = client.post(base_path + "/sources", json={"title": "First", "text": "Fixture evidence."}).json()
        second = client.post(base_path + "/sources", json={"title": "Second", "text": "More fixture evidence."}).json()
        source_path = f"/api/knowledge/sources/{first['source_id']}"
        assert client.get(source_path).status_code == 200
        assert client.get(source_path + "/preview").json()["content"] == "Fixture evidence."
        chunks = client.get(source_path + "/chunks").json()["chunks"]
        if not use_memory:
            assert client.get(f"/api/knowledge/chunks/{chunks[0]['chunk_id']}").json()["content"] == chunks[0]["content"]
        client.patch("/api/knowledge/settings", json={"reranker_enabled": True})
        search = {"query": "fixture", "knowledge_base_ids": [base["id"]]}
        assert "debug" not in client.post("/api/knowledge/search", json=search).json()
        searched = client.post("/api/knowledge/search", json={**search, "debug": True}).json()
        assert searched["results"] and searched["metadata"]["rerank_fallback"]
        assert searched["debug"]["reranker_failed"]
        reindex = app.state.runtime_state.knowledge_service.reindex

        async def partial_reindex(source_id):
            if source_id == first["source_id"]:
                raise KnowledgeIndexError("KNOWLEDGE_SOURCE_NOT_READABLE", "Fixture source unavailable")
            return await reindex(source_id)

        monkeypatch.setattr(app.state.runtime_state.knowledge_service, "reindex", partial_reindex)
        result = client.post(base_path + "/reindex").json()
        results = {source["source_id"]: source for source in result["sources"]}
        assert results[first["source_id"]]["status"] == "failed"
        assert "indexed_at" not in results[first["source_id"]]
        assert results[second["source_id"]]["status"] == "indexed"
        assert client.delete(source_path).json()["deleted"]
        assert client.delete(base_path).json()["deleted"]
