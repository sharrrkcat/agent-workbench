from __future__ import annotations

from typing import Any


FORM_ID = "image_generation_txt2img"
SAMPLERS = ["euler", "euler_a", "dpmpp_2m", "dpmpp_sde", "ddim"]
SCHEDULERS = ["normal", "karras", "exponential", "simple"]


class ImageGeneratorAgentError(RuntimeError):
    pass


async def run(ctx):
    action = ctx.action_id or "default"
    if action in {"default", "form"}:
        await show_form(ctx, initial_prompt=ctx.input.text.strip() if action == "default" else "")
        return
    if action == "generate_from_form":
        return await generate_from_form(ctx)
    if action == "status":
        result = await ctx.capability("image_generation").status()
        if not result.success:
            raise ImageGeneratorAgentError(result.error or "Image generation status failed.")
        await ctx.reply_json(result.data or {})
        return result.data or {}
    await show_form(ctx, initial_prompt=ctx.input.text.strip())


async def show_form(ctx, initial_prompt: str = "") -> None:
    profiles = await list_enabled_profiles(ctx)
    if not profiles:
        await ctx.reply_markdown(
            "# Image generation unavailable\n\n"
            "Create and enable at least one Image Model Profile before generating images."
        )
        return
    selected = select_profile(ctx, profiles)
    await ctx.reply_blocks([txt2img_form(profiles, selected, initial_prompt)])


async def generate_from_form(ctx) -> dict:
    values = dict(ctx.input.prefill or {})
    async with ctx.step("Validate image request"):
        request = request_from_form(values)
        validation = await call_image_generation(ctx, "validate_txt2img", **request)
    async with ctx.step("Generate image") as step:
        result = await call_image_generation(ctx, "txt2img", **request)
        queue = queue_metadata_from_result(result)
        ctx.run.update_step(
            step.step.step_id,
            message=queue_step_message(queue),
            metadata={"image_generation_queue": queue} if queue else None,
        )
    async with ctx.step("Save attachments"):
        attachments = []
        for image in result.get("images") or []:
            attachments.append(await save_generated_image(ctx, result, image))
    metadata = compact_generation_metadata(result, validation, attachments)
    record_run_metadata(ctx, metadata)
    gallery = [
        {
            "url": attachment["url"],
            "attachment_id": attachment["id"],
            "alt": attachment.get("name") or "Generated image",
            "title": attachment.get("name") or "Generated image",
        }
        for attachment in attachments
    ]
    async with ctx.step("Render result"):
        await ctx.reply_images(gallery, metadata={"image_generation": metadata})
    return metadata


async def list_enabled_profiles(ctx) -> list[dict]:
    result = await ctx.capability("image_generation").list_model_profiles(enabled_only=True)
    if not result.success:
        raise ImageGeneratorAgentError(result.error or "Image generation profile listing failed.")
    return list(result.data or [])


async def call_image_generation(ctx, method_name: str, **kwargs: Any) -> dict:
    result = await getattr(ctx.capability("image_generation"), method_name)(**kwargs)
    if not result.success:
        raise ImageGeneratorAgentError(result.error or f"Image generation capability call failed: {method_name}")
    return result.data or {}


def select_profile(ctx, profiles: list[dict]) -> dict:
    configured = str((ctx.config or {}).get("default_profile_id_or_alias") or "").strip()
    if configured:
        for profile in profiles:
            if configured in {profile.get("id"), profile.get("alias")}:
                return profile
    return profiles[0]


def txt2img_form(profiles: list[dict], selected: dict, initial_prompt: str = "") -> dict:
    selected_id = selected.get("alias") or selected.get("id") or ""
    return {
        "type": "action_form",
        "form_id": FORM_ID,
        "title": "Text to Image",
        "description": "Internal txt2img generation uses the selected Image Model Profile.",
        "sections": [
            {"key": "model", "title": "Model"},
            {"key": "prompts", "title": "Prompts"},
            {"key": "sampling", "title": "Sampling"},
            {"key": "size", "title": "Size"},
            {"key": "advanced", "title": "Advanced"},
        ],
        "fields": [
            {
                "name": "profile_id_or_alias",
                "type": "enum",
                "label": "Model Profile",
                "required": True,
                "options": [
                    {
                        "value": profile.get("alias") or profile.get("id"),
                        "label": profile_label(profile),
                    }
                    for profile in profiles
                ],
                "value": selected_id,
                "ui": {"section": "model", "span": 12},
            },
            {
                "name": "positive_prompt",
                "type": "textarea",
                "label": "Positive Prompt",
                "required": True,
                "min_length": 1,
                "max_length": 8000,
                "value": initial_prompt,
                "ui": {"section": "prompts", "span": 12},
            },
            {
                "name": "negative_prompt",
                "type": "textarea",
                "label": "Negative Prompt",
                "max_length": 8000,
                "value": "",
                "ui": {"section": "prompts", "span": 12},
            },
            {
                "name": "width",
                "type": "integer",
                "label": "Width",
                "minimum": 64,
                "maximum": 2048,
                "step": 8,
                "value": 1024,
                "ui": {"section": "size", "span": 6},
            },
            {
                "name": "height",
                "type": "integer",
                "label": "Height",
                "minimum": 64,
                "maximum": 2048,
                "step": 8,
                "value": 1024,
                "ui": {"section": "size", "span": 6},
            },
            {
                "name": "steps",
                "type": "integer",
                "label": "Steps",
                "minimum": 1,
                "maximum": 150,
                "step": 1,
                "value": 30,
                "ui": {"section": "sampling", "span": 4},
            },
            {
                "name": "cfg",
                "type": "float",
                "label": "CFG",
                "minimum": 0,
                "maximum": 30,
                "step": 0.5,
                "value": 7.0,
                "ui": {"section": "sampling", "span": 4},
            },
            {
                "name": "batch_size",
                "type": "integer",
                "label": "Batch Size",
                "minimum": 1,
                "maximum": 4,
                "step": 1,
                "value": 1,
                "ui": {"section": "sampling", "span": 4},
            },
            {
                "name": "sampler",
                "type": "enum",
                "label": "Sampler",
                "options": [{"value": item, "label": sampler_label(item)} for item in SAMPLERS],
                "value": "euler",
                "ui": {"section": "sampling", "span": 6},
            },
            {
                "name": "scheduler",
                "type": "enum",
                "label": "Scheduler",
                "options": [{"value": item, "label": scheduler_label(item)} for item in SCHEDULERS],
                "value": "normal",
                "ui": {"section": "sampling", "span": 6},
            },
            {
                "name": "seed",
                "type": "integer",
                "label": "Seed",
                "minimum": -1,
                "maximum": 4294967295,
                "step": 1,
                "value": -1,
                "ui": {"section": "advanced", "span": 6},
            },
            {
                "name": "loras",
                "type": "json",
                "label": "LoRAs",
                "value": [],
                "ui": {"section": "advanced", "span": 6},
            },
        ],
        "submit": {
            "label": "Generate",
            "action_id": "generate_from_form",
            "message": "Submitted image generation form",
        },
    }


def request_from_form(values: dict[str, Any]) -> dict[str, Any]:
    seed = values.get("seed")
    if seed is not None:
        seed = int(seed)
    return {
        "profile_id_or_alias": values.get("profile_id_or_alias"),
        "positive_prompt": values.get("positive_prompt"),
        "negative_prompt": values.get("negative_prompt") or "",
        "width": values.get("width"),
        "height": values.get("height"),
        "steps": values.get("steps"),
        "cfg": values.get("cfg"),
        "sampler": values.get("sampler") or "euler",
        "scheduler": values.get("scheduler") or "normal",
        "seed": None if seed is None or seed < 0 else seed,
        "batch_size": values.get("batch_size") or 1,
        "loras": values.get("loras") or [],
    }


async def save_generated_image(ctx, result: dict, image: dict) -> dict:
    metadata = {
        "source": "image_generation",
        "backend": result.get("backend"),
        "real_generation": bool(result.get("real_generation")),
        "request_id": result.get("request_id"),
        "profile_id": (result.get("profile") or {}).get("id"),
        "profile_alias": (result.get("profile") or {}).get("alias"),
        "task": "txt2img",
        "seed": image.get("seed"),
        "index": image.get("index"),
        "width": image.get("width"),
        "height": image.get("height"),
    }
    return await ctx.save_attachment_base64(
        image.get("data_base64") or "",
        filename=image.get("filename") or "image-generation.png",
        mime_type=image.get("mime_type") or "image/png",
        kind="image",
        metadata=metadata,
    )


def compact_generation_metadata(result: dict, validation: dict, attachments: list[dict]) -> dict:
    profile = result.get("profile") or validation.get("profile") or {}
    request = result.get("request") or validation.get("request") or {}
    queue = queue_metadata_from_result(result)
    return {
        "kind": "image_generation_txt2img",
        "request_id": result.get("request_id"),
        "backend": result.get("backend"),
        "real_generation": bool(result.get("real_generation")),
        "task": "txt2img",
        "profile": {
            "id": profile.get("id"),
            "alias": profile.get("alias"),
            "name": profile.get("name"),
            "architecture": profile.get("architecture"),
            "variant": profile.get("variant"),
        },
        "request": {
            "width": request.get("width"),
            "height": request.get("height"),
            "steps": request.get("steps"),
            "cfg": request.get("cfg"),
            "sampler": request.get("sampler"),
            "scheduler": request.get("scheduler"),
            "seed": request.get("seed"),
            "batch_size": request.get("batch_size"),
            "lora_count": request.get("lora_count", 0),
            "positive_prompt_chars": request.get("positive_prompt_chars", 0),
            "negative_prompt_chars": request.get("negative_prompt_chars", 0),
            "positive_prompt_sha256": request.get("positive_prompt_sha256"),
            "negative_prompt_sha256": request.get("negative_prompt_sha256"),
        },
        "queue": queue,
        "output_count": len(attachments),
        "attachment_ids": [attachment.get("id") for attachment in attachments if attachment.get("id")],
    }


def record_run_metadata(ctx, metadata: dict) -> None:
    try:
        run = ctx.run_store.get_run(ctx.run_id)
        next_metadata = dict(run.metadata or {})
        next_metadata["image_generation"] = metadata
        ctx.run_store.update_metadata(ctx.run_id, next_metadata)
    except Exception:
        return


def queue_metadata_from_result(result: dict) -> dict:
    raw = result.get("queue")
    if not isinstance(raw, dict):
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        raw = metadata.get("queue") if isinstance(metadata.get("queue"), dict) else {}
    if not raw:
        return {}
    return {
        "request_id": raw.get("request_id"),
        "run_id": raw.get("run_id"),
        "status": raw.get("status"),
        "queue_wait_ms": raw.get("queue_wait_ms"),
        "execution_ms": raw.get("execution_ms"),
        "cancel_requested": bool(raw.get("cancel_requested")),
    }


def queue_step_message(queue: dict) -> str:
    if not queue:
        return "generated"
    wait_ms = queue.get("queue_wait_ms")
    execution_ms = queue.get("execution_ms")
    parts = []
    if isinstance(wait_ms, int):
        parts.append(f"wait {wait_ms} ms")
    if isinstance(execution_ms, int):
        parts.append(f"execute {execution_ms} ms")
    return ", ".join(parts) if parts else str(queue.get("status") or "generated")


def profile_label(profile: dict) -> str:
    name = profile.get("name") or profile.get("alias") or profile.get("id") or "Image Model"
    alias = profile.get("alias")
    architecture = profile.get("architecture")
    variant = profile.get("variant")
    suffix = " / ".join(str(item) for item in [architecture, variant] if item)
    if alias and alias != name:
        return f"{name} ({alias}) - {suffix}" if suffix else f"{name} ({alias})"
    return f"{name} - {suffix}" if suffix else str(name)


def sampler_label(value: str) -> str:
    return {
        "euler": "Euler",
        "euler_a": "Euler a",
        "dpmpp_2m": "DPM++ 2M",
        "dpmpp_sde": "DPM++ SDE",
        "ddim": "DDIM",
    }.get(value, value)


def scheduler_label(value: str) -> str:
    return {
        "normal": "Normal",
        "karras": "Karras",
        "exponential": "Exponential",
        "simple": "Simple",
    }.get(value, value)
