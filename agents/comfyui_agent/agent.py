import asyncio
import copy
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_workbench.core.message_parts import legacy_output_to_parts, make_form_part


RECIPE_KEY = "comfyui_recipe"
INPUT_MODES = {"llm", "raw"}
LLM_OPERATIONS = {"refine", "fresh"}
DEFAULT_FORM_SECTIONS = [
    {"key": "recipe", "title": "Recipe"},
    {"key": "prompts", "title": "Prompts"},
    {"key": "sampling", "title": "Sampling"},
    {"key": "image", "title": "Image"},
    {"key": "model", "title": "Model"},
    {"key": "output", "title": "Output"},
]

DEFAULT_LLM_REFINE_SYSTEM_PROMPT = """\
Use the current positive_prompt and the user's new request to produce a complete new positive_prompt.
Return only the complete positive prompt, not a diff.
Do not choose workflow, steps, cfg, sampler, scheduler, seed, width, height, or any other recipe parameter.
"""
DEFAULT_LLM_REFINE_USER_TEMPLATE = """\
User request:
{user_input}

Current positive prompt:
{positive_prompt}

Current negative prompt:
{negative_prompt}

Preset:
{preset_name} ({preset_id})

Input mode: {input_mode}
LLM operation: {llm_operation}
"""
DEFAULT_LLM_FRESH_SYSTEM_PROMPT = """\
Use only the user's request to produce a complete positive_prompt.
Do not reference the current positive_prompt.
Do not choose workflow, steps, cfg, sampler, scheduler, seed, width, height, or any other recipe parameter.
"""
DEFAULT_LLM_FRESH_USER_TEMPLATE = """\
User request:
{user_input}

Current negative prompt:
{negative_prompt}

Preset:
{preset_name} ({preset_id})

Input mode: {input_mode}
LLM operation: {llm_operation}
"""


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
        if recipe is None:
            await ctx.reply_markdown(_no_recipe_markdown(recipe_state, presets))
            return
        await ctx.reply_blocks([_summary_block(recipe_state), recipe_to_form(recipe, preset, presets)])
        return
    if action == "save_recipe_from_form":
        return await save_recipe_from_form(ctx)
    if action == "switch":
        await switch_mode(ctx)
        return
    if action in {"default", "raw", "llm", "fresh", "refine", "run"}:
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
    llm_operation = resolve_llm_operation(mode_source, recipe, ctx.config) if action_mode == "llm" else None
    if mode_source == "raw":
        recipe.setdefault("values", {})["positive_prompt"] = user_input or ""
    elif mode_source in {"llm", "fresh", "refine"}:
        recipe["user_prompt"] = user_input or ""
        recipe["last_user_prompt"] = user_input or ""
    elif mode_source == "default":
        if action_mode == "raw":
            recipe.setdefault("values", {})["positive_prompt"] = user_input or ""
        else:
            recipe["user_prompt"] = user_input or ""
            recipe["last_user_prompt"] = user_input or ""
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
        try:
            positive_prompt = await enhance_positive_prompt(
                ctx,
                recipe,
                preset_data,
                user_input or recipe.get("user_prompt") or "",
                action_id=mode_source,
                llm_operation=llm_operation or "refine",
            )
        except ComfyAgentError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            _record_prompt_enhancer_failure(ctx, detail)
            if step is not None:
                _update_step(ctx, step, detail.get("inner_message") or exc.message, metadata={"comfyui_prompt_enhancer": detail})
                _fail_step(ctx, step, exc.code, exc.message)
            raise
        recipe.setdefault("values", {})["positive_prompt"] = positive_prompt
        recipe["last_llm_operation"] = llm_operation
        recipe["updated_at"] = _now()
        save_recipe(ctx, recipe)
        _complete_step(ctx, step, "Positive prompt generated.")
        if not bool(ctx.config.get("auto_run_after_llm_prompt", True)):
            metadata = prompt_saved_metadata(recipe, preset_data, llm_operation or "refine", positive_prompt)
            await ctx.reply_blocks(saved_positive_prompt_blocks(positive_prompt), metadata={"comfyui_generation": metadata})
            _record_run_metadata(ctx, metadata)
            return {
                **metadata,
                "kind": "comfyui_prompt_saved",
            }

    step = _start_step(ctx, "Build workflow", "Applying recipe values to workflow copy.")
    workflow = build_workflow_from_recipe(recipe, preset_data, scan)
    _complete_step(ctx, step, "Workflow JSON prepared.")

    if action_mode == "llm" and bool(ctx.config.get("unload_llm_before_generation", True)):
        step = _start_step(ctx, "Unload prompt LLM", "Best-effort unload before ComfyUI generation.")
        unload = await _unload_llm(ctx)
        message = "Unload requested." if unload.get("ok") else f"Unload warning: {unload.get('error') or unload.get('message') or 'unsupported'}"
        _complete_step(ctx, step, message)

    prompt_id = ""
    step = _start_step(ctx, "Submit workflow to ComfyUI", "Submitting workflow.")
    submitted = await call_comfy(ctx, "submit_workflow", workflow=workflow)
    if not submitted.get("accepted"):
        error = submitted.get("error") or {}
        _fail_step(ctx, step, error.get("code") or "COMFYUI_PROMPT_REJECTED", error.get("message") or "ComfyUI rejected the workflow.")
        raise ComfyAgentError(error.get("code") or "COMFYUI_PROMPT_REJECTED", error.get("message") or "ComfyUI rejected the workflow.", submitted)
    prompt_id = submitted.get("prompt_id") or ""
    _complete_step(ctx, step, f"Submitted prompt `{prompt_id}`.")

    try:
        status = await poll_prompt_status(ctx, prompt_id, scan)
        image_filter = filter_output_images(collect_status_images(status))
        images = image_filter["images"]
        step = _start_step(ctx, "Fetch output images", f"Fetching {len(images)} output image(s).")
        if not images:
            filter_metadata = image_filter_metadata(prompt_id, image_filter)
            _record_run_metadata(ctx, filter_metadata)
            code = "COMFYUI_ONLY_TEMP_IMAGES" if image_filter["ignored_temp_image_count"] else "COMFYUI_OUTPUT_NOT_FOUND"
            message = (
                "ComfyUI returned only temporary images. Add or verify a SaveImage output node in the workflow."
                if code == "COMFYUI_ONLY_TEMP_IMAGES"
                else "ComfyUI completed but returned no output images."
            )
            _fail_step(ctx, step, code, message)
            raise ComfyAgentError(code, message, {"prompt_id": prompt_id, "status": status, "image_filter": filter_metadata})

        fetched = []
        for image in images:
            fetched.append(await call_comfy(ctx, "fetch_image", filename=image["filename"], subfolder=image.get("subfolder", ""), type=image.get("type", "output"), as_base64=True))
        _complete_step(ctx, step, f"Fetched {len(fetched)} output image(s).")

        step = _start_step(ctx, "Save attachments", "Saving generated images locally.")
        attachments = []
        for source, payload in zip(images, fetched):
            attachments.append(await save_image_attachment(ctx, payload, source, recipe, prompt_id))
        _complete_step(ctx, step, f"Saved {len(attachments)} local attachment(s).")

        metadata = generation_metadata(recipe, preset_data, prompt_id, attachments, image_filter=image_filter, llm_operation=llm_operation if action_mode == "llm" else None)
        _record_run_metadata(ctx, metadata)
        memory_release = await _maybe_free_comfyui_memory(ctx)
        if memory_release is not None:
            _record_run_metadata_key(ctx, "comfyui_memory_release", memory_release)
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
    except ComfyAgentError as exc:
        if prompt_id and exc.code != "COMFYUI_TIMEOUT":
            memory_release = await _maybe_free_comfyui_memory(ctx)
            if memory_release is not None:
                _record_run_metadata_key(ctx, "comfyui_memory_release", memory_release)
        raise


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


async def enhance_positive_prompt(ctx, recipe: dict, preset: dict, user_input: str, action_id: str | None = None, llm_operation: str | None = None) -> str:
    values = recipe.get("values") or {}
    operation = _resolve_llm_operation_value(llm_operation, default="refine")
    detail = _prompt_enhancer_detail(
        ctx,
        action_id=action_id or getattr(ctx, "action_id", "") or "default",
        stage="render_template",
        reached_provider=False,
        llm_operation=operation,
    )
    try:
        system, template = _llm_prompt_template(ctx.config, operation)
    except ComfyAgentError as exc:
        detail.update(exc.detail, stage="resolve_template", reached_provider=False)
        raise ComfyAgentError(
            "COMFYUI_PROMPT_ENHANCER_FAILED",
            "LLM prompt enhancer template is not configured. Set the ComfyUI Agent refine/fresh prompt templates.",
            detail,
        ) from exc
    try:
        prompt = template.format(
            user_input=user_input,
            positive_prompt=values.get("positive_prompt") or "",
            negative_prompt=values.get("negative_prompt") or "",
            preset_id=recipe.get("preset_id") or "",
            preset_name=preset.get("name") or recipe.get("preset_id") or "",
            input_mode="llm",
            llm_operation=operation,
        )
    except Exception as exc:
        detail.update(_inner_error(exc), stage="render_template", reached_provider=False)
        raise ComfyAgentError(
            "COMFYUI_PROMPT_ENHANCER_FAILED",
            "LLM prompt enhancer failed. Configure an LLM, switch to raw mode, or use `@comfyui_agent:raw`.",
            detail,
        ) from exc
    try:
        detail["stage"] = "call_llm"
        detail["reached_provider"] = True
        text = await ctx.llm.text(system=system, user=prompt)
    except Exception as exc:
        detail.update(_inner_error(exc), stage="call_llm", reached_provider=True)
        raise ComfyAgentError(
            "COMFYUI_PROMPT_ENHANCER_FAILED",
            "LLM prompt enhancer failed. Configure an LLM, switch to raw mode, or use `@comfyui_agent:raw`.",
            detail,
        ) from exc
    text = _strip_code_fence(str(text or "")).strip()
    if not text:
        detail.update(stage="empty_output", reached_provider=True, inner_code="LLM_EMPTY_OUTPUT", inner_message="LLM prompt enhancer returned empty text.")
        raise ComfyAgentError(
            "COMFYUI_PROMPT_ENHANCER_FAILED",
            "LLM prompt enhancer returned empty text. Configure an LLM, switch to raw mode, or use `@comfyui_agent:raw`.",
            detail,
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
        "comfyui_image_type": image_ref.get("type") or "output",
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
        if not getattr(ctx.input, "is_silent_submission", False):
            await ctx.reply_markdown(_no_recipe_markdown(state, presets))
        return
    next_recipe, next_preset, switched, errors = apply_form_to_recipe(recipe, prefill, presets)
    if errors:
        if not getattr(ctx.input, "is_silent_submission", False):
            await ctx.reply_markdown("# Recipe form was not saved\n\n" + "\n".join(f"- {error}" for error in errors))
        return
    save_recipe(ctx, next_recipe)
    title = "Preset switched and recipe saved" if switched else "Recipe saved"
    updated_form = await update_source_recipe_form(ctx, next_recipe, next_preset or preset, presets)
    if not getattr(ctx.input, "is_silent_submission", False):
        await ctx.reply_markdown(_recipe_markdown(next_recipe, title, "Form values update only this session recipe, not preset files. No generation was submitted."))
    return {"updated_form": updated_form} if updated_form else {"ok": True}


async def switch_mode(ctx):
    mode = ctx.input.text.strip().lower()
    if mode not in INPUT_MODES:
        await ctx.reply_markdown("Use `@comfyui_agent:switch llm` or `@comfyui_agent:switch raw`.")
        return
    recipe, preset, presets, state = await current_recipe(ctx)
    if recipe is None:
        await ctx.reply_markdown(_no_recipe_markdown(state, presets))
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
    ready_presets = [item for item in scan.get("presets") or [] if item.get("valid") and item.get("status") == "ready"]
    positive_prompt = ((recipe or {}).get("values") or {}).get("positive_prompt") if recipe else ""
    lines = [
        "# ComfyUI Status",
        "",
        f"- Connection reachable: `{bool(connection.get('reachable'))}`",
        f"- Workflows dir: `{scan.get('workflows_dir')}`",
        f"- Presets dir: `{scan.get('presets_dir')}`",
        f"- Workflow count: `{len(scan.get('workflows') or [])}`",
        f"- Valid ready preset count: `{len(ready_presets)}`",
        f"- Current recipe preset: `{recipe.get('preset_id') if recipe else ''}`",
        f"- Current input_mode: `{recipe.get('input_mode') if recipe else ''}`",
        f"- Default LLM operation: `{resolve_default_llm_operation(ctx.config)}`",
        f"- Last LLM operation: `{recipe.get('last_llm_operation') if recipe else ''}`",
        f"- Auto-run after LLM prompt: `{bool(ctx.config.get('auto_run_after_llm_prompt', True))}`",
        f"- Current positive_prompt empty: `{not bool(positive_prompt)}`",
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
    default_mode = resolve_default_input_mode(ctx.config)
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


def recipe_to_form(recipe: dict | None, preset: dict | None, presets: list[dict], collapsed: bool = False) -> dict:
    recipe = recipe or {}
    preset = preset or {"parameters": []}
    ready_presets = [item for item in presets if item.get("valid") and item.get("status") == "ready"]
    if not ready_presets:
        raise ComfyAgentError(
            "COMFYUI_PRESET_INVALID",
            "No valid ready ComfyUI preset is available; cannot render the recipe form.",
            {"schema_doc": "docs/COMFYUI_PRESET_SCHEMA.md"},
        )
    fields = [
        {
            "name": "preset_id",
            "type": "enum",
            "label": "Preset",
            "description": "Changing preset replaces this session recipe with that preset's defaults after Save.",
            "options": [{"value": item["preset_id"], "label": item.get("name") or item["preset_id"]} for item in ready_presets],
            "value": recipe.get("preset_id") or "",
            "required": True,
            "ui": {"section": "recipe", "span": 12},
        }
    ]
    values = recipe.get("values") or {}
    for parameter in preset.get("parameters") or []:
        if parameter.get("type") == "enum" and not parameter.get("options"):
            preset_id = recipe.get("preset_id") or preset.get("preset_id") or preset.get("id") or ""
            name = parameter.get("name") or "<unnamed>"
            raise ComfyAgentError(
                "COMFYUI_PRESET_INVALID",
                f"Preset `{preset_id}` enum parameter `{name}` is missing options. See docs/COMFYUI_PRESET_SCHEMA.md.",
                {"preset_id": preset_id, "parameter": name, "missing": "options", "schema_doc": "docs/COMFYUI_PRESET_SCHEMA.md"},
            )
        field = {key: parameter[key] for key in ("name", "type", "label", "description", "required", "default", "minimum", "maximum", "step", "options") if key in parameter}
        if "name" not in field or "type" not in field:
            continue
        field["value"] = values.get(field["name"], parameter.get("default"))
        field_ui = _form_field_ui(parameter, field)
        if field_ui:
            field["ui"] = field_ui
        fields.append(field)
    preset_ui = preset.get("ui") if isinstance(preset.get("ui"), dict) else {}
    return {
        "type": "action_form",
        "form_id": "comfyui_recipe",
        "title": "ComfyUI Recipe",
        "description": "Save recipe only updates this session recipe. It does not edit preset files or generate images.",
        "ui": {
            "default_collapsed": False,
            "collapsed": bool(collapsed),
            "collapse_on_success": True,
            "collapsed_message": "Recipe saved. Click to expand.",
        },
        "fields": fields,
        "sections": _form_sections(preset_ui),
        "submit": {"label": "Save recipe", "action_id": "save_recipe_from_form", "visibility": "silent", "success_message": "Recipe saved"},
    }


def _form_sections(preset_ui: dict | None) -> list[dict]:
    sections = (preset_ui or {}).get("sections")
    if isinstance(sections, list) and sections:
        cleaned = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            key = section.get("key")
            if not isinstance(key, str) or not key.strip():
                continue
            item = {"key": key.strip()}
            title = section.get("title")
            if isinstance(title, str) and title.strip():
                item["title"] = title.strip()
            cleaned.append(item)
        if cleaned:
            return cleaned
    return copy.deepcopy(DEFAULT_FORM_SECTIONS)


def _form_field_ui(parameter: dict, field: dict) -> dict:
    explicit = parameter.get("ui") if isinstance(parameter.get("ui"), dict) else {}
    default = _default_form_field_ui(str(field.get("name") or ""), str(field.get("type") or ""))
    ui = {}
    explicit_section = explicit.get("section")
    explicit_span = explicit.get("span")
    if isinstance(explicit_section, str) and explicit_section.strip():
        ui["section"] = explicit_section.strip()
    elif default.get("section") is not None:
        ui["section"] = default.get("section")
    if isinstance(explicit_span, int) and not isinstance(explicit_span, bool) and 1 <= explicit_span <= 12:
        ui["span"] = explicit_span
    elif default.get("span") is not None:
        ui["span"] = default.get("span")
    return ui


def _default_form_field_ui(name: str, field_type: str) -> dict:
    normalized = name.lower()
    if field_type in {"textarea", "json"} or "prompt" in normalized or "description" in normalized:
        return {"section": "prompts", "span": 12}
    if normalized in {"seed", "steps", "cfg", "cfg_scale", "denoise"}:
        return {"section": "sampling", "span": 4}
    if normalized in {"sampler", "sampler_name", "scheduler"}:
        return {"section": "sampling", "span": 4}
    if normalized in {"width", "height", "batch_size"}:
        return {"section": "image", "span": 4}
    if normalized in {"checkpoint", "checkpoint_name", "ckpt_name"}:
        return {"section": "model", "span": 6}
    if normalized == "filename_prefix":
        return {"section": "output", "span": 6}
    if field_type in {"integer", "float"}:
        return {"section": "sampling", "span": 4}
    if field_type == "boolean":
        return {"section": "sampling", "span": 4}
    if field_type == "enum":
        return {"section": "sampling", "span": 4}
    if field_type == "text":
        return {"section": "output", "span": 6}
    return {"section": "output", "span": 12}


def apply_form_to_recipe(current_recipe: dict, prefill: dict, presets: list[dict]) -> tuple[dict, dict | None, bool, list[str]]:
    preset_id = str(prefill.get("preset_id") or current_recipe.get("preset_id") or "")
    preset = _preset_by_id(presets, preset_id)
    if preset is None or not (preset.get("valid") and preset.get("status") == "ready"):
        return current_recipe, None, False, [f"Unknown or invalid preset: {preset_id}"]
    input_mode = _input_mode(current_recipe.get("input_mode") or "llm")
    switched = preset_id != current_recipe.get("preset_id")
    if switched:
        pseudo_preset = {"id": preset["preset_id"], "workflow": preset["workflow"], "parameters": preset.get("parameters") or []}
        recipe = recipe_from_preset(pseudo_preset, input_mode)
        recipe["user_prompt"] = ""
        recipe["updated_at"] = _now()
        return recipe, preset, switched, []
    else:
        recipe = dict(current_recipe)
        recipe["values"] = dict(current_recipe.get("values") or {})
        recipe["input_mode"] = input_mode
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
    if recipe.get("last_llm_operation") is not None:
        recipe["last_llm_operation"] = _resolve_llm_operation_value(recipe.get("last_llm_operation"), default=None)
    recipe["updated_at"] = _now()
    ctx.state.set(RECIPE_KEY, recipe)


def prompt_saved_metadata(recipe: dict, preset: dict, llm_operation: str, positive_prompt: str) -> dict:
    operation = _resolve_llm_operation_value(llm_operation, default="refine")
    return {
        "kind": "comfyui_prompt_saved",
        "preset_id": recipe.get("preset_id") or "",
        "preset_name": preset.get("name") or recipe.get("preset_id") or "",
        "workflow_file_name": recipe.get("workflow_file_name") or (preset.get("workflow") or {}).get("file_name") or "",
        "workflow_hash": recipe.get("workflow_hash") or (preset.get("workflow") or {}).get("hash") or "",
        "input_mode": "llm",
        "llm_operation": operation,
        "llm_operation_requested": operation,
        "llm_operation_used": operation,
        "user_prompt": recipe.get("user_prompt") or recipe.get("last_user_prompt") or "",
        "positive_prompt": positive_prompt or "",
        "negative_prompt": (recipe.get("values") or {}).get("negative_prompt") or "",
        "created_at": _now(),
    }


def generation_metadata(recipe: dict, preset: dict, prompt_id: str, attachments: list[dict], image_filter: dict | None = None, llm_operation: str | None = None) -> dict:
    values = copy.deepcopy(recipe.get("values") or {})
    image_filter = image_filter or {}
    metadata = {
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
        "output_image_count": image_filter.get("output_image_count", len(attachments)),
        "ignored_temp_image_count": image_filter.get("ignored_temp_image_count", 0),
        "ignored_input_image_count": image_filter.get("ignored_input_image_count", 0),
        "ignored_preview_image_count": image_filter.get("ignored_preview_image_count", 0),
        "image_filter": "output_only",
        "created_at": _now(),
    }
    if image_filter.get("warnings"):
        metadata["image_filter_warnings"] = image_filter["warnings"]
    if llm_operation:
        operation = _resolve_llm_operation_value(llm_operation, default=None)
        metadata.update(
            {
                "llm_operation": operation,
                "llm_operation_requested": operation,
                "llm_operation_used": operation,
            }
        )
    return metadata


def collect_status_images(status: dict) -> list[dict]:
    outputs = status.get("outputs") if isinstance(status.get("outputs"), dict) else {}
    return [image for image in outputs.get("images") or [] if image.get("filename")]


def filter_output_images(images: list[dict]) -> dict:
    kept: list[dict] = []
    ignored_temp = 0
    ignored_input = 0
    ignored_preview = 0
    warnings: list[str] = []
    for image in images:
        image_type = image.get("type")
        filename = str(image.get("filename") or "")
        normalized_type = str(image_type).strip().lower() if image_type is not None else ""
        if filename.startswith("ComfyUI_temp_"):
            ignored_temp += 1
            continue
        if normalized_type == "output":
            kept.append(image)
            continue
        if normalized_type == "temp":
            ignored_temp += 1
            continue
        if normalized_type == "input":
            ignored_input += 1
            continue
        if normalized_type == "preview":
            ignored_preview += 1
            continue
        if not normalized_type:
            warnings.append(f"Image type missing for {filename}; treating as output.")
            kept.append({**image, "type": "output"})
            continue
        ignored_preview += 1
        warnings.append(f"Ignored unsupported ComfyUI image type `{normalized_type}` for {filename}.")
    return {
        "images": kept,
        "total_image_count": len(images),
        "output_image_count": len(kept),
        "ignored_temp_image_count": ignored_temp,
        "ignored_input_image_count": ignored_input,
        "ignored_preview_image_count": ignored_preview,
        "warnings": warnings,
        "image_filter": "output_only",
    }


def image_filter_metadata(prompt_id: str, image_filter: dict) -> dict:
    return {
        "kind": "comfyui_generation",
        "prompt_id": prompt_id,
        "output_image_count": image_filter.get("output_image_count", 0),
        "ignored_temp_image_count": image_filter.get("ignored_temp_image_count", 0),
        "ignored_input_image_count": image_filter.get("ignored_input_image_count", 0),
        "ignored_preview_image_count": image_filter.get("ignored_preview_image_count", 0),
        "image_filter": "output_only",
        "image_filter_warnings": image_filter.get("warnings") or [],
    }


def _generation_input_mode(recipe: dict, mode_source: str) -> str:
    if mode_source == "run":
        return "run"
    if mode_source == "raw":
        return "raw"
    if mode_source in {"llm", "fresh", "refine"}:
        return "llm"
    return _input_mode(recipe.get("input_mode") or "llm")


def resolve_llm_operation(action_id: str, recipe: dict, agent_config: dict | None) -> str:
    if action_id == "fresh":
        return "fresh"
    if action_id == "refine":
        return "refine"
    if action_id == "llm":
        return resolve_default_llm_operation(agent_config)
    if action_id == "default" and _input_mode(recipe.get("input_mode") or "llm") == "llm":
        return resolve_default_llm_operation(agent_config)
    return resolve_default_llm_operation(agent_config)


def _preset_by_id(presets: list[dict], preset_id: str | None) -> dict | None:
    return next((item for item in presets if item.get("preset_id") == preset_id or item.get("id") == preset_id), None)


def _input_mode(value: Any) -> str:
    return _resolve_input_mode_value(value, default="llm")


def resolve_default_input_mode(agent_config: dict | None) -> str:
    return _resolve_input_mode_value((agent_config or {}).get("default_input_mode"), default="llm")


def resolve_default_llm_operation(agent_config: dict | None) -> str:
    return _resolve_llm_operation_value((agent_config or {}).get("llm_operation_default"), default="refine")


def _resolve_input_mode_value(value: Any, default: str | None) -> str:
    text = _normalized_config_text(value)
    if text in {"", "unset"}:
        if default is None:
            raise ComfyAgentError("COMFYUI_CONFIG_INVALID", "ComfyUI input mode is not configured.")
        return default
    if text not in INPUT_MODES:
        raise ComfyAgentError("COMFYUI_CONFIG_INVALID", f"Invalid ComfyUI input mode: {value}. Expected `llm` or `raw`.")
    return text


def _resolve_llm_operation_value(value: Any, default: str | None) -> str:
    text = _normalized_config_text(value)
    if text in {"", "unset"}:
        if default is None:
            raise ComfyAgentError("COMFYUI_CONFIG_INVALID", "ComfyUI LLM operation is not configured.")
        return default
    if text not in LLM_OPERATIONS:
        raise ComfyAgentError("COMFYUI_CONFIG_INVALID", f"Invalid ComfyUI LLM operation: {value}. Expected `refine` or `fresh`.")
    return text


def _normalized_config_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _llm_prompt_template(config: dict | None, operation: str) -> tuple[str, str]:
    config = config or {}
    if operation == "fresh":
        system = _prompt_template_value(config, "llm_fresh_system_prompt", DEFAULT_LLM_FRESH_SYSTEM_PROMPT)
        template = _prompt_template_value(config, "llm_fresh_user_template", DEFAULT_LLM_FRESH_USER_TEMPLATE)
        _validate_prompt_template(system, "llm_fresh_system_prompt")
        _validate_prompt_template(template, "llm_fresh_user_template")
        return system, template
    system = _prompt_template_value(config, "llm_refine_system_prompt", DEFAULT_LLM_REFINE_SYSTEM_PROMPT)
    template = _prompt_template_value(config, "llm_refine_user_template", DEFAULT_LLM_REFINE_USER_TEMPLATE)
    _validate_prompt_template(system, "llm_refine_system_prompt")
    _validate_prompt_template(template, "llm_refine_user_template")
    return system, template


def _prompt_template_value(config: dict, key: str, default: str) -> str:
    if key in config and config.get(key) is not None:
        return str(config.get(key)).strip()
    return default.strip()


def _validate_prompt_template(value: str, key: str) -> None:
    if not value:
        raise ComfyAgentError(
            "COMFYUI_PROMPT_TEMPLATE_EMPTY",
            f"ComfyUI Agent config `{key}` must not be empty.",
            {"field": key},
        )


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


def saved_positive_prompt_blocks(positive_prompt: str) -> list[dict]:
    return [
        {"type": "markdown", "text": "## Positive prompt"},
        {"type": "text", "text": positive_prompt or ""},
        {"type": "markdown", "text": "Saved to the current session recipe."},
        {
            "type": "command_buttons",
            "buttons": [
                {"label": "Edit recipe", "message": "@comfyui_agent:form"},
                {"label": "Run recipe", "message": "@comfyui_agent:run"},
            ],
        },
    ]


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
        f"- Recipe values: `{len(values)}` fields",
    ])


def _no_recipe_markdown(state: dict, presets: list[dict] | None = None) -> str:
    lines = [
        "# ComfyUI recipe unavailable",
        "",
        str(state.get("message") or "No valid ready ComfyUI preset is available."),
        "",
        "- Run `@comfyui_agent:scan_workflows` after adding API-format workflow JSON files.",
        "- Or edit a draft preset in `presets_dir` until it is valid and ready.",
    ]
    needs_mapping = [item for item in presets or [] if item.get("status") == "needs_mapping"]
    if needs_mapping:
        lines.extend(["", "Needs mapping presets:"])
        lines.extend(f"- `{item.get('preset_id')}` workflow=`{(item.get('workflow') or {}).get('file_name', '')}`" for item in needs_mapping)
    return "\n".join(lines)


def _summary_block(state: dict) -> dict:
    return {"type": "markdown", "text": f"Recipe status: `{state.get('status')}`. Form submit saves only; default/raw/llm/fresh/refine/run generate explicitly."}


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


def _update_step(ctx, step, message: str, metadata: dict | None = None) -> None:
    if step is None or getattr(ctx, "run", None) is None:
        return
    if hasattr(ctx.run, "update_step"):
        ctx.run.update_step(step.step_id, message=message, metadata=metadata)


async def update_source_recipe_form(ctx, recipe: dict, preset: dict | None, presets: list[dict]) -> dict | None:
    source_message_id = getattr(ctx.input, "source_message_id", None)
    form_id = getattr(ctx.input, "form_id", None) or "comfyui_recipe"
    if not source_message_id or getattr(ctx, "message_store", None) is None:
        return None
    block = recipe_to_form(recipe, preset, presets, collapsed=True)
    try:
        source = ctx.message_store.get_message(source_message_id)
    except Exception:
        return None
    parts = copy.deepcopy(getattr(source, "parts", None) or [])
    content = copy.deepcopy(source.content)
    replaced_parts = _replace_form_part(parts, form_id, block)
    replaced_content = False
    if not replaced_parts:
        replaced_content = _replace_action_form_block(content, form_id, block)
    if not replaced_parts and not replaced_content:
        return None
    if not replaced_parts:
        parts = legacy_output_to_parts(_output_type_for_updated_content(source.output_type, content), content)
    updated = ctx.message_store.update_message(
        source.model_copy(
            update={
                "content": source.content if replaced_parts else content,
                "output_type": None if replaced_parts else source.output_type,
                "content_version": 2,
                "parts": parts,
            }
        )
    )
    if getattr(ctx, "event_bus", None) is not None:
        ctx.event_bus.emit(
            "message_updated",
            session_id=updated.session_id,
            run_id=getattr(ctx, "run_id", None),
            message_id=updated.message_id,
            payload={"message": updated.model_dump(mode="json")},
        )
    return {"source_message_id": source_message_id, "form_id": form_id, "block": block}


def _replace_form_part(parts: Any, form_id: str, block: dict) -> bool:
    if not isinstance(parts, list):
        return False
    replacement = make_form_part(block)
    for index, item in enumerate(parts):
        if isinstance(item, dict) and item.get("type") == "form" and item.get("form_id") == form_id:
            parts[index] = {**replacement, "id": item.get("id") or replacement["id"]}
            return True
    return False


def _replace_action_form_block(content: Any, form_id: str, block: dict) -> bool:
    if isinstance(content, dict) and content.get("type") == "action_form" and content.get("form_id") == form_id:
        content.clear()
        content.update(block)
        return True
    blocks = content.get("blocks") if isinstance(content, dict) else None
    if not isinstance(blocks, list):
        return False
    for index, item in enumerate(blocks):
        if isinstance(item, dict) and item.get("type") == "action_form" and item.get("form_id") == form_id:
            blocks[index] = block
            return True
    return False


def _output_type_for_updated_content(output_type: str | None, content: Any) -> str:
    if isinstance(content, dict):
        if isinstance(content.get("blocks"), list):
            return "rich_content"
        if content.get("type") == "action_form":
            return "rich_content"
    return output_type or "rich_content"


def _prompt_enhancer_detail(ctx, action_id: str, stage: str, reached_provider: bool, llm_operation: str | None = None) -> dict:
    resolution = getattr(ctx, "llm_resolution", None) or {}
    model_config = getattr(getattr(ctx, "llm", None), "default_model_config", None) or {}
    llm_profile_id = resolution.get("profile_id") or model_config.get("profile_id") or model_config.get("llm_profile_id")
    detail = {
        "code": "COMFYUI_PROMPT_ENHANCER_FAILED",
        "stage": stage,
        "agent_id": getattr(getattr(ctx, "agent", None), "id", None) or "comfyui_agent",
        "action_id": action_id,
        "llm_profile_id": llm_profile_id,
        "provider_profile_id": resolution.get("provider_profile_id") or model_config.get("provider_profile_id"),
        "provider": resolution.get("provider") or model_config.get("provider"),
        "model_id": resolution.get("model_id") or model_config.get("model_id") or model_config.get("model"),
        "reached_provider": reached_provider,
    }
    if llm_operation:
        operation = _resolve_llm_operation_value(llm_operation, default=None)
        detail.update(
            {
                "llm_operation": operation,
                "llm_operation_requested": operation,
                "llm_operation_used": operation,
            }
        )
    return detail


def _inner_error(exc: Exception) -> dict:
    return {
        "inner_code": getattr(exc, "code", None) or exc.__class__.__name__,
        "inner_message": getattr(exc, "message", None) or str(exc) or exc.__class__.__name__,
    }


def _record_prompt_enhancer_failure(ctx, detail: dict) -> None:
    try:
        run = ctx.run_store.get_run(ctx.run_id)
        metadata = dict(run.metadata or {})
        metadata["comfyui_prompt_enhancer_error"] = detail
        ctx.run_store.update_metadata(ctx.run_id, metadata)
    except Exception:
        return


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


async def _maybe_free_comfyui_memory(ctx) -> dict | None:
    if not bool(ctx.config.get("free_comfyui_memory_after_generation", False)):
        return None
    step = _start_step(ctx, "Free ComfyUI memory", "Requesting ComfyUI memory release.")
    requested = {"unload_models": True, "free_memory": True}
    try:
        result = await ctx.capability("comfyui").free_memory(**requested)
        data = result.data or {} if getattr(result, "success", False) else {}
        if not getattr(result, "success", False):
            data = {"ok": False, "error": {"code": "COMFYUI_FREE_MEMORY_FAILED", "message": result.error or "ComfyUI memory release failed."}}
    except Exception as exc:
        data = {"ok": False, "error": {"code": "COMFYUI_FREE_MEMORY_FAILED", "message": str(exc) or exc.__class__.__name__}}
    metadata = {
        "enabled": True,
        "attempted": True,
        "success": bool(data.get("ok")),
        "requested": data.get("requested") or requested,
        "status_code": data.get("status_code"),
        "error": data.get("error"),
    }
    if metadata["success"]:
        _complete_step(ctx, step, "ComfyUI memory release requested.")
    else:
        _fail_step(ctx, step, "COMFYUI_FREE_MEMORY_FAILED", "Failed to release ComfyUI memory; generation result preserved.")
    return metadata


async def _reply_images(ctx, gallery: list[dict], metadata: dict) -> None:
    try:
        await ctx.reply_images(gallery, metadata=metadata)
    except TypeError:
        await ctx.reply_images(gallery)


def _record_run_metadata(ctx, metadata: dict) -> None:
    _record_run_metadata_key(ctx, "comfyui_generation", metadata)


def _record_run_metadata_key(ctx, key: str, value: dict) -> None:
    try:
        run = ctx.run_store.get_run(ctx.run_id)
        next_metadata = dict(run.metadata or {})
        next_metadata[key] = value
        ctx.run_store.update_metadata(ctx.run_id, next_metadata)
    except Exception:
        return


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
