"""Confirmed QQ delivery pairs, whole-batch pruning and request boundaries."""
import json

import pytest

from ai_workbench.core.models.context_budget import ChatContextBudget
from ai_workbench.core.models.schema import ChatRequest
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.schema.context_budget import ContextLimits
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.project import QQ_DEFAULT_PROMPT
from tests.test_qqbot import qq_client, configure_execution, project
from tests.test_qq_reply_policy import execute_batch
from tests.tool_fixtures import completion, ok, tool_call


def assert_pairs(messages):
    ids = []
    for index, message in enumerate(messages):
        if message["role"] == "assistant":
            assert message["content"] == ""
            call, = message["tool_calls"]
            assert call["function"]["name"] == "qq_send_message"
            assert messages[index + 1]["role"] == "tool"
            assert messages[index + 1]["tool_call_id"] == call["id"]
            assert json.loads(messages[index + 1]["content"])["status"] == "sent"
            ids.append(call["id"])
        elif message["role"] == "tool":
            assert messages[index - 1]["role"] == "assistant"
    assert len(ids) == len(set(ids))


def test_whole_batch_history_limits_and_token_pruning(qq_client, monkeypatch):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    for number in range(1, 4):
        upstream.turns = [completion(tool_call("qq_send_message", {"text": f"reply {number}a"}, "same_a"),
                                    tool_call("qq_send_message", {"text": f"reply {number}b"}, "same_b"), content="PRIVATE"),
                          completion(content="PRIVATE")]
        batch, run = execute_batch(client, state, p, session, number)
        assert run.status == "DONE"
    def build(**policy):
        return build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(**policy), None)
    full = build()
    wire = full.model_dump()["messages"]
    assert len(wire) == 16 and "PRIVATE" not in json.dumps(wire)
    assert_pairs(wire)
    for limit, size in ((0, 1), (2, 1), (3, 6), (5, 6), (6, 11), (None, 16)):
        built = build(max_messages=limit)
        assert len(built.messages) == size
        assert_pairs(built.model_dump()["messages"])
    last = wire[-6:-1]
    length = len("next") + len(last[0]["content"]) + sum(len(json.dumps(m, ensure_ascii=False)) for m in last[1:])
    assert len(build(max_chars=length).messages) == 6
    assert len(build(max_chars=length - 1).messages) == 1
    monkeypatch.setattr("ai_workbench.core.models.context_budget.estimate_input_tokens", lambda payload: 30 * len(payload["messages"]))
    budget = ChatContextBudget(ContextLimits(window_tokens=512, output_tokens=128), full.trace)
    profile = state.model_profiles.get(p["model_profile_id"])
    request = client.portal.call(budget.prepare, profile, ChatRequest(model=profile.alias, messages=full.messages), None)
    assert len(request.messages) == 6 and budget.stats.removed_turns == 2
    assert [s.message_index for s in budget.trace.sources] == list(range(6))
    assert {s.turn_id for s in budget.trace.sources if s.kind == "history"} == {batch.input_message_id}
    assert_pairs([m.model_dump(exclude_none=True) for m in request.messages])
    assert len(connection.calls) == 6  # Projecting native history never dispatches it.


@pytest.mark.parametrize("failure", ["failed", "unknown", "cancelled"])
def test_partial_sends_survive_run_failure_in_history(qq_client, failure):
    import asyncio
    from ai_workbench.core.harness.schema import ToolExecutionError
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    original = connection.call
    async def send(action, params):
        if connection.calls:
            if failure == "cancelled":
                raise asyncio.CancelledError()
            raise TimeoutError() if failure == "unknown" else ToolExecutionError("QQ_ACTION_FAILED", "Rejected")
        return await original(action, params)
    connection.call = send
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "confirmed"}, "first"),
                                tool_call("qq_send_message", {"text": "not confirmed"}, "second"), content="PRIVATE")]
    batch, run = execute_batch(client, state, p, session)
    assert batch.status != "done"
    context = build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(), None)
    wire = context.model_dump()["messages"]
    assert [m["role"] for m in wire] == ["user", "assistant", "tool", "user"]
    assert_pairs(wire)
    assert "not confirmed" not in json.dumps(wire) and "PRIVATE" not in json.dumps(wire)


def test_default_prompt_is_creation_only_and_runtime_is_per_call(qq_client):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, system_prompt="", reply_message_limit=2)
    assert p["system_prompt"] == ""
    upstream.turns = [completion(tool_call("qq_send_message", {"text": str(n)}, f"call{n}")) for n in range(2)]
    _, run = execute_batch(client, state, p, session)
    assert run.status == "DONE"
    for number, call in enumerate(upstream.calls):
        system, = [m for m in call["messages"] if m["role"] == "system"]
        assert system["content"].count("Current batch=") == 1
        assert f"confirmed sends={number}/2" in system["content"]
        assert "your QQ account=12345" in system["content"] and "target=7788" in system["content"]
    snapshot = state.runs.get_config_snapshot(run.run_id)
    assert snapshot["project_system_prompt"] == "" and snapshot["qq_bot_account"] == "12345"
    client.delete(f"/api/projects/{p['id']}")
    p = project(client)
    assert p["system_prompt"] == QQ_DEFAULT_PROMPT
    ok(client.patch(f"/api/projects/{p['id']}", json={"system_prompt": ""}))
    ok(client.patch(f"/api/projects/{p['id']}", json={"name": "Renamed"}))
    assert ok(client.get(f"/api/projects/{p['id']}"))["system_prompt"] == ""
