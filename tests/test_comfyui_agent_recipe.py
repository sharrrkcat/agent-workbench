import asyncio
import json
from pathlib import Path

import pytest
import yaml

from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.message_parts import blocks_to_parts
from ai_workbench.core.schema.llm_profile import LLMProfileSchema, ProviderProfileSchema
from agents.comfyui_agent import agent as comfy_agent
from ai_workbench.core.stores import SessionAgentStateStore
from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, run as run_async


WORKFLOW = {
    "3": {"class_type": "KSampler", "inputs": {"steps": 30, "cfg": 7.0}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
}

READY_PRESET = {
    "file_name": "txt2img.yaml",
    "preset_id": "txt2img_basic",
    "id": "txt2img_basic",
    "name": "Text to Image Basic",
    "valid": True,
    "status": "ready",
    "workflow": {"file_name": "txt2img.workflow.json", "hash": "sha256:abc"},
    "parameters": [
        {"name": "positive_prompt", "type": "textarea", "required": True, "default": "", "mapping": {"node_id": "6", "input_path": ["inputs", "text"]}},
        {"name": "negative_prompt", "type": "textarea", "default": "", "mapping": {"node_id": "7", "input_path": ["inputs", "text"]}},
        {"name": "steps", "type": "integer", "default": 30, "minimum": 1, "maximum": 150, "mapping": {"node_id": "3", "input_path": ["inputs", "steps"]}},
    ],
    "errors": [],
    "warnings": [],
}

OTHER_PRESET = {
    **READY_PRESET,
    "file_name": "other.yaml",
    "preset_id": "other",
    "id": "other",
    "name": "Other",
    "workflow": {"file_name": "other.workflow.json", "hash": "sha256:def"},
    "parameters": [{"name": "cfg", "type": "float", "default": 7.0, "mapping": {"node_id": "3", "input_path": ["inputs", "cfg"]}}],
}


class Result:
    def __init__(self, data=None, success=True, error=""):
        self.success = success
        self.data = data or {}
        self.error = error


class FakeInput:
    def __init__(self, text="", prefill=None, is_silent_submission=False):
        self.text = text
        self.prefill = prefill or {}
        self.form_id = ""
        self.source_message_id = ""
        self.is_silent_submission = is_silent_submission


class FakeState:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value


class FakeLLM:
    def __init__(self, text="cinematic cat", fail=False, unload_ok=True, error=None):
        self.calls = []
        self.text_value = text
        self.fail = fail
        self.unload_ok = unload_ok
        self.error = error

    async def text(self, **kwargs):
        self.calls.append(("text", kwargs))
        if self.fail:
            raise self.error or RuntimeError("no model")
        return self.text_value

    async def unload_model(self):
        self.calls.append(("unload_model", {}))
        return {"ok": self.unload_ok, "error": "" if self.unload_ok else "unsupported"}


class FakeStep:
    def __init__(self, step_id, label, message=""):
        self.step_id = step_id
        self.label = label
        self.message = message
        self.status = "running"


class FakeRun:
    def __init__(self):
        self.steps = []

    def start_step(self, label, message=None, metadata=None, parent_step_id=None):
        step = FakeStep(f"step-{len(self.steps)}", label, message or "")
        self.steps.append(step)
        return step

    def complete_step(self, step_id, message=None):
        step = self._step(step_id)
        step.status = "completed"
        step.message = message or step.message
        return step

    def fail_step(self, step_id, error_code=None, error_message=None):
        step = self._step(step_id)
        step.status = "failed"
        step.error_code = error_code
        step.error_message = error_message
        return step

    def update_step(self, step_id, message=None, metadata=None):
        step = self._step(step_id)
        step.message = message or step.message
        return step

    def _step(self, step_id):
        return next(step for step in self.steps if step.step_id == step_id)


class FakeRunStore:
    def __init__(self):
        self.metadata = {}
        self.cancel_requested = False

    def get_run(self, run_id):
        return type("Run", (), {"metadata": self.metadata, "cancel_requested": self.cancel_requested})()

    def update_metadata(self, run_id, metadata):
        self.metadata = metadata


class FakeCapability:
    def __init__(self, ctx):
        self.ctx = ctx

    async def scan_workflow_library(self):
        self.ctx.calls.append("scan_workflow_library")
        return Result(self.ctx.scan)

    async def load_preset(self, preset_id=None, file_name=None):
        self.ctx.calls.append("load_preset")
        if self.ctx.load_preset_result is not None:
            return Result(self.ctx.load_preset_result)
        preset = OTHER_PRESET if preset_id == "other" else READY_PRESET
        return Result({"found": True, "preset": {"id": preset["preset_id"], "name": preset["name"], "status": preset["status"], "workflow": preset["workflow"], "parameters": preset["parameters"]}, "validation": preset})

    async def validate_preset(self, preset_id=None, file_name=None, preset=None):
        self.ctx.calls.append("validate_preset")
        return Result({"valid": True, "status": "ready", "errors": [], "warnings": []})

    async def test_connection(self):
        self.ctx.calls.append("test_connection")
        return Result({"reachable": False, "summary": "ComfyUI is unreachable."})

    async def submit_workflow(self, workflow=None):
        self.ctx.calls.append(("submit_workflow", workflow))
        return Result({"accepted": True, "prompt_id": "prompt-1"})

    async def get_prompt_status(self, prompt_id=None):
        self.ctx.calls.append("get_prompt_status")
        if self.ctx.statuses:
            return Result(self.ctx.statuses.pop(0))
        return Result(completed_status())

    async def fetch_image(self, **kwargs):
        self.ctx.calls.append(("fetch_image", kwargs))
        return Result({"filename": kwargs["filename"], "mime_type": "image/png", "data_base64": "ZmFrZQ=="})

    async def free_memory(self, unload_models=True, free_memory=True):
        self.ctx.calls.append(("free_memory", {"unload_models": unload_models, "free_memory": free_memory}))
        return Result(self.ctx.free_memory_result)

    async def interrupt(self):
        self.ctx.calls.append("interrupt")
        return Result({"ok": True})


class FakeCtx:
    def __init__(self, tmp_path: Path, action_id="default", text="", prefill=None, config=None, scan=None, llm=None, is_silent_submission=False):
        self.action_id = action_id
        self.input = FakeInput(text, prefill, is_silent_submission)
        self.config = {
            "default_input_mode": "llm",
            "default_preset_id": "txt2img_basic",
            "llm_operation_default": "refine",
            "llm_refine_system_prompt": "Improve prompts.",
            "llm_refine_user_template": "{user_input}\n{positive_prompt}\n{negative_prompt}\n{preset_id}\n{preset_name}\n{input_mode}\n{llm_operation}",
            "llm_fresh_system_prompt": "Improve fresh prompts.",
            "llm_fresh_user_template": "{user_input}\n{negative_prompt}\n{preset_id}\n{preset_name}\n{input_mode}\n{llm_operation}",
            "auto_run_after_llm_prompt": True,
            "unload_llm_before_generation": True,
            **(config or {}),
        }
        self.state = FakeState()
        self.calls = []
        self.replies = []
        self.llm = llm or FakeLLM()
        self.run = FakeRun()
        self.run_id = "run-1"
        self.run_store = FakeRunStore()
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir(parents=True, exist_ok=True)
        (workflows_dir / "txt2img.workflow.json").write_text(json.dumps(WORKFLOW), encoding="utf-8")
        (workflows_dir / "other.workflow.json").write_text(json.dumps(WORKFLOW), encoding="utf-8")
        self.scan = scan or {
            "presets": [READY_PRESET, OTHER_PRESET],
            "workflows": [{"file_name": "txt2img.workflow.json", "valid": True, "hash": "sha256:abc"}],
            "workflows_dir": str(workflows_dir),
            "presets_dir": str(tmp_path / "presets"),
            "config": {"poll_interval_seconds": 0, "max_wait_seconds": 1},
        }
        self.statuses = []
        self.attachments = []
        self.free_memory_result = {"ok": True, "requested": {"unload_models": True, "free_memory": True}, "status_code": 200, "response": {}}
        self.load_preset_result = None

    def capability(self, name):
        assert name == "comfyui"
        return FakeCapability(self)

    async def reply_markdown(self, value, **kwargs):
        self.replies.append(("markdown", value, kwargs))

    async def reply_blocks(self, blocks, **kwargs):
        self.replies.append(("parts", blocks_to_parts(blocks), kwargs))

    async def reply_images(self, images, **kwargs):
        self.replies.append(("media_group", images, kwargs))

    async def save_attachment_base64(self, data_base64, filename, mime_type, kind="file", metadata=None):
        attachment = {"id": f"att-{len(self.attachments)}", "url": f"/api/attachments/att-{len(self.attachments)}.png", "name": filename, "metadata": metadata or {}}
        self.attachments.append(attachment)
        return attachment


def completed_status():
    return {"prompt_id": "prompt-1", "status": "completed", "completed": True, "failed": False, "outputs": {"images": [{"filename": "out.png", "type": "output", "subfolder": ""}]}}


def run(coro):
    return asyncio.run(coro)


def text_part(message):
    return next(part for part in message.parts if part.get("type") == "text")


@pytest.mark.parametrize("mode", ["llm", "raw"])
def test_new_session_recipe_uses_default_input_mode(tmp_path: Path, mode):
    ctx = FakeCtx(tmp_path, action_id="status", config={"default_input_mode": mode})

    recipe, preset, presets, state = run(comfy_agent.current_recipe(ctx))

    assert recipe["preset_id"] == "txt2img_basic"
    assert recipe["input_mode"] == mode


@pytest.mark.parametrize("stored_value", [None, "", "unset"])
def test_default_input_mode_unset_values_fall_back_to_manifest_default(tmp_path: Path, stored_value):
    ctx = FakeCtx(tmp_path, action_id="status", config={"default_input_mode": stored_value})

    recipe, _, _, _ = run(comfy_agent.current_recipe(ctx))

    assert recipe["input_mode"] == "llm"


def test_default_input_mode_invalid_value_fails_clearly(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="status", config={"default_input_mode": "unset-but-not-valid"})

    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.current_recipe(ctx))

    assert exc.value.code == "COMFYUI_CONFIG_INVALID"


@pytest.mark.parametrize("stored_value", [None, "", "unset"])
def test_llm_operation_default_unset_values_fall_back_to_manifest_default(stored_value):
    assert comfy_agent.resolve_default_llm_operation({"llm_operation_default": stored_value}) == "refine"


def test_llm_operation_default_invalid_value_fails_clearly():
    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        comfy_agent.resolve_default_llm_operation({"llm_operation_default": "unset-but-not-valid"})

    assert exc.value.code == "COMFYUI_CONFIG_INVALID"


def test_save_form_same_preset_updates_recipe_values_only(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="save_recipe_from_form", prefill={"preset_id": "txt2img_basic", "positive_prompt": "cat", "steps": 44})
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "llm")
    recipe["user_prompt"] = "keep me"
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)

    assert saved["values"]["positive_prompt"] == "cat"
    assert saved["values"]["steps"] == 44
    assert saved["input_mode"] == "llm"
    assert saved["user_prompt"] == "keep me"
    assert not any(call[0] == "submit_workflow" for call in ctx.calls if isinstance(call, tuple))
    assert ctx.replies[-1][0] == "markdown"
    assert all(reply[0] != "media_group" for reply in ctx.replies)
    assert all(not any(part.get("type") == "form" for part in reply[1]) for reply in ctx.replies if reply[0] == "parts")


def test_save_form_changed_preset_replaces_recipe_and_drops_old_fields(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="save_recipe_from_form", prefill={"preset_id": "other", "cfg": 8.0})
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "llm")
    recipe["values"]["positive_prompt"] = "old"
    recipe["user_prompt"] = "old user prompt"
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)

    assert saved["preset_id"] == "other"
    assert saved["input_mode"] == "llm"
    assert saved["user_prompt"] == ""
    assert saved["values"] == {"cfg": 7.0}


def test_silent_save_form_saves_recipe_without_chat_reply_or_generation(tmp_path: Path):
    ctx = FakeCtx(
        tmp_path,
        action_id="save_recipe_from_form",
        prefill={"preset_id": "txt2img_basic", "positive_prompt": "silent cat", "steps": 31},
        is_silent_submission=True,
    )
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))

    run(comfy_agent.run(ctx))
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)

    assert saved["values"]["positive_prompt"] == "silent cat"
    assert saved["values"]["steps"] == 31
    assert ctx.replies == []
    assert not any(call[0] == "submit_workflow" for call in ctx.calls if isinstance(call, tuple))


def test_recipe_form_excludes_mode_and_user_prompt_uses_current_values_and_silent_submit(tmp_path: Path):
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "llm")
    recipe["values"]["positive_prompt"] = "current generated prompt"
    form = comfy_agent.recipe_to_form(recipe, READY_PRESET, [READY_PRESET, OTHER_PRESET])

    fields = {field["name"]: field for field in form["fields"]}
    assert "preset_id" in fields
    assert fields["preset_id"]["options"]
    assert fields["preset_id"]["value"] == "txt2img_basic"
    assert "input_mode" not in fields
    assert "user_prompt" not in fields
    assert fields["positive_prompt"]["value"] == "current generated prompt"
    assert form["submit"]["visibility"] == "silent"
    assert form["submit"]["success_message"] == "Recipe saved"
    assert form["ui"]["default_collapsed"] is False
    assert form["ui"]["collapsed"] is False
    assert form["ui"]["collapse_on_success"] is True
    assert form["ui"]["collapsed_message"] == "Recipe saved. Click to expand."


def test_recipe_form_can_render_saved_collapsed_state_with_fields(tmp_path: Path):
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "llm")
    recipe["values"]["positive_prompt"] = "saved prompt"

    form = comfy_agent.recipe_to_form(recipe, READY_PRESET, [READY_PRESET], collapsed=True)
    fields = {field["name"]: field for field in form["fields"]}

    assert form["type"] == "action_form"
    assert form["ui"]["collapsed"] is True
    assert form["ui"]["collapse_on_success"] is True
    assert fields["positive_prompt"]["value"] == "saved prompt"
    assert "input_mode" not in fields
    assert "user_prompt" not in fields


def test_recipe_form_copies_preset_ui_to_action_form(tmp_path: Path):
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "llm")
    preset = {
        **READY_PRESET,
        "ui": {"sections": [{"key": "prompts", "title": "Prompts"}, {"key": "sampling", "title": "Sampling"}]},
        "parameters": [
            {**READY_PRESET["parameters"][0], "ui": {"section": "prompts", "span": 12}},
            {**READY_PRESET["parameters"][2], "ui": {"section": "sampling", "span": 6}},
        ],
    }

    form = comfy_agent.recipe_to_form(recipe, preset, [preset])
    fields = {field["name"]: field for field in form["fields"]}

    assert form["sections"] == [{"key": "prompts", "title": "Prompts"}, {"key": "sampling", "title": "Sampling"}]
    assert fields["positive_prompt"]["ui"] == {"section": "prompts", "span": 12}
    assert fields["steps"]["ui"] == {"section": "sampling", "span": 6}


def test_recipe_form_default_layout_for_common_fields(tmp_path: Path):
    preset = {
        **READY_PRESET,
        "parameters": [
            *READY_PRESET["parameters"],
            {"name": "cfg", "type": "float", "default": 7.0, "mapping": {"node_id": "3", "input_path": ["inputs", "cfg"]}},
            {"name": "width", "type": "integer", "default": 1024, "mapping": {"node_id": "3", "input_path": ["inputs", "cfg"]}},
            {"name": "height", "type": "integer", "default": 1024, "mapping": {"node_id": "3", "input_path": ["inputs", "cfg"]}},
            {"name": "batch_size", "type": "integer", "default": 1, "mapping": {"node_id": "3", "input_path": ["inputs", "cfg"]}},
        ],
    }
    recipe = comfy_agent.recipe_from_preset(preset, "llm")

    form = comfy_agent.recipe_to_form(recipe, preset, [preset])
    fields = {field["name"]: field for field in form["fields"]}

    assert fields["preset_id"]["ui"] == {"section": "recipe", "span": 12}
    assert fields["positive_prompt"]["ui"] == {"section": "prompts", "span": 12}
    assert fields["negative_prompt"]["ui"] == {"section": "prompts", "span": 12}
    assert fields["steps"]["ui"] == {"section": "sampling", "span": 4}
    assert fields["cfg"]["ui"] == {"section": "sampling", "span": 4}
    assert fields["width"]["ui"] == {"section": "image", "span": 4}
    assert fields["height"]["ui"] == {"section": "image", "span": 4}
    assert fields["batch_size"]["ui"] == {"section": "image", "span": 4}


def test_recipe_form_preserves_explicit_ui_parts_when_defaulting_missing_parts(tmp_path: Path):
    preset = {
        **READY_PRESET,
        "parameters": [
            {**READY_PRESET["parameters"][2], "ui": {"span": 6}},
            {"name": "cfg", "type": "float", "default": 7.0, "ui": {"section": "advanced"}, "mapping": {"node_id": "3", "input_path": ["inputs", "cfg"]}},
        ],
    }
    recipe = comfy_agent.recipe_from_preset(preset, "llm")

    form = comfy_agent.recipe_to_form(recipe, preset, [preset])
    fields = {field["name"]: field for field in form["fields"]}

    assert fields["steps"]["ui"] == {"section": "sampling", "span": 6}
    assert fields["cfg"]["ui"] == {"section": "advanced", "span": 4}


def test_recipe_form_rejects_invalid_enum_parameter_before_part_validation(tmp_path: Path):
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "llm")
    bad_preset = {**READY_PRESET, "parameters": [{"name": "sampler_name", "type": "enum", "default": "euler", "options": []}]}

    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        comfy_agent.recipe_to_form(recipe, bad_preset, [bad_preset])

    assert exc.value.code == "COMFYUI_PRESET_INVALID"
    assert "sampler_name" in exc.value.message
    assert "COMFYUI_PRESET_SCHEMA" in exc.value.message


def test_form_action_without_ready_preset_returns_clear_prompt_not_empty_options(tmp_path: Path):
    needs_mapping = {**READY_PRESET, "preset_id": "draft", "id": "draft", "status": "needs_mapping"}
    scan = {
        "presets": [needs_mapping],
        "workflows": [],
        "workflows_dir": str(tmp_path / "workflows"),
        "presets_dir": str(tmp_path / "presets"),
        "config": {"poll_interval_seconds": 0, "max_wait_seconds": 1},
    }
    ctx = FakeCtx(tmp_path, action_id="form", scan=scan)

    run(comfy_agent.run(ctx))

    assert ctx.replies[-1][0] == "markdown"
    assert "No valid ready ComfyUI preset" in ctx.replies[-1][1]
    assert "Needs mapping presets" in ctx.replies[-1][1]
    assert all(reply[0] != "parts" for reply in ctx.replies)


def test_switch_only_changes_input_mode_and_does_not_generate(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="switch", text="raw")
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))
    ctx.config["llm_operation_default"] = "fresh"

    run(comfy_agent.run(ctx))

    assert ctx.state.get(comfy_agent.RECIPE_KEY)["input_mode"] == "raw"
    assert ctx.config["llm_operation_default"] == "fresh"
    assert "submit_workflow" not in ctx.calls


def test_raw_action_writes_positive_prompt_without_changing_mode_and_generates(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="raw", text="raw prompt")
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))

    run(comfy_agent.run(ctx))
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)

    assert saved["values"]["positive_prompt"] == "raw prompt"
    assert saved["input_mode"] == "llm"
    assert any(call[0] == "submit_workflow" for call in ctx.calls if isinstance(call, tuple))
    assert ctx.llm.calls == []
    assert "llm_operation" not in ctx.run_store.metadata["comfyui_generation"]


def test_llm_action_writes_user_prompt_enhances_without_changing_mode_and_generates(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="llm", text="make a cat")
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))

    run(comfy_agent.run(ctx))
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)

    assert saved["user_prompt"] == "make a cat"
    assert saved["values"]["positive_prompt"] == "cinematic cat"
    assert saved["input_mode"] == "raw"
    assert saved["last_llm_operation"] == "refine"
    assert ctx.llm.calls[0][0] == "text"
    assert ("unload_model", {}) in ctx.llm.calls


def test_default_llm_mode_uses_configured_refine_template(tmp_path: Path):
    ctx = FakeCtx(
        tmp_path,
        action_id="default",
        text="add gulls",
        config={
            "llm_operation_default": "refine",
            "llm_refine_system_prompt": "Refine system",
            "llm_refine_user_template": "request={user_input}; old={positive_prompt}; op={llm_operation}",
            "auto_run_after_llm_prompt": False,
        },
        llm=FakeLLM(text="ocean with gulls"),
    )
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "llm")
    recipe["values"]["positive_prompt"] = "ocean"
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))

    call = ctx.llm.calls[0][1]
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)
    assert call["system"] == "Refine system"
    assert call["user"] == "request=add gulls; old=ocean; op=refine"
    assert saved["values"]["positive_prompt"] == "ocean with gulls"
    assert saved["last_llm_operation"] == "refine"
    assert ctx.run_store.metadata["comfyui_generation"]["llm_operation"] == "refine"


def test_default_llm_mode_uses_configured_fresh_template_without_current_positive_prompt(tmp_path: Path):
    ctx = FakeCtx(
        tmp_path,
        action_id="default",
        text="new forest",
        config={
            "llm_operation_default": "fresh",
            "llm_fresh_system_prompt": "Fresh system",
            "llm_fresh_user_template": "request={user_input}; op={llm_operation}",
            "auto_run_after_llm_prompt": False,
        },
        llm=FakeLLM(text="forest prompt"),
    )
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "llm")
    recipe["values"]["positive_prompt"] = "old ocean prompt"
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))

    call = ctx.llm.calls[0][1]
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)
    assert call["system"] == "Fresh system"
    assert call["user"] == "request=new forest; op=fresh"
    assert "old ocean prompt" not in call["user"]
    assert saved["values"]["positive_prompt"] == "forest prompt"
    assert saved["last_llm_operation"] == "fresh"
    assert ctx.run_store.metadata["comfyui_generation"]["llm_operation"] == "fresh"


def test_llm_action_uses_llm_operation_default(tmp_path: Path):
    ctx = FakeCtx(
        tmp_path,
        action_id="llm",
        text="new ocean",
        config={
            "llm_operation_default": "fresh",
            "llm_fresh_user_template": "{user_input}|{llm_operation}",
            "auto_run_after_llm_prompt": False,
        },
    )
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "raw")
    recipe["values"]["positive_prompt"] = "old prompt"
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))

    assert ctx.llm.calls[0][1]["user"] == "new ocean|fresh"
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)
    assert saved["input_mode"] == "raw"
    assert saved["last_llm_operation"] == "fresh"


def test_refine_template_ignores_legacy_custom_fields() -> None:
    system, template = comfy_agent._llm_prompt_template(
        {
            "prompt_enhancer_system_prompt": "Legacy custom system",
            "prompt_enhancer_user_template": "legacy={user_input}",
        },
        "refine",
    )

    assert system == comfy_agent.DEFAULT_LLM_REFINE_SYSTEM_PROMPT.strip()
    assert template == comfy_agent.DEFAULT_LLM_REFINE_USER_TEMPLATE.strip()


def test_refine_template_prefers_new_field_over_legacy_field() -> None:
    system, template = comfy_agent._llm_prompt_template(
        {
            "llm_refine_system_prompt": "New custom system",
            "llm_refine_user_template": "new={user_input}",
            "prompt_enhancer_system_prompt": "Legacy custom system",
            "prompt_enhancer_user_template": "legacy={user_input}",
        },
        "refine",
    )

    assert system == "New custom system"
    assert template == "new={user_input}"


def test_prompt_template_empty_value_fails_clearly() -> None:
    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        comfy_agent._llm_prompt_template({"llm_refine_user_template": ""}, "refine")

    assert exc.value.code == "COMFYUI_PROMPT_TEMPLATE_EMPTY"
    assert exc.value.detail["field"] == "llm_refine_user_template"


@pytest.mark.parametrize(
    ("action_id", "configured_default", "expected_operation"),
    [
        ("fresh", "refine", "fresh"),
        ("refine", "fresh", "refine"),
    ],
)
def test_fresh_and_refine_actions_force_operation_without_changing_default(tmp_path: Path, action_id: str, configured_default: str, expected_operation: str):
    ctx = FakeCtx(
        tmp_path,
        action_id=action_id,
        text="make a cat",
        config={
            "llm_operation_default": configured_default,
            "llm_refine_user_template": "refine={user_input}|{positive_prompt}|{llm_operation}",
            "llm_fresh_user_template": "fresh={user_input}|{llm_operation}",
            "auto_run_after_llm_prompt": False,
        },
    )
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "raw")
    recipe["values"]["positive_prompt"] = "old prompt"
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))

    call_user = ctx.llm.calls[0][1]["user"]
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)
    assert expected_operation in call_user
    assert saved["input_mode"] == "raw"
    assert saved["last_llm_operation"] == expected_operation
    assert ctx.config["llm_operation_default"] == configured_default


@pytest.mark.parametrize(
    ("action_id", "stored_mode"),
    [
        ("llm", "raw"),
        ("default", "llm"),
        ("fresh", "raw"),
        ("refine", "raw"),
    ],
)
def test_llm_auto_run_false_saves_and_displays_positive_prompt_without_submitting(tmp_path: Path, action_id: str, stored_mode: str):
    generated = "cinematic `cat`\n```note\nkept\n```"
    ctx = FakeCtx(tmp_path, action_id=action_id, text="make a cat", config={"auto_run_after_llm_prompt": False}, llm=FakeLLM(text=generated))
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, stored_mode))

    run(comfy_agent.run(ctx))
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)

    assert saved["user_prompt"] == "make a cat"
    assert saved["values"]["positive_prompt"] == generated
    assert saved["input_mode"] == stored_mode
    assert saved["last_llm_operation"] in {"refine", "fresh"}
    assert [call[0] for call in ctx.llm.calls] == ["text"]
    assert not any(call[0] == "submit_workflow" for call in ctx.calls if isinstance(call, tuple))
    assert ctx.attachments == []
    assert all(reply[0] != "media_group" for reply in ctx.replies)
    assert ctx.replies[-1][0] == "parts"
    parts = ctx.replies[-1][1]
    assert parts[0] == {"id": "part_1", "type": "text", "format": "markdown", "text": "## Positive prompt"}
    assert parts[1] == {"id": "part_2", "type": "text", "format": "plain", "text": generated}
    assert parts[2] == {"id": "part_3", "type": "text", "format": "markdown", "text": "Saved to the current session recipe."}
    assert parts[3] == {
        "id": "part_4",
        "type": "command_buttons",
        "buttons": [
            {"label": "Edit recipe", "message": "@comfyui_agent:form"},
            {"label": "Run recipe", "message": "@comfyui_agent:run"},
        ],
    }
    body = json.dumps(parts)
    assert "```" in generated
    assert "```text" not in body
    assert "````text" not in body
    assert "Positive prompt saved" not in body
    assert ctx.run_store.metadata["comfyui_generation"]["llm_operation"] == saved["last_llm_operation"]


def test_saved_positive_prompt_blocks_validate_as_parts() -> None:
    parts = blocks_to_parts(comfy_agent.saved_positive_prompt_blocks("wrapped prompt"))

    assert parts[1] == {"id": "part_2", "type": "text", "format": "plain", "text": "wrapped prompt"}
    assert parts[3]["type"] == "command_buttons"
    assert parts[3]["buttons"][0]["message"] == "@comfyui_agent:form"
    assert parts[3]["buttons"][1]["message"] == "@comfyui_agent:run"


def test_default_respects_raw_and_llm_modes_and_generates(tmp_path: Path):
    raw_ctx = FakeCtx(tmp_path, action_id="default", text="raw cat")
    raw_ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))
    run(comfy_agent.run(raw_ctx))
    assert raw_ctx.state.get(comfy_agent.RECIPE_KEY)["values"]["positive_prompt"] == "raw cat"
    assert raw_ctx.llm.calls == []

    llm_ctx = FakeCtx(tmp_path, action_id="default", text="make a cat")
    llm_ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))
    run(comfy_agent.run(llm_ctx))
    assert llm_ctx.state.get(comfy_agent.RECIPE_KEY)["user_prompt"] == "make a cat"
    assert llm_ctx.state.get(comfy_agent.RECIPE_KEY)["values"]["positive_prompt"] == "cinematic cat"


@pytest.mark.parametrize("action_id", ["fresh", "refine"])
def test_fresh_and_refine_auto_run_true_enter_generation_pipeline(tmp_path: Path, action_id: str):
    ctx = FakeCtx(tmp_path, action_id=action_id, text="make a cat")
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))

    run(comfy_agent.run(ctx))

    saved = ctx.state.get(comfy_agent.RECIPE_KEY)
    assert saved["last_llm_operation"] == action_id
    assert any(call[0] == "submit_workflow" for call in ctx.calls if isinstance(call, tuple))
    assert ctx.run_store.metadata["comfyui_generation"]["llm_operation"] == action_id


def test_run_action_does_not_modify_prompt_or_parameters(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="run")
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "llm")
    recipe["values"]["positive_prompt"] = "existing"
    recipe["user_prompt"] = "old user prompt"
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))

    saved = ctx.state.get(comfy_agent.RECIPE_KEY)
    assert saved["values"]["positive_prompt"] == "existing"
    assert saved["user_prompt"] == "old user prompt"
    assert ctx.llm.calls == []
    assert "llm_operation" not in ctx.run_store.metadata["comfyui_generation"]
    assert any(call[0] == "submit_workflow" for call in ctx.calls if isinstance(call, tuple))


def test_run_action_with_empty_positive_prompt_returns_clear_error_before_submit(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="run")
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))

    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.run(ctx))

    assert exc.value.code == "COMFYUI_RECIPE_INVALID"
    assert "positive_prompt" in exc.value.message
    assert not any(call[0] == "submit_workflow" for call in ctx.calls if isinstance(call, tuple))


def test_prompt_enhancer_empty_and_failure_do_not_fallback_raw(tmp_path: Path):
    empty = FakeCtx(tmp_path, action_id="llm", text="cat", llm=FakeLLM(text=""))
    empty.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))
    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.run(empty))
    assert exc.value.code == "COMFYUI_PROMPT_ENHANCER_FAILED"
    assert exc.value.detail["stage"] == "empty_output"
    assert exc.value.detail["reached_provider"] is True
    assert not any(call[0] == "submit_workflow" for call in empty.calls if isinstance(call, tuple))

    class ProviderError(RuntimeError):
        code = "FAKE_PROVIDER_FAILED"
        message = "provider failed before response"

    failed = FakeCtx(tmp_path, action_id="llm", text="cat", llm=FakeLLM(fail=True, error=ProviderError("provider failed before response")))
    failed.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))
    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.run(failed))
    assert exc.value.code == "COMFYUI_PROMPT_ENHANCER_FAILED"
    assert exc.value.detail["stage"] == "call_llm"
    assert exc.value.detail["inner_code"] == "FAKE_PROVIDER_FAILED"
    assert exc.value.detail["reached_provider"] is True


def test_prompt_enhancer_template_failure_does_not_call_llm(tmp_path: Path):
    llm = FakeLLM()
    ctx = FakeCtx(tmp_path, action_id="llm", text="cat", llm=llm, config={"llm_refine_user_template": "{missing_key}"})
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))

    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.run(ctx))

    assert exc.value.detail["stage"] == "render_template"
    assert exc.value.detail["reached_provider"] is False
    assert llm.calls == []
    assert ctx.run_store.metadata["comfyui_prompt_enhancer_error"]["stage"] == "render_template"


def test_unload_failure_warns_but_generation_continues(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="llm", text="cat", llm=FakeLLM(unload_ok=False))
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))

    run(comfy_agent.run(ctx))

    assert any(call[0] == "submit_workflow" for call in ctx.calls if isinstance(call, tuple))


def test_workflow_fill_mapping_writes_copy_and_leaves_source_unchanged(tmp_path: Path):
    ctx = FakeCtx(tmp_path)
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "raw")
    recipe["values"]["positive_prompt"] = "cat"
    recipe["values"]["steps"] = 44
    source = Path(ctx.scan["workflows_dir"]) / "txt2img.workflow.json"
    before = source.read_text(encoding="utf-8")

    filled = comfy_agent.build_workflow_from_recipe(recipe, READY_PRESET, ctx.scan)

    assert filled["6"]["inputs"]["text"] == "cat"
    assert filled["3"]["inputs"]["steps"] == 44
    assert source.read_text(encoding="utf-8") == before


def test_workflow_fill_validation_errors(tmp_path: Path):
    ctx = FakeCtx(tmp_path)
    recipe = comfy_agent.recipe_from_preset(READY_PRESET, "raw")
    recipe["values"]["positive_prompt"] = "cat"
    missing_mapping = {**READY_PRESET, "parameters": [{**READY_PRESET["parameters"][0], "mapping": None}]}
    with pytest.raises(comfy_agent.ComfyAgentError):
        comfy_agent.validate_generation_recipe(recipe, missing_mapping, {**missing_mapping, "valid": True}, action_mode="raw")

    bad_node = {**READY_PRESET, "parameters": [{**READY_PRESET["parameters"][0], "mapping": {"node_id": "999", "input_path": ["inputs", "text"]}}]}
    with pytest.raises(comfy_agent.ComfyAgentError):
        comfy_agent.build_workflow_from_recipe(recipe, bad_node, ctx.scan)

    bad_path = {**READY_PRESET, "parameters": [{**READY_PRESET["parameters"][0], "mapping": {"node_id": "6", "input_path": ["inputs", "missing"]}}]}
    with pytest.raises(comfy_agent.ComfyAgentError):
        comfy_agent.build_workflow_from_recipe(recipe, bad_path, ctx.scan)


def test_generation_polls_fetches_saves_gallery_and_metadata(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="raw", text="cat")
    ctx.statuses = [
        {"prompt_id": "prompt-1", "status": "queued", "completed": False, "failed": False, "queue_position": 2, "outputs": {"images": []}},
        {"prompt_id": "prompt-1", "status": "running", "completed": False, "failed": False, "outputs": {"images": []}},
        completed_status(),
    ]
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))

    run(comfy_agent.run(ctx))

    assert ctx.calls.count("get_prompt_status") == 3
    assert any(call[0] == "fetch_image" for call in ctx.calls if isinstance(call, tuple))
    assert ctx.attachments[0]["url"].startswith("/api/attachments/")
    assert ctx.replies[-1][0] == "media_group"
    metadata = ctx.replies[-1][2]["metadata"]["comfyui_generation"]
    assert metadata["kind"] == "comfyui_generation"
    assert metadata["output_attachment_ids"] == ["att-0"]
    assert "comfyui_generation" in ctx.run_store.metadata
    labels = [step.label for step in ctx.run.steps]
    assert "Wait for generation" in labels
    assert "Save attachments" in labels


def test_generation_filters_temp_and_input_images_from_gallery(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="raw", text="cat")
    ctx.statuses = [
        {
            "prompt_id": "prompt-1",
            "status": "completed",
            "completed": True,
            "failed": False,
            "outputs": {
                "images": [
                    {"filename": "ComfyUI_temp_abc_00001_.png", "type": "temp", "subfolder": ""},
                    {"filename": "input.png", "type": "input", "subfolder": ""},
                    {"filename": "ComfyUI_temp_fallback_00002_.png", "type": "output", "subfolder": ""},
                    {"filename": "out.png", "type": "output", "subfolder": ""},
                ]
            },
        }
    ]
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))

    run(comfy_agent.run(ctx))

    fetch_calls = [call for call in ctx.calls if isinstance(call, tuple) and call[0] == "fetch_image"]
    assert [call[1]["filename"] for call in fetch_calls] == ["out.png"]
    assert ctx.replies[-1][0] == "media_group"
    assert len(ctx.replies[-1][1]) == 1
    metadata = ctx.run_store.metadata["comfyui_generation"]
    assert metadata["output_attachment_ids"] == ["att-0"]
    assert metadata["output_image_count"] == 1
    assert metadata["ignored_temp_image_count"] == 2
    assert metadata["ignored_input_image_count"] == 1
    assert metadata["image_filter"] == "output_only"
    assert ctx.attachments[0]["metadata"]["comfyui_image_type"] == "output"
    assert ctx.attachments[0]["metadata"]["source"] == "comfyui"
    assert ctx.attachments[0]["metadata"]["prompt_id"] == "prompt-1"
    assert ctx.attachments[0]["metadata"]["preset_id"] == "txt2img_basic"
    assert ctx.attachments[0]["metadata"]["workflow_file_name"] == "txt2img.workflow.json"


def test_generation_only_temp_images_fails_without_saving_gallery(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="raw", text="cat")
    ctx.statuses = [
        {
            "prompt_id": "prompt-1",
            "status": "completed",
            "completed": True,
            "failed": False,
            "outputs": {"images": [{"filename": "ComfyUI_temp_abc_00001_.png", "type": "temp", "subfolder": ""}]},
        }
    ]
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))

    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.run(ctx))

    assert exc.value.code == "COMFYUI_ONLY_TEMP_IMAGES"
    assert "SaveImage" in exc.value.message
    assert ctx.attachments == []
    assert all(reply[0] != "media_group" for reply in ctx.replies)
    assert ctx.run_store.metadata["comfyui_generation"]["ignored_temp_image_count"] == 1


def test_generation_missing_image_type_treats_as_output_with_warning(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="raw", text="cat")
    ctx.statuses = [
        {
            "prompt_id": "prompt-1",
            "status": "completed",
            "completed": True,
            "failed": False,
            "outputs": {"images": [{"filename": "legacy.png", "subfolder": ""}]},
        }
    ]
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))

    run(comfy_agent.run(ctx))

    metadata = ctx.run_store.metadata["comfyui_generation"]
    assert metadata["output_image_count"] == 1
    assert "image_filter_warnings" in metadata
    assert ctx.attachments[0]["metadata"]["comfyui_image_type"] == "output"


def test_free_comfyui_memory_after_generation_runs_after_saving_and_is_best_effort(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="raw", text="cat", config={"free_comfyui_memory_after_generation": True})
    ctx.free_memory_result = {
        "ok": False,
        "requested": {"unload_models": True, "free_memory": True},
        "status_code": 404,
        "error": {"code": "COMFYUI_FREE_MEMORY_FAILED", "message": "unsupported"},
    }
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))

    run(comfy_agent.run(ctx))

    save_index = next(index for index, call in enumerate(ctx.calls) if isinstance(call, tuple) and call[0] == "fetch_image")
    free_index = next(index for index, call in enumerate(ctx.calls) if isinstance(call, tuple) and call[0] == "free_memory")
    assert free_index > save_index
    assert ctx.replies[-1][0] == "media_group"
    release = ctx.run_store.metadata["comfyui_memory_release"]
    assert release["enabled"] is True
    assert release["attempted"] is True
    assert release["success"] is False
    assert release["status_code"] == 404
    labels = [step.label for step in ctx.run.steps]
    assert "Free ComfyUI memory" in labels


def test_free_comfyui_memory_not_called_for_prompt_inspection_or_validation_failure(tmp_path: Path):
    inspect_ctx = FakeCtx(tmp_path, action_id="llm", text="cat", config={"auto_run_after_llm_prompt": False, "free_comfyui_memory_after_generation": True})
    inspect_ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))

    run(comfy_agent.run(inspect_ctx))

    assert not any(isinstance(call, tuple) and call[0] == "free_memory" for call in inspect_ctx.calls)

    invalid_ctx = FakeCtx(tmp_path, action_id="raw", text="cat", config={"free_comfyui_memory_after_generation": True})
    invalid_ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))
    invalid_ctx.load_preset_result = {
        "found": True,
        "preset": {"id": READY_PRESET["preset_id"], "name": READY_PRESET["name"], "status": READY_PRESET["status"], "workflow": READY_PRESET["workflow"], "parameters": READY_PRESET["parameters"]},
        "validation": {**READY_PRESET, "valid": False, "errors": ["bad"]},
    }

    with pytest.raises(comfy_agent.ComfyAgentError):
        run(comfy_agent.run(invalid_ctx))

    assert not any(isinstance(call, tuple) and call[0] == "free_memory" for call in invalid_ctx.calls)


def test_free_comfyui_memory_called_after_submitted_failure_but_not_timeout(tmp_path: Path):
    failed = FakeCtx(tmp_path, action_id="raw", text="cat", config={"free_comfyui_memory_after_generation": True})
    failed.statuses = [{"prompt_id": "prompt-1", "status": "failed", "completed": False, "failed": True, "error": {"message": "node failed"}, "outputs": {"images": []}}]
    failed.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))
    with pytest.raises(comfy_agent.ComfyAgentError):
        run(comfy_agent.run(failed))
    assert any(isinstance(call, tuple) and call[0] == "free_memory" for call in failed.calls)

    timeout = FakeCtx(tmp_path, action_id="raw", text="cat", config={"free_comfyui_memory_after_generation": True})
    timeout.scan["config"] = {"poll_interval_seconds": 0, "max_wait_seconds": 0.001}
    timeout.statuses = [{"prompt_id": "prompt-1", "status": "running", "completed": False, "failed": False, "outputs": {"images": []}} for _ in range(100000)]
    timeout.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))
    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.run(timeout))
    assert exc.value.code == "COMFYUI_TIMEOUT"
    assert not any(isinstance(call, tuple) and call[0] == "free_memory" for call in timeout.calls)


def test_llm_unload_and_comfyui_free_memory_order(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="llm", text="cat", config={"free_comfyui_memory_after_generation": True})
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))

    run(comfy_agent.run(ctx))

    labels = [step.label for step in ctx.run.steps]
    assert labels.index("Unload prompt LLM") < labels.index("Submit workflow to ComfyUI")
    assert labels.index("Save attachments") < labels.index("Free ComfyUI memory")


def test_generation_failed_timeout_no_output_and_cancel_paths(tmp_path: Path):
    failed = FakeCtx(tmp_path, action_id="raw", text="cat")
    failed.statuses = [{"prompt_id": "prompt-1", "status": "failed", "completed": False, "failed": True, "error": {"message": "node failed"}, "outputs": {"images": []}}]
    failed.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))
    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.run(failed))
    assert exc.value.code == "COMFYUI_PROMPT_FAILED"

    no_output = FakeCtx(tmp_path, action_id="raw", text="cat")
    no_output.statuses = [{"prompt_id": "prompt-1", "status": "completed", "completed": True, "failed": False, "outputs": {"images": []}}]
    no_output.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))
    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.run(no_output))
    assert exc.value.code == "COMFYUI_OUTPUT_NOT_FOUND"

    cancelled = FakeCtx(tmp_path, action_id="raw", text="cat")
    cancelled.run_store.cancel_requested = True
    cancelled.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))
    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.run(cancelled))
    assert exc.value.code == "RUN_CANCELLED"
    assert "interrupt" in cancelled.calls


def test_status_and_scan_actions_return_details(tmp_path: Path):
    scan = {
        "presets": [READY_PRESET],
        "workflows": [
            {"file_name": "txt2img.workflow.json", "valid": True, "hash": "sha256:abc"},
            {"file_name": "bad.json", "valid": False, "format": "unknown", "errors": ["bad"]},
            {"file_name": "gui.json", "valid": False, "format": "unsupported_gui_format", "errors": ["gui"]},
        ],
        "duplicates": [{"hash": "sha256:x", "file_names": ["a.json", "b.json"]}],
        "missing_preset_workflows": [{"workflow_file_name": "new.json", "reason": "missing_preset"}],
        "created_draft_presets": [{"id": "auto_new", "file_name": "auto_new.yaml", "workflow_file_name": "new.json"}],
        "skipped_draft_presets": [{"workflow_file_name": "new.json", "reason": "preset_write_disabled"}],
        "workflows_dir": str(tmp_path / "workflows"),
        "presets_dir": str(tmp_path / "presets"),
        "config": {"poll_interval_seconds": 0, "max_wait_seconds": 1},
    }
    status_ctx = FakeCtx(tmp_path, action_id="status", scan=scan)
    scan_ctx = FakeCtx(tmp_path, action_id="scan_workflows", scan=scan)

    run(comfy_agent.run(status_ctx))
    run(comfy_agent.run(scan_ctx))

    assert "test_connection" in status_ctx.calls
    assert "Current input_mode" in status_ctx.replies[-1][1]
    assert "Auto-run after LLM prompt" in status_ctx.replies[-1][1]
    assert "Current positive_prompt empty" in status_ctx.replies[-1][1]
    assert "Created Draft Presets" in scan_ctx.replies[-1][1]
    assert "unsupported_gui_format" in scan_ctx.replies[-1][1]


def test_default_manifest_description_says_generate():
    manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / "agents" / "comfyui_agent" / "agent.yaml").read_text(encoding="utf-8"))
    default = next(action for action in manifest["actions"] if action["id"] == "default")

    assert "generate" in default["description"].lower()
    assert "without generating" not in default["description"].lower()


def test_comfyui_manifest_declares_llm_operation_config_and_actions():
    manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / "agents" / "comfyui_agent" / "agent.yaml").read_text(encoding="utf-8"))
    actions = {action["id"]: action for action in manifest["actions"]}
    schema = {field["name"]: field for field in manifest["config_schema"]}

    assert {"fresh", "refine"}.issubset(actions)
    assert schema["llm_operation_default"]["default"] == "refine"
    assert schema["llm_operation_default"]["options"] == ["refine", "fresh"]
    assert schema["free_comfyui_memory_after_generation"]["default"] is False
    assert schema["free_comfyui_memory_after_generation"]["type"] == "boolean"
    for key in [
        "llm_refine_system_prompt",
        "llm_refine_user_template",
        "llm_fresh_system_prompt",
        "llm_fresh_user_template",
    ]:
        assert key in schema
    assert "prompt_enhancer_system_prompt" not in schema
    assert "prompt_enhancer_user_template" not in schema
    assert "{positive_prompt}" in schema["llm_refine_user_template"]["default"]
    assert "{positive_prompt}" not in schema["llm_fresh_user_template"]["default"]


class IntegrationComfyRuntime:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls = []
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir(parents=True, exist_ok=True)
        (workflows_dir / "txt2img.workflow.json").write_text(json.dumps(WORKFLOW), encoding="utf-8")
        self.scan = {
            "presets": [READY_PRESET],
            "workflows": [{"file_name": "txt2img.workflow.json", "valid": True, "hash": "sha256:abc"}],
            "workflows_dir": str(workflows_dir),
            "presets_dir": str(tmp_path / "presets"),
            "config": {"poll_interval_seconds": 0, "max_wait_seconds": 1},
        }

    def scan_workflow_library(self, context=None):
        self.calls.append("scan_workflow_library")
        return self.scan

    def load_preset(self, preset_id=None, file_name=None, context=None):
        self.calls.append(("load_preset", preset_id))
        return {"found": True, "preset": READY_PRESET, "validation": READY_PRESET}

    def validate_preset(self, preset_id=None, file_name=None, preset=None, context=None):
        self.calls.append(("validate_preset", preset_id))
        return READY_PRESET

    def submit_workflow(self, workflow=None, context=None):
        self.calls.append(("submit_workflow", workflow))
        return {"accepted": True, "prompt_id": "prompt-1"}

    def get_prompt_status(self, prompt_id=None, context=None):
        self.calls.append(("get_prompt_status", prompt_id))
        return completed_status()

    def fetch_image(self, **kwargs):
        self.calls.append(("fetch_image", kwargs))
        return {"filename": kwargs["filename"], "mime_type": "image/png", "data_base64": "ZmFrZQ=="}


def comfy_fixture(tmp_path: Path, llm=None) -> tuple[PromptRuntimeFixture, IntegrationComfyRuntime]:
    fixture = PromptRuntimeFixture(llm=llm or FakeLLMRuntime(response="cinematic ocean"))
    comfy_runtime = IntegrationComfyRuntime(tmp_path)
    state_store = SessionAgentStateStore()
    fixture.agent_runner.runtime_registry.replace("comfyui", comfy_runtime)
    fixture.agent_runner.script_runner.runtime_registry.replace("comfyui", comfy_runtime)
    fixture.agent_runner.session_agent_state_store = state_store
    fixture.agent_runner.script_runner.session_agent_state_store = state_store
    return fixture, comfy_runtime


def add_model_profile(fixture: PromptRuntimeFixture) -> LLMProfileSchema:
    provider = ProviderProfileSchema(
        id="provider-comfy-test",
        name="Comfy Provider",
        provider="lm_studio",
        base_url="http://localhost:1234/v1",
    )
    fixture.provider_profiles.create(provider)
    profile = LLMProfileSchema(
        id="comfy-model-profile",
        alias="comfy_model_profile",
        name="Comfy Model",
        provider_profile_id=provider.id,
        provider=provider.provider,
        base_url=provider.base_url,
        model_id="comfy-provider-model",
    )
    fixture.llm_profiles.create(profile)
    return profile


def test_comfyui_agent_llm_action_uses_agent_config_model_profile_override(tmp_path: Path):
    llm = FakeLLMRuntime(response="cinematic ocean")
    fixture, comfy_runtime = comfy_fixture(tmp_path, llm=llm)
    profile = add_model_profile(fixture)
    fixture.agent_configs.set_config("comfyui_agent", runtime={"llm_profile_id": profile.id})
    session = fixture.sessions.create_session(default_agent_id="comfyui_agent")

    result = run_async(fixture.runtime.handle_input(session, "@comfyui_agent:llm 大海"))

    assert result.success is True
    assert len(llm.calls) == 1
    assert llm.calls[0]["model_config"]["model_id"] == "comfy-provider-model"
    assert llm.calls[0]["model_config"]["provider"] == "lm_studio"
    assert llm.calls[0]["model_config"]["base_url"] == "http://localhost:1234/v1"
    run_record = fixture.runs.get_run(result.run_id)
    assert run_record.metadata["llm_resolution"]["profile_id"] == profile.id
    assert run_record.metadata["llm_resolution"]["provider_profile_id"] == "provider-comfy-test"
    assert any(call[0] == "submit_workflow" for call in comfy_runtime.calls if isinstance(call, tuple))


def test_comfyui_agent_raw_and_run_actions_do_not_call_llm(tmp_path: Path):
    llm = FakeLLMRuntime(response="unused")
    fixture, _ = comfy_fixture(tmp_path, llm=llm)
    profile = add_model_profile(fixture)
    fixture.agent_configs.set_config("comfyui_agent", runtime={"llm_profile_id": profile.id})
    session = fixture.sessions.create_session(default_agent_id="comfyui_agent")

    raw_result = run_async(fixture.runtime.handle_input(session, "@comfyui_agent:raw ocean"))
    run_result = run_async(fixture.runtime.handle_input(session, "@comfyui_agent:run"))

    assert raw_result.success is True
    assert run_result.success is True
    assert llm.calls == []


def test_comfyui_agent_current_action_shortcuts_trigger_form_and_run(tmp_path: Path):
    llm = FakeLLMRuntime(response="unused")
    fixture, comfy_runtime = comfy_fixture(tmp_path, llm=llm)
    session = fixture.sessions.create_session(default_agent_id="comfyui_agent")

    form_result = run_async(fixture.runtime.handle_input(session, ":form"))
    raw_result = run_async(fixture.runtime.handle_input(session, ":raw ocean"))
    run_result = run_async(fixture.runtime.handle_input(session, ":run"))

    assert form_result.success is True
    assert raw_result.success is True
    assert run_result.success is True
    assert any(call[0] == "submit_workflow" for call in comfy_runtime.calls if isinstance(call, tuple))
    messages = fixture.messages.list_messages(session.session_id)
    assert text_part(messages[0])["text"] == ":form"
    assert messages[0].metadata["invocation"]["resolved_agent_id"] == "comfyui_agent"
    assert messages[0].metadata["invocation"]["resolved_action_id"] == "form"
    assert text_part(messages[2])["text"] == ":raw ocean"
    assert messages[2].metadata["invocation"]["args"] == "ocean"
    assert text_part(messages[4])["text"] == ":run"


def test_comfyui_raw_shortcut_matches_explicit_action_when_target_agent_is_same(tmp_path: Path):
    llm = FakeLLMRuntime(response="unused")
    shortcut_fixture, shortcut_runtime = comfy_fixture(tmp_path / "shortcut", llm=llm)
    explicit_fixture, explicit_runtime = comfy_fixture(tmp_path / "explicit", llm=FakeLLMRuntime(response="unused"))
    shortcut_session = shortcut_fixture.sessions.create_session(default_agent_id="comfyui_agent")
    explicit_session = explicit_fixture.sessions.create_session(default_agent_id="comfyui_agent")

    shortcut = run_async(shortcut_fixture.runtime.handle_input(shortcut_session, ":raw 大海"))
    explicit = run_async(explicit_fixture.runtime.handle_input(explicit_session, "@comfyui_agent:raw 大海"))

    assert shortcut.success is True
    assert explicit.success is True
    assert shortcut_fixture.runs.get_run(shortcut.run_id).target_id == explicit_fixture.runs.get_run(explicit.run_id).target_id
    assert shortcut_fixture.runs.get_run(shortcut.run_id).action_id == explicit_fixture.runs.get_run(explicit.run_id).action_id
    assert shortcut_fixture.runs.get_run(shortcut.run_id).metadata["args"] == explicit_fixture.runs.get_run(explicit.run_id).metadata["args"]
    assert any(call[0] == "submit_workflow" for call in shortcut_runtime.calls if isinstance(call, tuple))
    assert any(call[0] == "submit_workflow" for call in explicit_runtime.calls if isinstance(call, tuple))


def test_comfyui_agent_llm_resolution_failure_records_pre_provider_stage(tmp_path: Path):
    llm = FakeLLMRuntime(response="unused")
    fixture, _ = comfy_fixture(tmp_path, llm=llm)
    fixture.agent_configs.set_config("comfyui_agent", runtime={"llm_profile_id": "missing"})
    session = fixture.sessions.create_session(default_agent_id="comfyui_agent")

    result = run_async(fixture.runtime.handle_input(session, "@comfyui_agent:llm 大海"))

    assert result.success is False
    assert llm.calls == []
    run_record = fixture.runs.get_run(result.run_id)
    detail = run_record.metadata["comfyui_prompt_enhancer_error"]
    assert detail["stage"] == "resolve_llm"
    assert detail["reached_provider"] is False
    assert detail["inner_code"] == "LLM_PROFILE_NOT_FOUND"
