import json

import pytest
import yaml

from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.forms import FormValidationError, validate_action_form_block, validate_action_form_values
from ai_workbench.core.schema.context_policy import ContextPolicy
from tests.test_api import create_session, make_client, post_message


COMFY_WORKFLOW = {
    "3": {"class_type": "KSampler", "inputs": {"steps": 30, "cfg": 7.0}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
}


def write_comfy_assets(tmp_path):
    workflows = tmp_path / "workflows"
    presets = tmp_path / "presets"
    workflows.mkdir(parents=True, exist_ok=True)
    presets.mkdir(parents=True, exist_ok=True)
    (workflows / "base.workflow.json").write_text(json.dumps(COMFY_WORKFLOW), encoding="utf-8")
    (workflows / "other.workflow.json").write_text(json.dumps(COMFY_WORKFLOW), encoding="utf-8")
    base = {
        "id": "base",
        "name": "Base",
        "status": "ready",
        "workflow": {"file_name": "base.workflow.json"},
        "parameters": [
            {"name": "positive_prompt", "type": "textarea", "required": True, "default": "", "mapping": {"node_id": "6", "input_path": ["inputs", "text"]}},
            {"name": "steps", "type": "integer", "default": 30, "mapping": {"node_id": "3", "input_path": ["inputs", "steps"]}},
        ],
        "output": {"images": "all"},
    }
    other = {
        "id": "other",
        "name": "Other",
        "status": "ready",
        "workflow": {"file_name": "other.workflow.json"},
        "parameters": [
            {"name": "cfg", "type": "float", "default": 7.0, "mapping": {"node_id": "3", "input_path": ["inputs", "cfg"]}},
        ],
        "output": {"images": "all"},
    }
    (presets / "base.yaml").write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")
    (presets / "other.yaml").write_text(yaml.safe_dump(other, sort_keys=False), encoding="utf-8")
    return workflows, presets


def demo_form(**overrides):
    form = {
        "type": "action_form",
        "form_id": "demo",
        "title": "Demo Form",
        "fields": [
            {"name": "prompt", "type": "textarea", "required": True, "min_length": 2, "max_length": 20, "value": "hello"},
            {"name": "count", "type": "integer", "minimum": 1, "maximum": 10, "step": 1, "value": 3},
            {"name": "cfg", "type": "float", "minimum": 1, "maximum": 30, "step": 0.5, "value": 7.0},
            {"name": "enabled", "type": "boolean", "value": True},
            {"name": "mode", "type": "enum", "options": [{"value": "fast", "label": "Fast"}, {"value": "quality", "label": "Quality"}], "value": "fast"},
            {"name": "config_json", "type": "json", "default": {"size": "small"}},
        ],
        "submit": {"label": "Run", "action_id": "form_submit"},
    }
    form.update(overrides)
    return form


def test_action_form_payload_shape_validation_success() -> None:
    assert validate_action_form_block(demo_form())["form_id"] == "demo"


def test_action_form_layout_ui_and_sections_validate() -> None:
    form = demo_form(
        fields=[
            {"name": "prompt", "type": "textarea", "ui": {"section": "prompts", "span": 12}},
            {"name": "steps", "type": "integer", "ui": {"section": "sampling", "span": 4}},
        ],
        sections=[{"key": "prompts", "title": "Prompts"}, {"key": "sampling", "title": "Sampling"}],
    )
    parsed = validate_action_form_block(form)
    assert parsed["sections"][0] == {"key": "prompts", "title": "Prompts"}
    assert parsed["fields"][1]["ui"] == {"section": "sampling", "span": 4}


def test_action_form_top_level_ui_validates() -> None:
    form = demo_form(
        ui={
            "default_collapsed": False,
            "collapsed": True,
            "collapse_on_success": True,
            "collapsed_message": "Recipe saved. Click to expand.",
        }
    )
    parsed = validate_action_form_block(form)

    assert parsed["ui"] == {
        "default_collapsed": False,
        "collapsed": True,
        "collapse_on_success": True,
        "collapsed_message": "Recipe saved. Click to expand.",
    }


@pytest.mark.parametrize(
    "ui",
    [
        {"default_collapsed": "false"},
        {"collapsed": "true"},
        {"collapse_on_success": "yes"},
        {"collapsed_message": 123},
        {"unknown": True},
    ],
)
def test_action_form_rejects_invalid_top_level_ui(ui: dict) -> None:
    with pytest.raises(FormValidationError) as exc:
        validate_action_form_block(demo_form(ui=ui))
    assert exc.value.code == "FORM_INVALID"


def test_action_form_submit_visibility_defaults_to_message() -> None:
    assert validate_action_form_block(demo_form())["submit"]["visibility"] == "message"


@pytest.mark.parametrize("missing", ["form_id", "title", "fields", "submit"])
def test_action_form_payload_shape_validation_requires_core_fields(missing: str) -> None:
    form = demo_form()
    form.pop(missing)
    with pytest.raises(FormValidationError) as exc:
        validate_action_form_block(form)
    assert exc.value.code == "FORM_INVALID"


@pytest.mark.parametrize("span", [0, 13, "4"])
def test_action_form_rejects_invalid_ui_span(span) -> None:
    form = demo_form(fields=[{"name": "steps", "type": "integer", "ui": {"section": "sampling", "span": span}}])
    with pytest.raises(FormValidationError) as exc:
        validate_action_form_block(form)
    assert exc.value.code == "FORM_INVALID"


def test_action_form_rejects_ui_order() -> None:
    form = demo_form(fields=[{"name": "steps", "type": "integer", "ui": {"section": "sampling", "span": 4, "order": 1}}])
    with pytest.raises(FormValidationError) as exc:
        validate_action_form_block(form)
    assert exc.value.code == "FORM_INVALID"


def test_action_form_value_validation_success_and_optional_fallbacks() -> None:
    values = validate_action_form_values(
        demo_form(),
        {
            "prompt": "generate",
            "count": "4",
            "cfg": "8.5",
            "enabled": False,
            "mode": "quality",
            "config_json": '{"ok": true}',
        },
    )
    assert values == {
        "prompt": "generate",
        "count": 4,
        "cfg": 8.5,
        "enabled": False,
        "mode": "quality",
        "config_json": {"ok": True},
    }


def test_action_form_value_validation_ignores_layout_metadata() -> None:
    form = demo_form(
        ui={"collapsed": True},
        fields=[{"name": "steps", "type": "integer", "value": 30, "ui": {"section": "sampling", "span": 4}}],
    )
    values = validate_action_form_values(form, {"steps": "44"})
    assert values == {"steps": 44}
    with pytest.raises(FormValidationError):
        validate_action_form_values(form, {"steps": "44", "ui": {"span": 12}})


@pytest.mark.parametrize(
    ("patch", "submitted"),
    [
        ({}, {"prompt": ""}),
        ({}, {"prompt": "x"}),
        ({}, {"prompt": 123}),
        ({}, {"count": 0}),
        ({}, {"count": "1.5"}),
        ({}, {"cfg": "bad"}),
        ({}, {"enabled": "true"}),
        ({}, {"mode": "missing"}),
        ({}, {"config_json": "{bad"}),
        ({}, {"extra": "nope"}),
    ],
)
def test_action_form_value_validation_rejects_invalid_values(patch: dict, submitted: dict) -> None:
    with pytest.raises(FormValidationError) as exc:
        validate_action_form_values(demo_form(**patch), submitted)
    assert exc.value.code == "FORM_VALIDATION_FAILED"


def test_action_form_missing_optional_uses_value_default_none() -> None:
    form = {
        "type": "action_form",
        "form_id": "fallbacks",
        "title": "Fallbacks",
        "fields": [
            {"name": "with_value", "type": "text", "value": "value"},
            {"name": "with_default", "type": "integer", "default": 2},
            {"name": "empty", "type": "text"},
        ],
        "submit": {"action_id": "form_submit"},
    }
    assert validate_action_form_values(form, {}) == {"with_value": "value", "with_default": 2, "empty": None}


def test_form_submit_uses_original_form_target_and_prefill() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="render_test")
    payload = post_message(client, session["session_id"], "@render_test:form")
    form_message = next(message for message in payload["messages"] if any(part.get("type") == "form" and part.get("form_id") == "demo" for part in message.get("parts", [])))

    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={
            "source_message_id": form_message["message_id"],
            "form_id": "demo",
            "values": {
                "prompt": "submitted",
                "count": 5,
                "mode": "quality",
                "enabled": False,
                "config_json": {"size": "medium"},
            },
            "agent_id": "chat",
            "action_id": "default",
        },
    )
    assert response.status_code == 422

    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={
            "source_message_id": form_message["message_id"],
            "form_id": "demo",
            "values": {
                "prompt": "submitted",
                "count": 5,
                "mode": "quality",
                "enabled": False,
                "config_json": {"size": "medium"},
            },
        },
    )
    assert response.status_code == 200
    messages = response.json()["messages"]
    user_message = next(message for message in messages if message["role"] == "user")
    assistant = messages[-1]
    assert user_message["origin"] == "form_submission"
    assert user_message["metadata"]["origin"] == "form_submission"
    assert user_message["metadata"]["source_message_id"] == form_message["message_id"]
    assert user_message["metadata"]["form_id"] == "demo"
    assert user_message["metadata"]["target_agent_id"] == "render_test"
    assert user_message["metadata"]["target_action_id"] == "form_submit"
    assert user_message["metadata"]["prefill"]["prompt"] == "submitted"
    assert user_message["content"] == "Submitted form: Demo Form"
    assert assistant["output_type"] is None
    assert assistant["parts"][0]["type"] == "json"
    assert assistant["parts"][0]["data"]["received_prefill"]["prompt"] == "submitted"
    assert assistant["parts"][0]["data"]["source_message_id"] == form_message["message_id"]
    assert assistant["role"] == "assistant"


def test_silent_form_submit_invokes_target_without_chat_messages_and_writes_state() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="render_test")
    source = client.app.state.runtime_state.messages.add_message(
        session_id=session["session_id"],
        role="assistant",
        content={
            "blocks": [
                {
                    "type": "action_form",
                    "form_id": "silent_demo",
                    "title": "Silent Demo",
                    "fields": [{"name": "prompt", "type": "text", "required": True}],
                    "submit": {
                        "agent_id": "render_test",
                        "action_id": "form_submit",
                        "visibility": "silent",
                        "success_message": "Recipe saved",
                    },
                }
            ]
        },
        agent_id="render_test",
        output_type="rich_content",
    )

    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={
            "source_message_id": source.message_id,
            "form_id": "silent_demo",
            "values": {"prompt": "submitted"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ok"] is True
    assert payload["silent"] is True
    assert payload["message"] == "Recipe saved"
    assert payload["run_id"]
    assert payload["messages"] == []

    messages = client.app.state.runtime_state.messages.list_messages(session["session_id"])
    assert [message.origin for message in messages] == ["agent_reply"]
    assert all(message.origin != "form_submission" for message in messages)
    assert all(message.role != "tool" for message in messages)
    state = client.app.state.runtime_state.session_agent_states.get_state(
        session["session_id"], "render_test", "last_silent_form_submission"
    )
    assert state["prefill"]["prompt"] == "submitted"
    assert state["source_message_id"] == source.message_id
    assert state["form_id"] == "silent_demo"
    assert state["is_silent_submission"] is True


def test_comfyui_silent_recipe_save_updates_source_form_block_without_chat_bubbles(tmp_path) -> None:
    workflows, presets = write_comfy_assets(tmp_path)
    client = make_client()
    client.patch(
        "/api/capability-configs/comfyui",
        json={"user_config": {"workflows_dir": str(workflows), "presets_dir": str(presets), "allow_workflow_file_write": True, "allow_preset_file_write": True}},
    )
    session = create_session(client, default_agent_id="comfyui_agent")
    payload = post_message(client, session["session_id"], "@comfyui_agent:form")
    form_message = next(message for message in payload["messages"] if any(part.get("type") == "form" and part.get("form_id") == "comfyui_recipe" for part in message.get("parts", [])))

    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={
            "source_message_id": form_message["message_id"],
            "form_id": "comfyui_recipe",
            "values": {"preset_id": "base", "positive_prompt": "new prompt", "steps": 44},
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is True
    assert result["silent"] is True
    assert result["messages"] == []
    assert result["updated_form"]["source_message_id"] == form_message["message_id"]
    updated = client.app.state.runtime_state.messages.get_message(form_message["message_id"])
    form = next(part for part in updated.parts if part.get("type") == "form" and part.get("form_id") == "comfyui_recipe")
    fields = {field["name"]: field for field in form["fields"]}
    assert form["ui"]["collapsed"] is True
    assert form["ui"]["collapsed_message"] == "Recipe saved. Click to expand."
    assert fields["positive_prompt"]["value"] == "new prompt"
    assert fields["steps"]["value"] == 44
    assert updated.content_version == 2
    form_part = next(part for part in updated.parts if part.get("type") == "form" and part.get("form_id") == "comfyui_recipe")
    assert form_part["ui"]["collapsed"] is True
    messages = client.app.state.runtime_state.messages.list_messages(session["session_id"])
    assert [message.origin for message in messages] == ["user_message", "agent_reply"]


def test_comfyui_silent_recipe_save_preset_switch_returns_new_form_fields(tmp_path) -> None:
    workflows, presets = write_comfy_assets(tmp_path)
    client = make_client()
    client.patch(
        "/api/capability-configs/comfyui",
        json={"user_config": {"workflows_dir": str(workflows), "presets_dir": str(presets), "allow_workflow_file_write": True, "allow_preset_file_write": True}},
    )
    session = create_session(client, default_agent_id="comfyui_agent")
    payload = post_message(client, session["session_id"], "@comfyui_agent:form")
    form_message = next(message for message in payload["messages"] if any(part.get("type") == "form" and part.get("form_id") == "comfyui_recipe" for part in message.get("parts", [])))

    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={"source_message_id": form_message["message_id"], "form_id": "comfyui_recipe", "values": {"preset_id": "other", "positive_prompt": "ignored", "steps": 30}},
    )

    assert response.status_code == 200
    block = response.json()["updated_form"]["block"]
    fields = {field["name"]: field for field in block["fields"]}
    assert block["ui"]["collapsed"] is True
    assert set(fields) == {"preset_id", "cfg"}
    assert fields["preset_id"]["value"] == "other"


def test_silent_form_submit_validation_failure_does_not_invoke_target() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="render_test")
    source = client.app.state.runtime_state.messages.add_message(
        session_id=session["session_id"],
        role="assistant",
        content={
            "blocks": [
                {
                    "type": "action_form",
                    "form_id": "silent_invalid",
                    "title": "Silent Invalid",
                    "fields": [{"name": "prompt", "type": "text", "required": True}],
                    "submit": {"agent_id": "render_test", "action_id": "form_submit", "visibility": "silent"},
                }
            ]
        },
        agent_id="render_test",
        output_type="rich_content",
    )

    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={"source_message_id": source.message_id, "form_id": "silent_invalid", "values": {"prompt": ""}},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "FORM_VALIDATION_FAILED"
    assert client.app.state.runtime_state.session_agent_states.get_state(
        session["session_id"], "render_test", "last_silent_form_submission"
    ) is None


def test_silent_form_submit_ignores_request_visibility_and_target_overrides() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="render_test")
    payload = post_message(client, session["session_id"], "@render_test:form")
    form_message = next(message for message in payload["messages"] if any(part.get("type") == "form" and part.get("form_id") == "demo" for part in message.get("parts", [])))

    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={
            "source_message_id": form_message["message_id"],
            "form_id": "demo",
            "values": {
                "prompt": "submitted",
                "count": 5,
                "mode": "quality",
                "enabled": False,
                "config_json": {"size": "medium"},
            },
            "submit": {"visibility": "silent", "agent_id": "chat", "action_id": "default"},
        },
    )

    assert response.status_code == 422


def test_silent_form_submit_target_failure_returns_structured_error_without_chat_messages() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="render_test")
    source = client.app.state.runtime_state.messages.add_message(
        session_id=session["session_id"],
        role="assistant",
        content={
            "blocks": [
                {
                    "type": "action_form",
                    "form_id": "silent_fail",
                    "title": "Silent Fail",
                    "fields": [{"name": "prompt", "type": "text", "required": True}],
                    "submit": {
                        "agent_id": "render_test",
                        "action_id": "form_submit",
                        "visibility": "silent",
                        "failure_message": "Save failed",
                    },
                }
            ]
        },
        agent_id="render_test",
        output_type="rich_content",
    )

    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={"source_message_id": source.message_id, "form_id": "silent_fail", "values": {"prompt": "fail"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["ok"] is False
    assert payload["silent"] is True
    assert payload["message"] == "Save failed: Form submit failed on request."
    assert payload["messages"] == []


def test_form_submit_invalid_target_action_returns_structured_error() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="render_test")
    source = client.app.state.runtime_state.messages.add_message(
        session_id=session["session_id"],
        role="assistant",
        content={
            "blocks": [
                {
                    "type": "action_form",
                    "form_id": "bad",
                    "title": "Bad",
                    "fields": [{"name": "prompt", "type": "text"}],
                    "submit": {"action_id": "missing"},
                }
            ]
        },
        agent_id="render_test",
        output_type="rich_content",
    )
    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={"source_message_id": source.message_id, "form_id": "bad", "values": {"prompt": "x"}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "FORM_TARGET_INVALID"


def test_form_submit_missing_target_agent_returns_structured_error() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="render_test")
    source = client.app.state.runtime_state.messages.add_message(
        session_id=session["session_id"],
        role="assistant",
        content={
            "blocks": [
                {
                    "type": "action_form",
                    "form_id": "bad_agent",
                    "title": "Bad Agent",
                    "fields": [{"name": "prompt", "type": "text"}],
                    "submit": {"agent_id": "missing_agent", "action_id": "default"},
                }
            ]
        },
        agent_id="render_test",
        output_type="rich_content",
    )
    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={"source_message_id": source.message_id, "form_id": "bad_agent", "values": {"prompt": "x"}},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FORM_TARGET_INVALID"


def test_form_submit_disabled_target_agent_returns_structured_error() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="chat")
    client.patch("/api/agent-configs/render_test", json={"enabled": False})
    source = client.app.state.runtime_state.messages.add_message(
        session_id=session["session_id"],
        role="assistant",
        content={
            "blocks": [
                {
                    "type": "action_form",
                    "form_id": "disabled_agent",
                    "title": "Disabled Agent",
                    "fields": [{"name": "prompt", "type": "text"}],
                    "submit": {"agent_id": "render_test", "action_id": "form_submit"},
                }
            ]
        },
        agent_id="chat",
        output_type="rich_content",
    )
    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={"source_message_id": source.message_id, "form_id": "disabled_agent", "values": {"prompt": "x"}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "FORM_TARGET_INVALID"


def test_form_submission_context_uses_summary_not_prefill_json() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="render_test")
    message = client.app.state.runtime_state.messages.add_message(
        session_id=session["session_id"],
        role="user",
        content="Submitted form: Demo Form",
        metadata={"origin": "form_submission", "prefill": {"prompt": "hidden detailed value"}},
        origin="form_submission",
    )
    context = ContextBuilder(client.app.state.runtime_state.messages).build(
        session_id=session["session_id"],
        args="",
        policy=ContextPolicy(mode="current_message"),
        current_message_id=message.message_id,
    )
    assert context.messages == [{"role": "user", "content": "Submitted form: Demo Form"}]
    assert "hidden detailed value" not in str(context.messages)
