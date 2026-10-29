"""Localized date instructions in the actual, budgeted Harness request."""

from datetime import date, datetime, timezone

import pytest

from ai_workbench.core.harness import agent_loop
from ai_workbench.core.instructions import date_instruction
from ai_workbench.core.context_snapshot import append_system_block, prepend_system_block
from ai_workbench.core.models.context_budget import ChatContextBudget
from ai_workbench.core.schema.context_budget import ContextLimits
from ai_workbench.core.schema.context_snapshot import ContextSource, ContextTrace
from ai_workbench.core.schema.persona import COGITA_PERSONA_ID, USER_PERSONA_ID
from tests.test_context_detail import details
from tests.test_projects import workspace, child
from tests.test_web_tools import web_env, configure
from tests.model_fixtures import configure_model
from tests.tool_fixtures import completion, ok, register_approval_tool, tool_call


@pytest.mark.parametrize("day,english,chinese", [(26, "Monday", "一"), (27, "Tuesday", "二"), (28, "Wednesday", "三"),
    (29, "Thursday", "四"), (30, "Friday", "五"), (31, "Saturday", "六"), (1, "Sunday", "日")])
def test_date_and_weekday_language(day, english, chinese):
    value = date(2026, 11 if day == 1 else 10, day)
    assert date_instruction("en", value) == f"Current date: {value.isoformat()} ({english})."
    assert date_instruction("zh-CN", value) == f"当前日期：{value.year}年{value.month}月{value.day}日（星期{chinese}）。"


@pytest.mark.parametrize("language", ["en", "zh-CN"])
@pytest.mark.parametrize("project", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_instruction_precedes_persona_in_request_and_snapshot(web_env, monkeypatch, language, project, streaming):
    client, upstream, _ = web_env
    configure_model(client, request_options={"streaming": streaming})
    monkeypatch.setattr(agent_loop, "utc_now", lambda: datetime(2026, 10, 29, 12, tzinfo=timezone.utc))
    ok(client.patch(f"/api/personas/{COGITA_PERSONA_ID}", json={"system_prompt": "AGENT😀\nSecond line"}))
    ok(client.patch(f"/api/personas/{USER_PERSONA_ID}", json={"system_prompt": "USER background"}))
    if project:
        session = child(client, workspace(client, harness_enabled=True, tools_allowed=["web_search"], system_prompt="PROJECT"))
    else:
        session = configure(client, harness_enabled=True, tools_allowed=["web_search"])
    upstream.turns = [completion(content="answer")]
    payload = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Research"},
                             headers={"X-UI-Language": language}))
    assert payload["success"], payload
    snapshot = details(client, payload["run"])[0]
    assert snapshot["request"] == upstream.calls[0]
    sources = {source["kind"]: source for source in snapshot["sources"]}
    expected = date_instruction(language, date(2026, 10, 29))
    assert sources["instruction"]["text"] == expected
    assert sources["instruction"]["parent_id"] == sources["agent_persona"]["parent_id"] == sources["system"]["id"]
    assert sources["instruction"]["start"] == 0
    assert sources["agent_persona"]["start"] == len(expected) + 2
    assert sources["agent_persona"]["text"] == "AGENT😀\nSecond line"
    assert "USER background" in sources["cogita_persona"]["text"]
    assert sources["current_input"]["text"] == "Research"
    if project:
        assert sources["project_prompt"]["text"] == "PROJECT"
    assert snapshot["request"]["messages"][0]["content"].startswith(expected + "\n\nAGENT😀")
    assert snapshot["budget"]["input_tokens"] > 0
    assert all(source["char_count"] == len(source["text"]) for source in snapshot["sources"])


@pytest.mark.parametrize("harness,tools", [(False, ["web_search"]), (True, ["web_fetch"]), (True, []), (True, ["base64_encode"])])
def test_instruction_is_absent_without_enabled_web_search(web_env, harness, tools):
    client, upstream, _ = web_env
    configure_model(client, request_options={"streaming": False})
    session = configure(client, harness_enabled=harness, tools_allowed=tools)
    upstream.turns = [completion(content="answer")]
    payload = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Hello"}))
    assert payload["success"], payload
    assert all(source["kind"] != "instruction" for source in details(client, payload["run"])[0]["sources"])
    assert "Current date:" not in str(upstream.calls[-1])


def test_date_updates_each_round_and_language_survives_approval(web_env, monkeypatch):
    client, upstream, _ = web_env
    configure_model(client, request_options={"streaming": False})
    state = client.app.state.runtime_state
    register_approval_tool(state.tool_registry)
    session = configure(client, harness_enabled=True)
    clock = [datetime(2026, 10, 29, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(agent_loop, "utc_now", lambda: clock[0])
    upstream.turns = [completion(tool_call("test_approval", {"value": "pause"})), completion(content="resumed")]
    payload = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Research"}, headers={"X-UI-Language": "zh-CN"}))
    assert payload["run"]["status"] == "WAITING_FOR_USER"
    run_id = payload["run"]["run_id"]
    assert state.runs.get_harness_state(run_id)["ui_language"] == "zh-CN"
    first = details(client, payload["run"])[0]
    clock[0] = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    payload = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}, headers={"X-UI-Language": "en"}))
    snapshots = details(client, payload["run"])
    assert snapshots[0] == first
    for snapshot, day in zip(snapshots, [29, 30]):
        instructions = [source for source in snapshot["sources"] if source["kind"] == "instruction"]
        assert len(instructions) == 1
        assert instructions[0]["text"] == date_instruction("zh-CN", date(2026, 10, day))
        assert snapshot["request"]["messages"][0]["content"].count("当前日期：") == 1


def test_project_revocation_removes_instruction_from_next_round(web_env):
    client, upstream, _ = web_env
    configure_model(client, request_options={"streaming": False})
    register_approval_tool(client.app.state.runtime_state.tool_registry)
    project = workspace(client, harness_enabled=True, tools_allowed=["web_search", "test_approval"])
    session = child(client, project)
    upstream.turns = [completion(tool_call("test_approval", {"value": "pause"})), completion(content="resumed")]
    payload = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Hello"}))
    assert any(source["kind"] == "instruction" for source in details(client, payload["run"])[0]["sources"])
    ok(client.patch(f"/api/projects/{project['id']}", json={"tools_allowed": ["test_approval"]}))
    payload = ok(client.post(f"/api/tools/approvals/{payload['run']['run_id']}", json={"decision": "approve"}))
    assert all(source["kind"] != "instruction" for source in details(client, payload["run"])[-1]["sources"])


def test_retry_and_edit_use_current_interface_language(web_env):
    client, _, _ = web_env
    configure_model(client, request_options={"streaming": False})
    session = configure(client, harness_enabled=True, tools_allowed=["web_search"])
    payload = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Hello"}))
    first = details(client, payload["run"])[0]
    assert next(s["text"] for s in first["sources"] if s["kind"] == "instruction").startswith("Current date:")
    retried = ok(client.post(f"/api/runs/{payload['run']['run_id']}/retry", headers={"X-UI-Language": "zh-CN"}))
    assert next(s["text"] for s in details(client, retried["run"])[0]["sources"] if s["kind"] == "instruction").startswith("当前日期：")
    user_id = payload["run"]["metadata"]["input_message_id"]
    edited = ok(client.post(f"/api/messages/{user_id}/edit", json={"content": "Edited", "attachment_ids": []}, headers={"X-UI-Language": "en"}))
    assert next(s["text"] for s in details(client, edited["run"])[0]["sources"] if s["kind"] == "instruction").startswith("Current date:")
    assert client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "Bad language"},
                       headers={"X-UI-Language": "arbitrary instructions"}).status_code == 422


def test_prepend_preserves_nested_offsets_and_fixed_history_slot():
    messages = [{"role": "system", "content": "old history"}, {"role": "user", "content": "question"}]
    trace = ContextTrace(sources=[ContextSource(id="history", kind="history", message_index=0, end=11, turn_id="old"),
                                 ContextSource(id="input", kind="current_input", message_index=1)])
    messages, _ = append_system_block(messages, trace, "Knowledge", "knowledge")
    trace.sources.append(ContextSource(id="snippet", kind="knowledge_snippet", parent_id="knowledge", message_index=0, start=13, end=22))
    before = messages[0]["content"]
    result, _ = prepend_system_block(messages, trace, "Today", "instruction")
    assert messages[0]["content"] == before
    for source in trace.sources:
        if source.id == "snippet":
            assert result[0]["content"][source.start:source.end] == "Knowledge"
    budget = ChatContextBudget(ContextLimits(window_tokens=4096, output_tokens=512), trace)
    assert budget._history_groups() == []
    trace = ContextTrace(sources=[ContextSource(id="input", kind="current_input", message_index=0)])
    result, _ = prepend_system_block([{"role": "user", "content": "question"}], trace, "Today", "instruction")
    assert result == [{"role": "system", "content": "Today"}, {"role": "user", "content": "question"}]
    assert next(s.message_index for s in trace.sources if s.id == "input") == 1
