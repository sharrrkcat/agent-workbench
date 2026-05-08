import asyncio
import copy
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RECIPE_KEY = "comfyui_recipe"
INPUT_MODES = {"llm", "raw"}


class ComfyAgentError(RuntimeError):
    def __init__(self, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail or {}


async def run(ctx):
    action = ctx.action_id or "default"
    if action == "form":
        recipe, preset, presets, recipe_state = await current_recipe(ctx)
        await ctx.reply_blocks([_summary_block(recipe_state), recipe_to_form(recipe, preset, presets)])
        return
    if action == "save_recipe_from_form":
        await save_recipe_from_form(ctx)
        return
    if action == "switch":
        await switch_mode(ctx)
        return
    if action in {"default", "raw", "llm", "run"}:
        await execute_generation(ctx, mode_source=action, user_input=ctx.input.text.strip())
        return
    if action == "presets":
        await list_presets(ctx)
        return
    if action == "scan_workflows":
        await scan_workflows(ctx)
        return
    if action == "status":
        await status_action(ctx)
        return
    await execute_generation(ctx, mode_source="default", user_input=ctx.input.text.strip())


async def execute_generation(ctx, recipe: dict | None = None, mode_source: str = "default", user_input: str | None = None) -> dict:
    scan = await call_comfy(ctx, "scan_workflow_library")
    recipe, preset, presets, state = await current_recipe(ctx, scan) if recipe is None else (recipe, _preset_by_id(scan.get("presets") or [], recipe.get("preset_id")), scan.get("presets") or [], {"status": "loaded"})
    if recipe is None:
        raise ComfyAgentError("COMFYUI_RECIPE_UNAVAILABLE", state.get("message") or "Configure at least one ready ComfyUI preset first.")

    step = _start_step(ctx, "Prepare recipe", "Loading current session recipe.")
    recipe = copy.deepcopy(recipe)
    action_mode = _generation_input_mode(recipe, mode_source)
    if mode_source == "raw":
        recipe.setdefault("values", {})["positive_prompt"] = user_input or ""
    elif mode_source == "llm":
        recipe["user_prompt"] = user_input or ""
    elif mode_source == "default":
        if action_mode == "raw":
            recipe.setdefault("values", {})["positive_prompt"] = user_input or ""
        else:
            recipe["user_prompt"] = user_input or ""
    recipe["updated_at"] = _now()
    save_recipe(ctx, recipe)
    _complete_step(ctx, step, f"Recipe prepared with input_mode={action_mode}.")

    step = _start_step(ctx, "Validate preset", "Checking preset, workflow, and required values.")
    loaded = await call_comfy(ctx, "load_preset", preset_id=recipe["preset_id"])
    preset_data = loaded.get("preset") or {}
    validation = loaded.get("validation") or await call_comfy(ctx, "validate_preset", preset_id=recipe["preset_id"])
    validate_generation_recipe(recipe, preset_data, validation, action_mode=action_mode)
    _complete_step(ctx, step, f"Preset `{recipe['preset_id']}` is ready.")

    if action_mode == "llm":
        step = _start_step(ctx, "Enhance prompt with LLM", "Generating positive prompt.")
        positive_prompt = await enhance_positive_prompt(ctx, recipe, preset_data, user_input or recipe.get("user_prompt") or "")
        recipe.setdefault("values", {})["positive_prompt"] = positive_prompt
        recipe["updated_at"] = _now()
        save_recipe(ctx, recipe)
        _complete_step(ctx, step, "Positive prompt generated.")

    step = _start_step(ctx, "Build workflow", "Applying recipe values to workflow copy.")
    workflow = build_workflow_from_recipe(recipe, preset_data, scan)
    _complete_step(ctx, step, "Workflow JSON prepared.")

    if action_mode == "llm" and bool(ctx.config.get("unload_llm_before_generation", True)):
        step = _start_step(ctx, "Unload prompt LLM", "Best-effort unload before ComfyUI generation.")
        unload = await _unload_llm(ctx)
        message = "Unload requested." if unload.get("ok") else f"Unload warning: {unload.get('error') or unload.get('message') or 'unsupported'}"
        _complete_step(ctx, step, message)

    step = _start_step(ctx, "Submit workflow to ComfyUI", "Submitting workflow.")
    submitted = await call_comfy(ctx, "submit_workflow", workflow=workflow)
    if not submitted.get("accepted"):
        error = submitted.get("error") or {}
        _fail_step(ctx, step, error.get("code") or "COMFYUI_PROMPT_REJECTED", error.get("message") or "ComfyUI rejected the workflow.")
        raise ComfyAgentError(error.get("code") or "COMFYUI_PROMPT_REJECTED", error.get("message") or "ComfyUI rejected the workflow.", submitted)
    prompt_id = submitted.get("prompt_id") or ""
    _complete_step(ctx, step, f"Submitted prompt `{prompt_id}`.")

    status = await poll_prompt_status(ctx, prompt_id, scan)
    images = collect_status_images(status)
    if not images:
        raise ComfyAgentError("COMFYUI_OUTPUT_NOT_FOUND", "ComfyUI completed but returned no image outputs.", {"prompt_id": prompt_id, "status": status})

    step = _start_step(ctx, "Fetch output images", f"Fetching {len(images)} image output(s).")
    fetched = []
    for image in images:
        fetched.append(await call_comfy(ctx, "fetch_image", filename=image["filename"], subfolder=image.get("subfolder", ""), type=image.get("type", "output"), as_base64=True))
    _complete_step(ctx, step, f"Fetched {len(fetched)} image output(s).")

    step = _start_step(ctx, "Save attachments", "Saving generated images locally.")
    attachments = []
    for source, payload in zip(images, fetched):
        attachments.append(await save_image_attachment(ctx, payload, source, recipe, prompt_id))
    _complete_step(ctx, step, f"Saved {len(attachments)} local attachment(s).")

    metadata = generation_metadata(recipe, preset_data, prompt_id, attachments)
    _record_run_metadata(ctx, metadata)
    gallery = [
        {
            "url": attachment["url"],
            "alt": f"ComfyUI image from {recipe.get('preset_id')}",
            "title": attachment.get("name") or "ComfyUI output",
        }
        for attachment in attachments
    ]
    step = _start_step(ctx, "Render result", "Rendering image gallery.")
    await _reply_images(ctx, gallery, metadata={"comfyui_generation": metadata})
    _complete_step(ctx, step, "Image gallery rendered.")
    return metadata


async def poll_prompt_status(ctx, prompt_id: str, scan: dict) -> dict:
    config = scan.get("config") if isinstance(scan.get("config"), dict) else {}
    interval = max(0.0, float(config.get("poll_interval_seconds", 1.0)))
    timeout = max(1.0, float(config.get("max_wait_seconds", 300)))
    started = asyncio.get_running_loop().time()
    step = _start_step(ctx, "Wait for generation", "queued")
    last_status = None
    try:
        while True:
            if _cancel_requested(ctx):
                await _best_effort_interrupt(ctx)
                _fail_step(ctx, step, "RUN_CANCELLED", "Generation cancelled.")
                raise ComfyAgentError("RUN_CANCELLED", "Generation cancelled.")
            status = await call_comfy(ctx, "get_prompt_status", prompt_id=prompt_id)
            last_status = status
            message = _status_message(status)
            _update_step(ctx, step, message)
            if status.get("completed"):
                _complete_step(ctx, step, "completed")
                return status
            if status.get("failed") or status.get("status") == "failed":
                _fail_step(ctx, step, "COMFYUI_PROMPT_FAILED", _status_error_message(status))
                raise ComfyAgentError("COMFYUI_PROMPT_FAILED", _status_error_message(status), {"status": status})
            if asyncio.get_running_loop().time() - started >= timeout:
                _fail_step(ctx, step, "COMFYUI_TIMEOUT", "Timed out waiting for ComfyUI generation.")
                raise ComfyAgentError("COMFYUI_TIMEOUT", "Timed out waiting for ComfyUI generation.", {"prompt_id": prompt_id, "last_status": last_status})
            await asyncio.sleep(interval)
    except Exception:
        if _cancel_requested(ctx):
            await _best_effort_interrupt(ctx)
        raise


async def enhance_positive_prompt(ctx, recipe: dict, preset: dict, user_input: str) -> str:
    values = recipe.get("values") or {}
    system = str(ctx.config.get("prompt_enhancer_system_prompt") or "").strip()
    template = str(ctx.config.get("prompt_enhancer_user_template") or "{user_input}").strip()
    prompt = template.format(
        user_input=user_input,
        positive_prompt=values.get("positive_prompt") or "",
        negative_prompt=values.get("negative_prompt") or "",
        preset_id=recipe.get("preset_id") or "",
        preset_name=preset.get("name") or recipe.get("preset_id") or "",
        input_mode="llm",
    )
    try:
        text = await ctx.llm.text(system=system, user=prompt)
    except Exception as exc:
        raise ComfyAgentError(
            "COMFYUI_PROMPT_ENHANCER_FAILED",
            "LLM prompt enhancer failed. Configure an LLM, switch to raw mode, or use `@comfyui_agent:raw`.",
            {"error": str(exc)},
        ) from exc
    text = _strip_code_fence(str(text or "")).strip()
    if not text:
        raise ComfyAgentError(
            "COMFYUI_PROMPT_ENHANCER_EMPTY",
            "LLM prompt enhancer returned empty text. Configure an LLM, switch to raw mode, or use `@comfyui_agent:raw`.",
        )
    return text


def validate_generation_recipe(recipe: dict, preset: dict, validation: dict, action_mode: str = "raw") -> None:
    if not validation.get("valid"):
        raise ComfyAgentError("COMFYUI_PRESET_INVALID", "Selected ComfyUI preset is invalid.", {"errors": validation.get("errors") or []})
    if validation.get("status") != "ready" or preset.get("status") == "needs_mapping":
        raise ComfyAgentError("COMFYUI_PRESET_NOT_READY", "Selected ComfyUI preset needs mapping and cannot generate yet.")
    values = recipe.get("values") or {}
    for parameter in preset.get("parameters") or []:
        name = parameter.get("name")
        if not name:
            continue
        if parameter.get("required") and values.get(name) in (None, "") and not (action_mode == "llm" and name == "positive_prompt"):
            raise ComfyAgentError("COMFYUI_RECIPE_INVALID", f"Missing required recipe value: {name}")
        if parameter.get("mapping") is None:
            raise ComfyAgentError("COMFYUI_PRESET_INVALID", f"Ready preset parameter is missing mapping: {name}")
        if name in values and not _value_matches_type(values[name], parameter.get("type")):
            raise ComfyAgentError("COMFYUI_RECIPE_INVALID", f"Recipe value type does not match preset field: {name}")


def build_workflow_from_recipe(recipe: dict, preset: dict, scan: dict) -> dict:
    workflow_ref = preset.get("workflow") or {}
    file_name = workflow_ref.get("file_name") or recipe.get("workflow_file_name") or ""
    if not _is_safe_basename(file_name):
        raise ComfyAgentError("COMFYUI_WORKFLOW_INVALID", "workflow.file_name must be a basename.")
    path = Path(scan.get("workflows_dir") or "") / file_name
    workflow = json.loads(path.read_text(encoding="utf-8"))
    workflow_copy = copy.deepcopy(workflow)
    values = recipe.get("values") or {}
    for parameter in preset.get("parameters") or []:
        name = parameter.get("name")
        mapping = parameter.get("mapping")
        if not name or name not in values:
            continue
        if not isinstance(mapping, dict):
            raise ComfyAgentError("COMFYUI_PRESET_INVALID", f"Missing mapping for parameter: {name}")
        _write_mapping(workflow_copy, mapping, values[name], name)
    return workflow_copy


def _write_mapping(workflow: dict, mapping: dict, value: Any, parameter_name: str) -> None:
    node_id = str(mapping.get("node_id") or "")
    input_path = mapping.get("input_path")
    if node_id not in workflow:
        raise ComfyAgentError("COMFYUI_WORKFLOW_INVALID", f"Mapping node does not exist for {parameter_name}: {node_id}")
    if not isinstance(input_path, list) or not input_path:
        raise ComfyAgentError("COMFYUI_WORKFLOW_INVALID", f"Mapping input_path is invalid for {parameter_name}.")
    current = workflow[node_id]
    for segment in input_path[:-1]:
        if not isinstance(current, dict) or segment not in current:
            raise ComfyAgentError("COMFYUI_WORKFLOW_INVALID", f"Mapping input_path cannot be located for {parameter_name}: {input_path}")
        current = current[segment]
    last = input_path[-1]
    if not isinstance(current, dict) or last not in current:
        raise ComfyAgentError("COMFYUI_WORKFLOW_INVALID", f"Mapping input_path cannot be written for {parameter_name}: {input_path}")
    current[last] = value


async def save_image_attachment(ctx, payload: dict, image_ref: dict, recipe: dict, prompt_id: str) -> dict:
    filename = _sanitize_filename(payload.get("filename") or image_ref.get("filename") or "comfyui-output.png")
    mime_type = payload.get("mime_type") or "image/png"
    metadata = {
        "source": "comfyui",
        "prompt_id": prompt_id,
        "preset_id": recipe.get("preset_id"),
        "workflow_file_name": recipe.get("workflow_file_name"),
        "comfyui_image": {key: image_ref.get(key) for key in ("filename", "subfolder", "type", "node_id", "node_label") if image_ref.get(key) is not None},
    }
    if payload.get("data_base64"):
        return await ctx.save_attachment_base64(payload["data_base64"], filename=filename, mime_type=mime_type, kind="image", metadata=metadata)
    if payload.get("bytes"):
        return await ctx.save_attachment_bytes(payload["bytes"], filename=filename, mime_type=mime_type, kind="image", metadata=metadata)
    raise ComfyAgentError("COMFYUI_OUTPUT_NOT_FOUND", f"Fetched image has no binary payload: {filename}")


async def save_recipe_from_form(ctx):
    prefill = dict(ctx.input.prefill or {})
    recipe, preset, presets, state = await current_recipe(ctx)
    if recipe is None:
        await ctx.reply_markdown(_no_recipe_markdown(state))
        return
    next_recipe, next_preset, switched, errors = apply_form_to_recipe(recipe, prefill, presets)
    if errors:
        await ctx.reply_markdown("# Recipe form was not saved\n\n" + "\n".join(f"- {error}" for error in errors))
        return
    save_recipe(ctx, next_recipe)
    title = "Preset switched and recipe saved" if switched else "Recipe saved"
    await ctx.reply_blocks([
        {"type": "markdown", "text": _recipe_markdown(next_recipe, title, "Form values update only this session recipe, not preset files. No generation was submitted.")},
        recipe_to_form(next_recipe, next_preset, presets),
    ])


async def switch_mode(ctx):
    mode = ctx.input.text.strip().lower()
    if mode not in INPUT_MODES:
        await ctx.reply_markdown("Use `@comfyui_agent:switch llm` or `@comfyui_agent:switch raw`.")
        return
    recipe, preset, presets, state = await current_recipe(ctx)
    if recipe is None:
        await ctx.reply_markdown(_no_recipe_markdown(state))
        return
    recipe["input_mode"] = mode
    recipe["updated_at"] = _now()
    save_recipe(ctx, recipe)
    await ctx.reply_markdown(_recipe_markdown(recipe, "Input mode switched", f"Current mode is `{mode}`. No image generation was submitted."))


async def list_presets(ctx):
    recipe, preset, presets, state = await current_recipe(ctx)
    lines = ["# ComfyUI Presets", ""]
    if not presets:
        lines.append("No ready presets found. Run `@comfyui_agent:scan_workflows` after adding API-format workflow JSON files, then map a draft preset.")
    for item in presets:
        current = " current" if recipe and item.get("preset_id") == recipe.get("preset_id") else ""
        lines.append(
            f"- `{item.get('preset_id')}`{current}: {item.get('status')} valid={item.get('valid')} workflow=`{item.get('workflow', {}).get('file_name', '')}`"
        )
    await ctx.reply_markdown("\n".join(lines))


async def scan_workflows(ctx):
    scan = await call_comfy(ctx, "scan_workflow_library")
    workflows = scan.get("workflows") or []
    invalid = [item for item in workflows if not item.get("valid") and item.get("format") != "unsupported_gui_format"]
    unsupported = [item for item in workflows if item.get("format") == "unsupported_gui_format"]
    skipped = scan.get("skipped_draft_presets") or []
    lines = [
        "# ComfyUI Workflow Scan",
        "",
        f"- Workflows: `{len(workflows)}`",
        f"- Presets: `{len(scan.get('presets') or [])}`",
        f"- Duplicates: `{len(scan.get('duplicates') or [])}`",
        f"- Missing preset workflows: `{len(scan.get('missing_preset_workflows') or [])}`",
        f"- Created draft presets: `{len(scan.get('created_draft_presets') or [])}`",
        f"- Invalid workflows: `{len(invalid)}`",
        f"- Unsupported GUI-format workflows: `{len(unsupported)}`",
        f"- Write-disabled / skipped drafts: `{len(skipped)}`",
    ]
    _append_created(lines, scan.get("created_draft_presets") or [])
    _append_missing(lines, scan.get("missing_preset_workflows") or [], skipped)
    _append_invalid(lines, invalid, unsupported)
    await ctx.reply_markdown("\n".join(lines))


async def status_action(ctx):
    connection = await call_comfy(ctx, "test_connection")
    scan = await call_comfy(ctx, "scan_workflow_library")
    recipe, preset, presets, state = await current_recipe(ctx, scan)
    default_id = str(ctx.config.get("default_preset_id") or "")
    default_preset = _preset_by_id(scan.get("presets") or [], default_id) if default_id else None
    recipe_validity = _recipe_validity(recipe, preset)
    lines = [
        "# ComfyUI Status",
        "",
        f"- Connection reachable: `{bool(connection.get('reachable'))}`",
        f"- Workflows dir: `{scan.get('workflows_dir')}`",
        f"- Presets dir: `{scan.get('presets_dir')}`",
        f"- Workflow count: `{len(scan.get('workflows') or [])}`",
        f"- Preset count: `{len(scan.get('presets') or [])}`",
        f"- Current recipe preset: `{recipe.get('preset_id') if recipe else ''}`",
        f"- Current input_mode: `{recipe.get('input_mode') if recipe else ''}`",
        f"- Current recipe validity: `{recipe_validity}`",
        f"- Default preset validity: `{bool(default_preset and default_preset.get('valid') and default_preset.get('status') == 'ready')}`",
    ]
    if not any(item.get("valid") and item.get("status") == "ready" for item in scan.get("presets") or []):
        lines.append("")
        lines.append("No valid ready preset is available. Run `@comfyui_agent:scan_workflows`, then edit a draft preset mapping.")
    await ctx.reply_markdown("\n".join(lines))


async def current_recipe(ctx, scan: dict | None = None):
    scan = scan or await call_comfy(ctx, "scan_workflow_library")
    all_presets = [item for item in scan.get("presets", []) if item.get("valid") and item.get("status") != "disabled"]
    ready_presets = [item for item in all_presets if item.get("status") == "ready"]
    stored = ctx.state.get(RECIPE_KEY)
    if isinstance(stored, dict) and stored.get("preset_id"):
        preset = _preset_by_id(all_presets, stored.get("preset_id"))
        return stored, preset, all_presets, {"status": "loaded"}
    default_id = str(ctx.config.get("default_preset_id") or "")
    default_mode = _input_mode(ctx.config.get("default_input_mode") or "llm")
    preset = _preset_by_id(ready_presets, default_id) if default_id else None
    if preset is None:
        preset = next(iter(ready_presets), None)
    if preset is None:
        return None, None, all_presets, {"status": "needs_preset", "message": "No valid ready ComfyUI preset is available."}
    loaded = await call_comfy(ctx, "load_preset", preset_id=preset["preset_id"])
    preset_data = loaded.get("preset") or {"parameters": preset.get("parameters") or []}
    recipe = recipe_from_preset(preset_data, default_mode)
    save_recipe(ctx, recipe)
    return recipe, preset, all_presets, {"status": "created_from_default"}


def recipe_from_preset(preset: dict, default_input_mode: str) -> dict:
    values = {}
    for parameter in preset.get("parameters") or []:
        if not isinstance(parameter, dict) or not parameter.get("name"):
            continue
        values[str(parameter["name"])] = parameter.get("default")
    workflow = preset.get("workflow") or {}
    return {
        "preset_id": preset.get("id") or preset.get("preset_id") or "",
        "workflow_file_name": workflow.get("file_name") or "",
        "workflow_hash": workflow.get("hash") or "",
        "input_mode": _input_mode(default_input_mode),
        "user_prompt": "",
        "values": values,
        "updated_at": _now(),
    }


def recipe_to_form(recipe: dict | None, preset: dict | None, presets: list[dict]) -> dict:
    recipe = recipe or {}
    preset = preset or {"parameters": []}
    fields = [
        {
            "name": "preset_id",
            "type": "enum",
            "label": "Preset",
            "options": [{"value": item["preset_id"], "label": item.get("name") or item["preset_id"]} for item in presets],
            "value": recipe.get("preset_id") or "",
            "required": True,
        },
        {
            "name": "input_mode",
            "type": "enum",
            "label": "Input mode",
            "options": [{"value": "llm", "label": "LLM prompt"}, {"value": "raw", "label": "Raw positive prompt"}],
            "value": recipe.get("input_mode") or "llm",
            "required": True,
        },
        {
            "name": "user_prompt",
            "type": "textarea",
            "label": "User request for LLM",
            "description": "Used when input_mode=llm. Submitting the form saves only; use Run to generate.",
            "value": recipe.get("user_prompt") or "",
        },
    ]
    values = recipe.get("values") or {}
    for parameter in preset.get("parameters") or []:
        field = {key: parameter[key] for key in ("name", "type", "label", "description", "required", "default", "minimum", "maximum", "step", "options") if key in parameter}
        if "name" not in field or "type" not in field:
            continue
        field["value"] = values.get(field["name"], parameter.get("default"))
        fields.append(field)
    return {
        "type": "action_form",
        "form_id": "comfyui_recipe",
        "title": "ComfyUI Recipe",
        "description": "Edits the current session recipe only. Submit saves; it does not generate.",
        "fields": fields,
        "submit": {"label": "Save recipe", "action_id": "save_recipe_from_form", "message": "Saved ComfyUI recipe"},
    }


def apply_form_to_recipe(current_recipe: dict, prefill: dict, presets: list[dict]) -> tuple[dict, dict | None, bool, list[str]]:
    preset_id = str(prefill.get("preset_id") or current_recipe.get("preset_id") or "")
    preset = _preset_by_id(presets, preset_id)
    if preset is None:
        return current_recipe, None, False, [f"Unknown or invalid preset: {preset_id}"]
    input_mode = _input_mode(prefill.get("input_mode") or current_recipe.get("input_mode") or "llm")
    switched = preset_id != current_recipe.get("preset_id")
    if switched:
        pseudo_preset = {"id": preset["preset_id"], "workflow": preset["workflow"], "parameters": preset.get("parameters") or []}
        recipe = recipe_from_preset(pseudo_preset, input_mode)
    else:
        recipe = dict(current_recipe)
        recipe["values"] = dict(current_recipe.get("values") or {})
        recipe["input_mode"] = input_mode
    recipe["user_prompt"] = str(prefill.get("user_prompt") or "")
    errors = []
    for parameter in preset.get("parameters") or []:
        name = parameter.get("name")
        if not name:
            continue
        value = prefill[name] if name in prefill else recipe["values"].get(name, parameter.get("default"))
        if parameter.get("required") and value in (None, ""):
            errors.append(f"Missing required field: {name}")
        recipe["values"][name] = value
    recipe["updated_at"] = _now()
    return recipe, preset, switched, errors


async def call_comfy(ctx, method_name: str, **kwargs) -> dict:
    result = await getattr(ctx.capability("comfyui"), method_name)(**kwargs)
    if not result.success:
        raise ComfyAgentError("COMFYUI_CAPABILITY_FAILED", result.error or f"ComfyUI capability call failed: {method_name}")
    return result.data or {}


def save_recipe(ctx, recipe: dict) -> None:
    recipe["input_mode"] = _input_mode(recipe.get("input_mode") or "llm")
    recipe["updated_at"] = _now()
    ctx.state.set(RECIPE_KEY, recipe)


def generation_metadata(recipe: dict, preset: dict, prompt_id: str, attachments: list[dict]) -> dict:
    values = copy.deepcopy(recipe.get("values") or {})
    return {
        "kind": "comfyui_generation",
        "preset_id": recipe.get("preset_id") or "",
        "preset_name": preset.get("name") or recipe.get("preset_id") or "",
        "workflow_file_name": recipe.get("workflow_file_name") or (preset.get("workflow") or {}).get("file_name") or "",
        "workflow_hash": recipe.get("workflow_hash") or (preset.get("workflow") or {}).get("hash") or "",
        "prompt_id": prompt_id,
        "input_mode": recipe.get("input_mode") or "llm",
        "user_prompt": recipe.get("user_prompt") or "",
        "positive_prompt": values.get("positive_prompt") or "",
        "negative_prompt": values.get("negative_prompt") or "",
        "values": values,
        "output_attachment_ids": [attachment.get("id") for attachment in attachments if attachment.get("id")],
        "created_at": _now(),
    }


def collect_status_images(status: dict) -> list[dict]:
    outputs = status.get("outputs") if isinstance(status.get("outputs"), dict) else {}
    return [image for image in outputs.get("images") or [] if image.get("filename")]


def _generation_input_mode(recipe: dict, mode_source: str) -> str:
    if mode_source == "run":
        return "run"
    if mode_source == "raw":
        return "raw"
    if mode_source == "llm":
        return "llm"
    return _input_mode(recipe.get("input_mode") or "llm")


def _preset_by_id(presets: list[dict], preset_id: str | None) -> dict | None:
    return next((item for item in presets if item.get("preset_id") == preset_id or item.get("id") == preset_id), None)


def _input_mode(value: Any) -> str:
    value = str(value or "llm").lower()
    return value if value in INPUT_MODES else "llm"


def _value_matches_type(value: Any, field_type: str) -> bool:
    if value is None:
        return True
    if field_type in {"text", "textarea"}:
        return isinstance(value, str)
    if field_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "enum":
        return isinstance(value, str)
    if field_type == "json":
        return isinstance(value, (dict, list))
    return True


def _recipe_validity(recipe: dict | None, preset: dict | None) -> str:
    if recipe is None:
        return "missing"
    if preset is None:
        return "preset_not_found"
    if not preset.get("valid"):
        return "preset_invalid"
    if preset.get("status") != "ready":
        return "preset_not_ready"
    return "ready"


def _is_safe_basename(file_name: Any) -> bool:
    if not isinstance(file_name, str) or not file_name.strip():
        return False
    name = file_name.strip()
    return name == os.path.basename(name) and not os.path.isabs(name) and "/" not in name and "\\" not in name and ".." not in Path(name).parts


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _sanitize_filename(filename: str) -> str:
    name = os.path.basename(filename or "comfyui-output.png")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "comfyui-output.png"


def _recipe_markdown(recipe: dict, title: str, detail: str) -> str:
    values = recipe.get("values") or {}
    return "\n".join([
        f"# {title}",
        "",
        detail,
        "",
        f"- Preset: `{recipe.get('preset_id')}`",
        f"- Workflow: `{recipe.get('workflow_file_name')}`",
        f"- Input mode: `{recipe.get('input_mode')}`",
        f"- User prompt: `{recipe.get('user_prompt') or ''}`",
        f"- Recipe values: `{len(values)}` fields",
    ])


def _no_recipe_markdown(state: dict) -> str:
    return "# ComfyUI recipe unavailable\n\n" + str(state.get("message") or "Configure at least one ready preset first.")


def _summary_block(state: dict) -> dict:
    return {"type": "markdown", "text": f"Recipe status: `{state.get('status')}`. Form submit saves only; default/raw/llm/run generate explicitly."}


def _append_created(lines: list[str], created: list[dict]) -> None:
    if not created:
        return
    lines.extend(["", "## Created Draft Presets"])
    for item in created:
        lines.append(f"- `{item.get('file_name')}` preset_id=`{item.get('id') or item.get('preset_id')}` workflow=`{item.get('workflow_file_name')}`")


def _append_missing(lines: list[str], missing: list[Any], skipped: list[dict]) -> None:
    lines.extend(["", "## Missing Preset Workflows"])
    if not missing:
        lines.append("- None.")
        return
    skipped_by_name = {item.get("workflow_file_name"): item.get("reason") for item in skipped}
    for item in missing:
        if isinstance(item, dict):
            name = item.get("workflow_file_name") or item.get("file_name")
            reason = skipped_by_name.get(name) or item.get("reason") or "created_draft_preset"
        else:
            name = str(item)
            reason = skipped_by_name.get(name) or "missing_preset"
        lines.append(f"- `{name}` reason=`{reason}`")


def _append_invalid(lines: list[str], invalid: list[dict], unsupported: list[dict]) -> None:
    if invalid:
        lines.extend(["", "## Invalid Workflows"])
        for item in invalid:
            lines.append(f"- `{item.get('file_name')}` reason=`invalid_workflow`: {'; '.join(item.get('errors') or [])}")
    if unsupported:
        lines.extend(["", "## Unsupported GUI-format Workflows"])
        for item in unsupported:
            lines.append(f"- `{item.get('file_name')}` reason=`unsupported_gui_format`: {'; '.join(item.get('errors') or [])}")


def _status_message(status: dict) -> str:
    message = str(status.get("status") or "unknown")
    if status.get("queue_position") is not None:
        message += f" queue_position={status.get('queue_position')}"
    return message


def _status_error_message(status: dict) -> str:
    error = status.get("error") if isinstance(status.get("error"), dict) else {}
    return error.get("message") or "ComfyUI prompt execution failed."


def _start_step(ctx, label: str, message: str = ""):
    if getattr(ctx, "run", None) is None:
        return None
    return ctx.run.start_step(label, message=message)


def _complete_step(ctx, step, message: str = "") -> None:
    if step is not None and getattr(ctx, "run", None) is not None:
        ctx.run.complete_step(step.step_id, message=message)


def _fail_step(ctx, step, code: str, message: str) -> None:
    if step is not None and getattr(ctx, "run", None) is not None:
        ctx.run.fail_step(step.step_id, error_code=code, error_message=message)


def _update_step(ctx, step, message: str) -> None:
    if step is None or getattr(ctx, "run", None) is None:
        return
    if hasattr(ctx.run, "update_step"):
        ctx.run.update_step(step.step_id, message=message)


def _cancel_requested(ctx) -> bool:
    try:
        return bool(ctx.run_store.get_run(ctx.run_id).cancel_requested)
    except Exception:
        return False


async def _best_effort_interrupt(ctx) -> None:
    try:
        await call_comfy(ctx, "interrupt")
    except Exception:
        return


async def _unload_llm(ctx) -> dict:
    try:
        result = await ctx.llm.unload_model()
    except AttributeError:
        result = await ctx.llm.unload()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if isinstance(result, dict):
        return result
    return getattr(result, "data", None) or {"ok": bool(getattr(result, "success", False)), "error": getattr(result, "error", "")}


async def _reply_images(ctx, gallery: list[dict], metadata: dict) -> None:
    try:
        await ctx.reply_images(gallery, metadata=metadata)
    except TypeError:
        await ctx.reply_images(gallery)


def _record_run_metadata(ctx, metadata: dict) -> None:
    try:
        run = ctx.run_store.get_run(ctx.run_id)
        next_metadata = dict(run.metadata or {})
        next_metadata["comfyui_generation"] = metadata
        ctx.run_store.update_metadata(ctx.run_id, next_metadata)
    except Exception:
        return


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
