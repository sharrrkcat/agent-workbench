import asyncio
import json
from pathlib import Path

import pytest
import yaml

from agents.comfyui_agent import agent as comfy_agent


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
    def __init__(self, text="cinematic cat", fail=False, unload_ok=True):
        self.calls = []
        self.text_value = text
        self.fail = fail
        self.unload_ok = unload_ok

    async def text(self, **kwargs):
        self.calls.append(("text", kwargs))
        if self.fail:
            raise RuntimeError("no model")
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
            "prompt_enhancer_system_prompt": "Improve prompts.",
            "prompt_enhancer_user_template": "{user_input}\n{positive_prompt}\n{negative_prompt}\n{preset_id}\n{preset_name}\n{input_mode}",
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

    def capability(self, name):
        assert name == "comfyui"
        return FakeCapability(self)

    async def reply_markdown(self, value, **kwargs):
        self.replies.append(("markdown", value, kwargs))

    async def reply_blocks(self, blocks, **kwargs):
        self.replies.append(("rich_content", {"blocks": blocks}, kwargs))

    async def reply_images(self, images, **kwargs):
        self.replies.append(("image_gallery", images, kwargs))

    async def save_attachment_base64(self, data_base64, filename, mime_type, kind="file", metadata=None):
        attachment = {"id": f"att-{len(self.attachments)}", "url": f"/api/attachments/att-{len(self.attachments)}.png", "name": filename, "metadata": metadata or {}}
        self.attachments.append(attachment)
        return attachment


def completed_status():
    return {"prompt_id": "prompt-1", "status": "completed", "completed": True, "failed": False, "outputs": {"images": [{"filename": "out.png", "type": "output", "subfolder": ""}]}}


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("mode", ["llm", "raw"])
def test_new_session_recipe_uses_default_input_mode(tmp_path: Path, mode):
    ctx = FakeCtx(tmp_path, action_id="status", config={"default_input_mode": mode})

    recipe, preset, presets, state = run(comfy_agent.current_recipe(ctx))

    assert recipe["preset_id"] == "txt2img_basic"
    assert recipe["input_mode"] == mode
    assert "enhance" not in recipe
    assert recipe["values"]["steps"] == 30


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
    assert all(reply[0] != "image_gallery" for reply in ctx.replies)
    assert all(not any(block.get("type") == "action_form" for block in reply[1].get("blocks", [])) for reply in ctx.replies if reply[0] == "rich_content")


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
    assert all(reply[0] != "rich_content" for reply in ctx.replies)


def test_switch_only_changes_input_mode_and_does_not_generate(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="switch", text="raw")
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))

    run(comfy_agent.run(ctx))

    assert ctx.state.get(comfy_agent.RECIPE_KEY)["input_mode"] == "raw"
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


def test_llm_action_writes_user_prompt_enhances_without_changing_mode_and_generates(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="llm", text="make a cat")
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))

    run(comfy_agent.run(ctx))
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)

    assert saved["user_prompt"] == "make a cat"
    assert saved["values"]["positive_prompt"] == "cinematic cat"
    assert saved["input_mode"] == "raw"
    assert ctx.llm.calls[0][0] == "text"
    assert ("unload_model", {}) in ctx.llm.calls


def test_llm_auto_run_false_saves_positive_prompt_without_submitting(tmp_path: Path):
    ctx = FakeCtx(tmp_path, action_id="llm", text="make a cat", config={"auto_run_after_llm_prompt": False})
    ctx.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "raw"))

    run(comfy_agent.run(ctx))
    saved = ctx.state.get(comfy_agent.RECIPE_KEY)

    assert saved["user_prompt"] == "make a cat"
    assert saved["values"]["positive_prompt"] == "cinematic cat"
    assert saved["input_mode"] == "raw"
    assert [call[0] for call in ctx.llm.calls] == ["text"]
    assert not any(call[0] == "submit_workflow" for call in ctx.calls if isinstance(call, tuple))
    assert ctx.replies[-1][0] == "markdown"
    assert "Positive prompt saved" in ctx.replies[-1][1]


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
    assert exc.value.code == "COMFYUI_PROMPT_ENHANCER_EMPTY"
    assert not any(call[0] == "submit_workflow" for call in empty.calls if isinstance(call, tuple))

    failed = FakeCtx(tmp_path, action_id="llm", text="cat", llm=FakeLLM(fail=True))
    failed.state.set(comfy_agent.RECIPE_KEY, comfy_agent.recipe_from_preset(READY_PRESET, "llm"))
    with pytest.raises(comfy_agent.ComfyAgentError) as exc:
        run(comfy_agent.run(failed))
    assert exc.value.code == "COMFYUI_PROMPT_ENHANCER_FAILED"


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
    assert ctx.replies[-1][0] == "image_gallery"
    metadata = ctx.replies[-1][2]["metadata"]["comfyui_generation"]
    assert metadata["kind"] == "comfyui_generation"
    assert metadata["output_attachment_ids"] == ["att-0"]
    assert "comfyui_generation" in ctx.run_store.metadata
    labels = [step.label for step in ctx.run.steps]
    assert "Wait for generation" in labels
    assert "Save attachments" in labels


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
