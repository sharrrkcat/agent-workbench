from pathlib import Path

import pytest
import yaml

from agents.comfyui_agent import agent as comfy_agent


READY_PRESET = {
    "file_name": "txt2img.yaml",
    "preset_id": "txt2img_basic",
    "id": "txt2img_basic",
    "name": "Text to Image Basic",
    "valid": True,
    "status": "ready",
    "workflow": {"file_name": "txt2img.workflow.json", "hash": "sha256:abc"},
    "parameters": [
        {"name": "positive_prompt", "type": "textarea", "required": True, "default": ""},
        {"name": "steps", "type": "integer", "default": 30, "minimum": 1, "maximum": 150},
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
    "parameters": [{"name": "cfg", "type": "float", "default": 7.0}],
}


class FakeInput:
    def __init__(self, text="", prefill=None):
        self.text = text
        self.prefill = prefill or {}
        self.form_id = ""
        self.source_message_id = ""


class FakeState:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value


class FakeCapability:
    def __init__(self, calls, scan):
        self.calls = calls
        self.scan = scan

    async def scan_workflow_library(self):
        self.calls.append("scan_workflow_library")
        return Result(self.scan)

    async def load_preset(self, preset_id=None, file_name=None):
        self.calls.append("load_preset")
        preset = OTHER_PRESET if preset_id == "other" else READY_PRESET
        return Result({"found": True, "preset": {"id": preset["preset_id"], "workflow": preset["workflow"], "parameters": preset["parameters"]}, "validation": preset})

    async def validate_preset(self, preset_id=None, file_name=None, preset=None):
        self.calls.append("validate_preset")
        return Result({"valid": True, "errors": [], "warnings": []})

    async def test_connection(self):
        self.calls.append("test_connection")
        return Result({"reachable": False, "summary": "ComfyUI is unreachable."})

    async def submit_workflow(self, *args, **kwargs):
        self.calls.append("submit_workflow")
        return Result({"accepted": True})


class Result:
    def __init__(self, data):
        self.success = True
        self.data = data
        self.error = ""


class FakeCtx:
    def __init__(self, action_id="default", text="", prefill=None, config=None, scan=None):
        self.action_id = action_id
        self.input = FakeInput(text, prefill)
        self.config = config or {"default_input_mode": "llm", "default_preset_id": "txt2img_basic"}
        self.state = FakeState()
        self.calls = []
        self.replies = []
        self.scan = scan or {"presets": [READY_PRESET, OTHER_PRESET], "workflows": [], "workflows_dir": "wf", "presets_dir": "ps"}

    def capability(self, name):
        assert name == "comfyui"
        return FakeCapability(self.calls, self.scan)

    async def reply_markdown(self, value):
        self.replies.append(("markdown", value))

    async def reply_blocks(self, blocks):
        self.replies.append(("rich_content", {"blocks": blocks}))


def run(coro):
    import asyncio

    return asyncio.run(coro)


@pytest.mark.parametrize("mode", ["llm", "raw"])
def test_new_session_recipe_uses_default_input_mode(mode):
    ctx = FakeCtx(action_id="status", config={"default_input_mode": mode, "default_preset_id": "txt2img_basic"})

    recipe, preset, presets, state = run(comfy_agent.current_recipe(ctx))

    assert recipe["preset_id"] == "txt2img_basic"
    assert recipe["input_mode"] == mode
    assert "enhance" not in recipe
    assert recipe["values"]["steps"] == 30


def test_save_form_same_preset_updates_recipe_values_only():
    ctx = FakeCtx(action_id="save_recipe_from_form", prefill={"preset_id": "txt2img_basic", "input_mode": "llm", "positive_prompt": "cat", "steps": 44})
    recipe = comfy_agent.recipe_from_preset({"id": "txt2img_basic", "workflow": READY_PRESET["workflow"], "parameters": READY_PRESET["parameters"]}, "llm")
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)

    assert saved["preset_id"] == "txt2img_basic"
    assert saved["values"]["positive_prompt"] == "cat"
    assert saved["values"]["steps"] == 44


def test_save_form_changed_preset_replaces_recipe_and_drops_old_fields(tmp_path: Path):
    preset_file = tmp_path / "preset.yaml"
    preset_file.write_text(yaml.safe_dump({"id": "txt2img_basic"}), encoding="utf-8")
    ctx = FakeCtx(action_id="save_recipe_from_form", prefill={"preset_id": "other", "input_mode": "raw", "cfg": 8.0})
    recipe = comfy_agent.recipe_from_preset({"id": "txt2img_basic", "workflow": READY_PRESET["workflow"], "parameters": READY_PRESET["parameters"]}, "llm")
    recipe["values"]["positive_prompt"] = "old"
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)

    assert saved["preset_id"] == "other"
    assert saved["workflow_file_name"] == "other.workflow.json"
    assert saved["input_mode"] == "raw"
    assert saved["values"] == {"cfg": 8.0}
    assert preset_file.read_text(encoding="utf-8") == yaml.safe_dump({"id": "txt2img_basic"})


def test_switch_raw_and_llm_actions_update_expected_recipe_fields():
    ctx = FakeCtx(action_id="switch", text="raw")
    recipe = comfy_agent.recipe_from_preset({"id": "txt2img_basic", "workflow": READY_PRESET["workflow"], "parameters": READY_PRESET["parameters"]}, "llm")
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))
    assert ctx.state.get(comfy_agent.RECIPE_KEY)["input_mode"] == "raw"

    ctx.action_id = "raw"
    ctx.input.text = "raw prompt"
    run(comfy_agent.run(ctx))
    assert ctx.state.get(comfy_agent.RECIPE_KEY)["values"]["positive_prompt"] == "raw prompt"
    assert ctx.state.get(comfy_agent.RECIPE_KEY)["input_mode"] == "raw"

    ctx.action_id = "llm"
    ctx.input.text = "make a cat"
    run(comfy_agent.run(ctx))
    assert ctx.state.get(comfy_agent.RECIPE_KEY)["user_prompt"] == "make a cat"
    assert ctx.state.get(comfy_agent.RECIPE_KEY)["input_mode"] == "raw"


def test_default_action_respects_llm_and_raw_input_modes():
    llm_ctx = FakeCtx(action_id="default", text="make a cat")
    llm_recipe = comfy_agent.recipe_from_preset({"id": "txt2img_basic", "workflow": READY_PRESET["workflow"], "parameters": READY_PRESET["parameters"]}, "llm")
    llm_ctx.state.set(comfy_agent.RECIPE_KEY, llm_recipe)
    run(comfy_agent.run(llm_ctx))
    assert llm_ctx.state.get(comfy_agent.RECIPE_KEY)["user_prompt"] == "make a cat"

    raw_ctx = FakeCtx(action_id="default", text="raw cat")
    raw_recipe = comfy_agent.recipe_from_preset({"id": "txt2img_basic", "workflow": READY_PRESET["workflow"], "parameters": READY_PRESET["parameters"]}, "raw")
    raw_ctx.state.set(comfy_agent.RECIPE_KEY, raw_recipe)
    run(comfy_agent.run(raw_ctx))
    assert raw_ctx.state.get(comfy_agent.RECIPE_KEY)["values"]["positive_prompt"] == "raw cat"


def test_run_action_is_dry_run_and_does_not_submit_workflow():
    ctx = FakeCtx(action_id="run")
    recipe = comfy_agent.recipe_from_preset({"id": "txt2img_basic", "workflow": READY_PRESET["workflow"], "parameters": READY_PRESET["parameters"]}, "llm")
    ctx.state.set(comfy_agent.RECIPE_KEY, recipe)

    run(comfy_agent.run(ctx))

    assert "validate_preset" in ctx.calls
    assert "submit_workflow" not in ctx.calls
    assert ctx.replies[-1][0] == "markdown"


def test_form_action_outputs_action_form_and_submit_accepts_prefill():
    ctx = FakeCtx(action_id="form")

    run(comfy_agent.run(ctx))

    blocks = ctx.replies[-1][1]["blocks"]
    form = blocks[1]
    assert form["type"] == "action_form"
    assert form["submit"]["action_id"] == "save_recipe_from_form"
    assert any(field["name"] == "preset_id" for field in form["fields"])


def test_status_and_scan_actions_return_summaries():
    status_ctx = FakeCtx(action_id="status")
    scan_ctx = FakeCtx(action_id="scan_workflows")

    run(comfy_agent.run(status_ctx))
    run(comfy_agent.run(scan_ctx))

    assert "test_connection" in status_ctx.calls
    assert "scan_workflow_library" in status_ctx.calls
    assert "scan_workflow_library" in scan_ctx.calls
    assert "Real ComfyUI generation is not implemented" in status_ctx.replies[-1][1]
