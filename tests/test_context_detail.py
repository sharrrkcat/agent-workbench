import json
import asyncio
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy.exc import OperationalError

from ai_workbench.core.attachments import resolve_attachment_uri
from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.context_snapshot import capture_context, context_detail, omit_context_images
from ai_workbench.core.models.schema import ChatRequest, ExternalConnection
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.stores import MessageStore, RunStore
from ai_workbench.core.schema.persona import COGITA_PERSONA_ID, USER_PERSONA_ID
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from tests.model_fixtures import configure_model
from tests.test_projects import workspace, child
from tests.test_chat_presentation import presentation_client, configure, send
from tests.tool_fixtures import completion, ok, tool_call
from tests.test_vision_input import profile as local_profile


def details(client, run):
    return [ok(client.get(f"/api/runs/{run['run_id']}/steps/{step['step_id']}/context"))
            for step in run["steps"] if step["kind"] == "model"]


@pytest.mark.parametrize("harness", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_context_captures_the_actual_request_and_stays_private(presentation_client, harness, streaming):
    client, upstream = presentation_client
    session = configure(client, harness=harness, streaming=streaming)
    ok(client.patch(f"/api/sessions/{session['session_id']}", json={"generation": {"temperature": 0}, "reasoning": False}))
    upstream.turns = ([completion(tool_call(), content="working")] if harness else []) + [completion(content="final output")]
    result = send(client, session, "PRIVATE_INPUT 中文😀")
    assert result["success"], result
    snapshots = details(client, result["run"])
    assert len(snapshots) == len(upstream.calls)
    for snapshot, request in zip(snapshots, upstream.calls):
        assert snapshot["request"] == request
        assert snapshot["request"]["temperature"] == 0
        assert snapshot["request"]["reasoning_effort"] == "none"
        assert snapshot["request"]["max_tokens"] == 4096
        current = next(source for source in snapshot["sources"] if source["kind"] == "current_input")
        assert current["text"] == "PRIVATE_INPUT 中文😀"
        assert current["char_count"] == len(current["text"])
        assert "final output" not in json.dumps(snapshot)
    if harness:
        assert [s["kind"] for s in snapshots[-1]["sources"] if s["kind"].startswith("tool_")] == ["tool_call", "tool_result"]
        assert "tools" not in {s["kind"] for s in snapshots[0]["sources"] if s["parent_id"] is not None}
    run = ok(client.get(f"/api/runs/{result['run']['run_id']}"))
    assert "PRIVATE_INPUT" not in json.dumps(run)
    for step in run["steps"]:
        if step["kind"] == "model":
            assert step["metadata"]["context"]["available"] is True
    state = client.app.state.runtime_state
    events = ok(client.get(f"/api/runs/{run['run_id']}/events"))["items"]
    assert all("request" not in event["payload"].get("step", {}) for event in events)
    with pytest.raises(ValueError, match="existing snapshot"):
        state.runs.save_context_snapshot(snapshots[0]["step_id"], state.runs.get_context_snapshot(snapshots[0]["step_id"]))


def test_context_endpoint_checks_ownership_and_missing_snapshots(presentation_client):
    client, _ = presentation_client
    session = configure(client, harness=False)
    result = send(client, session)
    snapshot = details(client, result["run"])[0]
    other = send(client, session)
    for run_id, step_id in [(other["run"]["run_id"], snapshot["step_id"]), (result["run"]["run_id"], "missing")]:
        response = client.get(f"/api/runs/{run_id}/steps/{step_id}/context")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CONTEXT_NOT_FOUND"
    ok(client.delete(f"/api/runs/{result['run']['run_id']}"))
    assert client.get(f"/api/runs/{result['run']['run_id']}/steps/{snapshot['step_id']}/context").status_code == 404


def test_sources_preserve_workspace_order_unicode_and_selection(presentation_client, monkeypatch):
    client, upstream = presentation_client
    configure_model(client, request_options={"streaming": False})
    embedding = configure_model(client, kind="embedding", alias="embedding")
    base = ok(client.post("/api/knowledge/bases", json={"name": "Guides", "embedding_model_profile_id": embedding["id"]}))
    ok(client.patch(f"/api/personas/{COGITA_PERSONA_ID}", json={"system_prompt": "  AGENT😀 private  "}))
    ok(client.patch(f"/api/personas/{USER_PERSONA_ID}", json={"system_prompt": "用户背景😀"}))
    project = workspace(client, system_prompt="PROJECT private", knowledge_base_ids=[base["id"]],
                        context_policy={"max_messages": 2, "max_chars": 16})
    session = child(client, project)
    state = client.app.state.runtime_state
    async def search(**_):
        return {"results": [{"chunk_id": "chunk-1", "source_id": "source-1", "knowledge_base_id": base["id"],
                             "title": "guide.md", "content": "KNOWLEDGE 中文😀"}], "debug": {}}
    monkeypatch.setattr(state.knowledge_service, "search", search)
    for index, (role, content) in enumerate([("user", "old"), ("assistant", "middle"), ("user", "long" * 20), ("assistant", "recent")]):
        state.messages.add_message(session["session_id"], role, content, message_id=f"history-{index}")
    state.messages.add_message(session["session_id"], "assistant", "skip", metadata={"incomplete": True})
    result = send(client, session, "current😀")
    assert result["success"], result
    snapshot = details(client, result["run"])[0]
    assert snapshot["request"] == upstream.calls[-1]
    sources = {source["kind"]: source for source in snapshot["sources"]}
    assert sources["agent_persona"]["text"] == "AGENT😀 private"
    assert sources["project_prompt"]["text"] == "PROJECT private"
    assert sources["cogita_persona"]["text"].endswith("用户背景😀\n</user_persona>")
    assert "KNOWLEDGE 中文😀" in sources["knowledge_snippet"]["text"]
    assert sources["knowledge_snippet"]["citation"] == "K1"
    assert sources["knowledge_snippet"]["source_id"] == "source-1"
    assert [sources[kind]["start"] for kind in ("agent_persona", "project_prompt", "cogita_persona", "knowledge")] == sorted(
        sources[kind]["start"] for kind in ("agent_persona", "project_prompt", "cogita_persona", "knowledge"))
    assert sources["history"]["text"] == "recent"
    assert {item["reason"] for item in snapshot["exclusions"]} == {"ineligible_history", "message_limit", "character_limit"}
    assert all(source["char_count"] == len(source["text"]) for source in snapshot["sources"])
    ok(client.patch(f"/api/personas/{COGITA_PERSONA_ID}", json={"system_prompt": "CHANGED"}))
    ok(client.patch(f"/api/projects/{project['id']}", json={"system_prompt": "CHANGED"}))
    assert details(client, result["run"])[0] == snapshot


def test_included_attachments_are_retained_until_the_last_snapshot_is_deleted(presentation_client, monkeypatch, tmp_path):
    client, upstream = presentation_client
    monkeypatch.setenv("COGITA_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    session = configure(client, harness=False, streaming=False)
    data = BytesIO()
    Image.new("RGB", (8, 6), "red").save(data, format="PNG")
    image = ok(client.post("/api/attachments", files={"file": ("image.png", data.getvalue(), "image/png")}))
    file = ok(client.post("/api/attachments", files={"file": ("note.txt", "文件内容😀".encode(), "text/plain")}))
    ok(client.patch("/api/settings/general", json={"send_text_file_attachments_to_llm": True}))
    result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "看看😀", "attachments": [image, file]}))
    assert result["success"], result
    snapshot = details(client, result["run"])[0]
    assert set(snapshot["attachment_ids"]) == {image["uri"].split("/")[-1], file["uri"].split("/")[-1]}
    assert "base64" not in json.dumps(snapshot)
    assert next(source for source in snapshot["sources"] if (source.get("attachment") or {}).get("type") == "image")["char_count"] == 0
    assert any("文件内容😀" in source["text"] for source in snapshot["sources"] if source["kind"] == "attachment")
    assert upstream.calls[-1]["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    follow_up = send(client, session, "follow up")
    user_id = result["run"]["metadata"]["input_message_id"]
    ok(client.delete(f"/api/messages/{user_id}"))
    assert resolve_attachment_uri(image["uri"]).exists()
    assert resolve_attachment_uri(file["uri"]).exists()
    assert client.delete(f"/api/attachments/{image['uri'].split('/')[-1]}").status_code == 409
    assert ok(client.post("/api/data/attachments/scan-orphans"))["orphans"] == []
    assert ok(client.post("/api/data/attachments/cleanup-orphans", json={"confirm": True}))["deleted_count"] == 0
    ok(client.delete(f"/api/runs/{follow_up['run']['run_id']}"))
    assert not resolve_attachment_uri(image["uri"]).exists()
    assert not resolve_attachment_uri(file["uri"]).exists()


def test_failed_calls_keep_context_and_failed_persistence_never_sends(presentation_client, monkeypatch):
    client, upstream = presentation_client
    session = configure(client, harness=False)
    upstream.stream_chunks = [{"refusal": "refused"}]
    result = send(client, session)
    assert result["run"]["status"] == "FAILED"
    assert len(details(client, result["run"])) == 1
    calls_before = len(upstream.calls)
    def fail(*_):
        raise OperationalError("INSERT private", {"body": "PRIVATE_BOUND_INPUT"}, RuntimeError("disk full"))
    monkeypatch.setattr(client.app.state.runtime_state.runs, "save_context_snapshot", fail)
    result = send(client, session)
    assert result["run"]["error_code"] == "CONTEXT_SAVE_FAILED"
    assert len(upstream.calls) == calls_before
    assert "PRIVATE_BOUND_INPUT" not in json.dumps(result)
    assert all("context" not in step["metadata"] for step in result["run"]["steps"])


def test_context_migration_adds_only_private_storage(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.HISTORY_LIMITS_REVISION)
    before = migrations.inspect_schema(engine)
    files = [tmp_path / folder / "keep" for folder in ("models", "attachments", "runtimes")]
    for file in files:
        file.parent.mkdir()
        file.write_text("keep")
    migrations.upgrade(engine)
    after = migrations.inspect_schema(engine)
    assert set(after.columns["runsteprecord"]) - set(before.columns["runsteprecord"]) == {"context_snapshot_json"}
    assert after.tables == before.tables
    assert all(file.read_text() == "keep" for file in files)


@pytest.mark.parametrize("engine", ["llama-server", "transformers"])
@pytest.mark.parametrize("streaming", [False, True])
def test_local_capture_uses_the_translated_transport_body(engine, streaming):
    from tests.tool_fixtures import ToolOpenAI
    async def scenario():
        upstream = ToolOpenAI(completion(content="answer"))
        adapter = upstream.factory(ExternalConnection(base_url="http://local.test/v1", api_key="private-local-key"))
        model = local_profile(engine).model_copy(update={"model_ref": "managed", "parameters": {"temperature": 0.7, "top_p": 0.9}})
        messages, runs = MessageStore(), RunStore()
        built = ContextBuilder(messages).build("s", "hello")
        run = runs.create_run("chat", COGITA_PERSONA_ID, "s")
        step = runs.create_step(run.run_id, "model")
        request = ChatRequest(model="local", messages=built.messages, reasoning=False, temperature=0, stream=streaming)
        capture = capture_context(runs, step.step_id, built.trace, model, ContextPolicy())
        try:
            if streaming:
                async for _ in adapter.chat_stream(model, request, capture=capture):
                    pass
            else:
                await adapter.chat(model, request, capture=capture)
        finally:
            await adapter.close()
        snapshot = runs.get_context_snapshot(step.step_id)
        assert snapshot.request.model_dump(mode="json", exclude_unset=True) == upstream.calls[0]
        assert snapshot.request.model == "managed" and snapshot.request.temperature == 0
        assert snapshot.request.top_p == 0.9 and snapshot.request.chat_template_kwargs.enable_thinking is False
        assert "reasoning_effort" not in upstream.calls[0]
        assert ("cogita_request_options" in upstream.calls[0]) == (engine == "transformers")
        assert "private-local-key" not in snapshot.model_dump_json()
    asyncio.run(scenario())


def test_ignored_images_remap_sources_and_do_not_retain_attachments():
    messages, runs = MessageStore(), RunStore()
    image = lambda name: {"type": "image", "uri": f"local://attachments/{name}.png"}
    messages.add_message("s", "user", "", metadata={"attachments": [image("old")]})
    messages.add_message("s", "assistant", "retained")
    current = messages.add_message("s", "user", "current", metadata={"attachments": [image("new")]})
    built = ContextBuilder(messages).build("s", "current", current_message_id=current.message_id)
    prepared = omit_context_images(built.messages, built.trace)
    assert prepared == [{"role": "assistant", "content": "retained"}, {"role": "user", "content": "current"}]
    run = runs.create_run("chat", COGITA_PERSONA_ID, "s")
    step = runs.create_step(run.run_id, "model")
    capture_context(runs, step.step_id, built.trace, local_profile(), ContextPolicy())(
        {"model": "managed", "stream": False, "messages": prepared})
    snapshot = context_detail(runs.get_context_snapshot(step.step_id))
    assert snapshot.attachment_ids == []
    assert [source.message_index for source in snapshot.sources] == [0, 1]
    assert [source.text for source in snapshot.sources] == ["retained", "current"]
    assert [(item.reason, item.reference_id) for item in snapshot.exclusions] == [
        ("images_unsupported", "old.png"), ("images_unsupported", "new.png")]
