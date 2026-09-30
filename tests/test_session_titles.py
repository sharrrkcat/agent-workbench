import asyncio

import pytest
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from tests.model_fixtures import MockOpenAI, configure_model
from tests.test_projects import workspace


@pytest.fixture(params=[True, False], ids=["memory", "sqlite"])
def environment(tmp_path, request):
    upstream = MockOpenAI()
    app = create_app(root=tmp_path, use_memory=request.param,
                     database_url=f"sqlite:///{tmp_path / 'app.db'}", adapter_factory=upstream.factory)
    with TestClient(app) as client:
        configure_model(client)
        yield client, upstream, app.state.runtime_state


def create_session(client, kind="ordinary", **values):
    path = "/api/sessions" if kind == "ordinary" else f"/api/projects/{workspace(client)['id']}/sessions"
    response = client.post(path, json=values)
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def send(client, session_id, text, attachments=None):
    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": text, "attachments": attachments or []})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("kind", ["ordinary", "workspace"])
def test_input_titles_without_auxiliary_and_with_switch_off(environment, kind):
    client, upstream, _ = environment
    for enabled in (True, False):
        client.patch("/api/settings/general", json={"auto_generate_session_titles": enabled}).raise_for_status()
        for text, expected in [
            ("  你好\n  世界  ", "你好 世界"),
            ("abcdefghijklmno", "abcdefghijklmno"),
            ("abcdefghijklmnop", "abcdefghijklmno…"),
            ("这是一个包含中文字符的测试会话标题", "这是一个包含中文字符的测试会话标题"[:15] + "…"),
            ("😀" * 16, "😀" * 15 + "…"),
        ]:
            session_id = create_session(client, kind)
            send(client, session_id, text)
            session = client.get(f"/api/sessions/{session_id}").json()
            assert session["title"] == expected
            assert session["title_generation_metadata"]["source"] == "input_excerpt"
            send(client, session_id, "A later message must not rename the session")
            assert client.get(f"/api/sessions/{session_id}").json()["title"] == expected
    assert len(upstream.calls) == 20, "Missing auxiliary selection must never borrow the chat model"


def test_auxiliary_success_failure_empty_and_manual_titles(environment):
    client, _, state = environment
    for title in ("Optimized title", None):
        calls = []

        async def generate(text):
            calls.append(text)
            return title

        state.utility_llm.generate_title = generate
        session_id = create_session(client)
        send(client, session_id, "First input")
        session = client.get(f"/api/sessions/{session_id}").json()
        assert session["title"] == (title or "First input")
        assert session["title_generation_metadata"]["source"] == ("utility" if title else "input_excerpt")
        send(client, session_id, "Second input")
        assert calls == ["First input"]

    async def failure(_text):
        raise RuntimeError("Auxiliary failed")

    state.utility_llm.generate_title = failure
    session_id = create_session(client)
    send(client, session_id, "Keep this title")
    assert client.get(f"/api/sessions/{session_id}").json()["title"] == "Keep this title"
    for title in ("Manual title", "New session", "新会话"):
        session_id = create_session(client, title=title)
        send(client, session_id, "Ignore this input for naming")
        assert client.get(f"/api/sessions/{session_id}").json()["title"] == title


def test_auxiliary_selection_is_used_and_disabled_selection_keeps_excerpt(environment):
    client, upstream, _ = environment
    model = client.get("/api/models/profiles").json()[0]
    client.patch("/api/models/settings", json={"utility_model_profile_id": model["id"]}).raise_for_status()
    upstream.response = "Generated title"
    session_id = create_session(client)
    send(client, session_id, "Name this conversation")
    assert client.get(f"/api/sessions/{session_id}").json()["title"] == "Generated title"
    assert upstream.calls[-1]["max_tokens"] == 64
    client.patch(f"/api/models/profiles/{model['id']}", json={"enabled": False}).raise_for_status()
    session_id = create_session(client)
    send(client, session_id, "Keep unavailable")
    assert client.get(f"/api/sessions/{session_id}").json()["title"] == "Keep unavailabl…"


def test_attachments_tools_and_failed_runs_get_basic_titles(environment):
    client, upstream, state = environment

    async def unexpected(_text):
        pytest.fail("Attachments and direct tools must not request an auxiliary title")

    state.utility_llm.generate_title = unexpected
    attachment = client.post("/api/attachments", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert attachment.status_code == 200, attachment.text
    session_id = create_session(client)
    send(client, session_id, "", [attachment.json()])
    assert client.get(f"/api/sessions/{session_id}").json()["title"] == "notes.txt"
    session_id = create_session(client)
    send(client, session_id, "/base64_encode hi")
    assert client.get(f"/api/sessions/{session_id}").json()["title"] == "/base64_encode …"
    upstream.failure = 503
    session_id = create_session(client)
    send(client, session_id, "Failed answer")
    assert client.get(f"/api/sessions/{session_id}").json()["title"] == "Failed answer"


def test_manual_rename_and_deletion_during_auxiliary_generation(environment):
    client, _, state = environment
    runner = state.runtime.chat_runner

    async def scenario(delete):
        session_id = create_session(client)
        runner.set_input_title(session_id, "Original input", [], "input")
        started, finish = asyncio.Event(), asyncio.Event()

        async def generate(_text):
            started.set()
            await finish.wait()
            return "Late generated title"

        state.utility_llm.generate_title = generate
        task = asyncio.create_task(runner.maybe_title(session_id, "Original input", "input"))
        await started.wait()
        if delete:
            state.sessions.delete_session(session_id)
        else:
            state.sessions.set_title(session_id, "My manual title")
        finish.set()
        await task
        if not delete:
            assert state.sessions.get_session(session_id).title == "My manual title"

    asyncio.run(scenario(False))
    asyncio.run(scenario(True))
