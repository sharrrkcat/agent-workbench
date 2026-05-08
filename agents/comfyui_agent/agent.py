from datetime import datetime, timezone
from typing import Any


RECIPE_KEY = "comfyui_recipe"
INPUT_MODES = {"llm", "raw"}


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
    if action == "raw":
        await save_raw(ctx)
        return
    if action == "llm":
        await save_llm(ctx)
        return
    if action == "run":
        await dry_run(ctx)
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
    await default(ctx)


async def default(ctx):
    recipe, preset, presets, state = await current_recipe(ctx)
    text = ctx.input.text.strip()
    if recipe is None:
        await ctx.reply_markdown(_no_recipe_markdown(state))
        return
    if recipe["input_mode"] == "raw":
        recipe.setdefault("values", {})["positive_prompt"] = text
        detail = "Saved the message as `values.positive_prompt` because `input_mode=raw`."
    else:
        recipe["user_prompt"] = text
        detail = "Saved the message as `user_prompt` because `input_mode=llm`. LLM prompt enhancement is not called in this round."
    save_recipe(ctx, recipe)
    await ctx.reply_markdown(_recipe_markdown(recipe, "ComfyUI recipe updated", detail))


async def save_raw(ctx):
    recipe, preset, presets, state = await current_recipe(ctx)
    if recipe is None:
        await ctx.reply_markdown(_no_recipe_markdown(state))
        return
    recipe.setdefault("values", {})["positive_prompt"] = ctx.input.text.strip()
    recipe["updated_at"] = _now()
    save_recipe(ctx, recipe)
    await ctx.reply_markdown(_recipe_markdown(recipe, "Raw positive prompt saved", "This did not change `input_mode` and did not generate an image."))


async def save_llm(ctx):
    recipe, preset, presets, state = await current_recipe(ctx)
    if recipe is None:
        await ctx.reply_markdown(_no_recipe_markdown(state))
        return
    recipe["user_prompt"] = ctx.input.text.strip()
    recipe["updated_at"] = _now()
    save_recipe(ctx, recipe)
    await ctx.reply_markdown(_recipe_markdown(recipe, "LLM user request saved", "No LLM prompt enhancement is called in this round."))


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


async def dry_run(ctx):
    recipe, preset, presets, state = await current_recipe(ctx)
    if recipe is None:
        await ctx.reply_markdown(_no_recipe_markdown(state))
        return
    validation = await call_comfy(ctx, "validate_preset", preset_id=recipe["preset_id"])
    lines = [
        "# ComfyUI Dry Run",
        "",
        "No workflow was submitted to ComfyUI.",
        "",
        f"- Preset: `{recipe['preset_id']}`",
        f"- Workflow: `{recipe['workflow_file_name']}`",
        f"- Workflow hash: `{recipe.get('workflow_hash') or ''}`",
        f"- Input mode: `{recipe['input_mode']}`",
        f"- Preset valid: `{bool(validation.get('valid'))}`",
        f"- Parameters: `{len(recipe.get('values') or {})}`",
    ]
    if validation.get("errors"):
        lines.append(f"- Errors: {', '.join(validation['errors'])}")
    if validation.get("warnings"):
        lines.append(f"- Warnings: {', '.join(validation['warnings'])}")
    await ctx.reply_markdown("\n".join(lines))


async def list_presets(ctx):
    recipe, preset, presets, state = await current_recipe(ctx)
    lines = ["# ComfyUI Presets", ""]
    if not presets:
        lines.append("No presets found. Run `@comfyui_agent:scan_workflows` after adding API-format workflow JSON files.")
    for item in presets:
        current = " current" if recipe and item.get("preset_id") == recipe.get("preset_id") else ""
        lines.append(
            f"- `{item.get('preset_id')}`{current}: {item.get('status')} valid={item.get('valid')} workflow=`{item.get('workflow', {}).get('file_name', '')}`"
        )
    await ctx.reply_markdown("\n".join(lines))


async def scan_workflows(ctx):
    scan = await call_comfy(ctx, "scan_workflow_library")
    lines = [
        "# ComfyUI Workflow Scan",
        "",
        f"- Workflows: `{len(scan.get('workflows') or [])}`",
        f"- Presets: `{len(scan.get('presets') or [])}`",
        f"- Duplicates: `{len(scan.get('duplicates') or [])}`",
        f"- Missing preset workflows: `{len(scan.get('missing_preset_workflows') or [])}`",
        f"- Created draft presets: `{len(scan.get('created_draft_presets') or [])}`",
    ]
    await ctx.reply_markdown("\n".join(lines))


async def status_action(ctx):
    connection = await call_comfy(ctx, "test_connection")
    scan = await call_comfy(ctx, "scan_workflow_library")
    recipe, preset, presets, state = await current_recipe(ctx, scan)
    lines = [
        "# ComfyUI Status",
        "",
        f"- Connection reachable: `{bool(connection.get('reachable'))}`",
        f"- Workflows dir: `{scan.get('workflows_dir')}`",
        f"- Presets dir: `{scan.get('presets_dir')}`",
        f"- Workflow files: `{len(scan.get('workflows') or [])}`",
        f"- Presets: `{len(scan.get('presets') or [])}`",
        f"- Current recipe preset: `{recipe.get('preset_id') if recipe else ''}`",
        f"- Recipe status: `{state.get('status')}`",
        "",
        "Real ComfyUI generation is not implemented in this round.",
    ]
    await ctx.reply_markdown("\n".join(lines))


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
        {"type": "markdown", "text": _recipe_markdown(next_recipe, title, "Form values update only this session recipe, not preset files.")},
        recipe_to_form(next_recipe, next_preset, presets),
    ])


async def current_recipe(ctx, scan: dict | None = None):
    scan = scan or await call_comfy(ctx, "scan_workflow_library")
    presets = [item for item in scan.get("presets", []) if item.get("valid") and item.get("status") != "disabled"]
    stored = ctx.state.get(RECIPE_KEY)
    if isinstance(stored, dict) and stored.get("preset_id"):
        preset = _preset_by_id(presets, stored.get("preset_id"))
        return stored, preset, presets, {"status": "loaded"}
    default_id = str(ctx.config.get("default_preset_id") or "")
    default_mode = _input_mode(ctx.config.get("default_input_mode") or "llm")
    preset = _preset_by_id(presets, default_id) if default_id else None
    if preset is None:
        preset = next((item for item in presets if item.get("status") == "ready"), None)
    if preset is None:
        return None, None, presets, {"status": "needs_preset", "message": "No valid ready ComfyUI preset is available."}
    loaded = await call_comfy(ctx, "load_preset", preset_id=preset["preset_id"])
    preset_data = loaded.get("preset") or {"parameters": preset.get("parameters") or []}
    recipe = recipe_from_preset(preset_data, default_mode)
    save_recipe(ctx, recipe)
    return recipe, preset, presets, {"status": "created_from_default"}


def recipe_from_preset(preset: dict, default_input_mode: str) -> dict:
    values = {}
    for parameter in preset.get("parameters") or []:
        if not isinstance(parameter, dict) or not parameter.get("name"):
            continue
        values[str(parameter["name"])] = parameter.get("default")
    workflow = preset.get("workflow") or {}
    return {
        "preset_id": preset.get("id") or "",
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
            "description": "Used when input_mode=llm. This round stores the request but does not call an LLM.",
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
        "description": "Edits the current session recipe only. Submit refreshes fields after a preset change.",
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
        if name in prefill:
            value = prefill[name]
        else:
            value = recipe["values"].get(name, parameter.get("default"))
        if parameter.get("required") and value in (None, ""):
            errors.append(f"Missing required field: {name}")
        recipe["values"][name] = value
    recipe["updated_at"] = _now()
    return recipe, preset, switched, errors


async def call_comfy(ctx, method_name: str, **kwargs) -> dict:
    result = await getattr(ctx.capability("comfyui"), method_name)(**kwargs)
    if not result.success:
        return {"valid": False, "errors": [result.error or "ComfyUI capability call failed."]}
    return result.data or {}


def save_recipe(ctx, recipe: dict) -> None:
    recipe["input_mode"] = _input_mode(recipe.get("input_mode") or "llm")
    recipe["updated_at"] = _now()
    ctx.state.set(RECIPE_KEY, recipe)


def _preset_by_id(presets: list[dict], preset_id: str | None) -> dict | None:
    return next((item for item in presets if item.get("preset_id") == preset_id), None)


def _input_mode(value: Any) -> str:
    value = str(value or "llm").lower()
    return value if value in INPUT_MODES else "llm"


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
        "",
        "`@comfyui_agent:run` is a dry-run in this round; it does not submit to ComfyUI.",
    ])


def _no_recipe_markdown(state: dict) -> str:
    return "# ComfyUI recipe unavailable\n\n" + str(state.get("message") or "Configure at least one ready preset first.")


def _summary_block(state: dict) -> dict:
    return {"type": "markdown", "text": f"Recipe status: `{state.get('status')}`. Real generation is not implemented in this round."}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
