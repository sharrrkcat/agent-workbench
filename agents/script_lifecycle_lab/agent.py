import asyncio
import json
import re
from typing import Any


EXTRACTION_SYSTEM_PROMPT = (
    "You extract project briefs as strict JSON. Return only JSON with keys: "
    "title, summary, features, risks, next_steps. "
    "features, risks, and next_steps must be arrays of strings."
)


async def run(ctx):
    if ctx.action_id in {"default", "steps"}:
        await run_steps(ctx)
        return
    if ctx.action_id == "hidden_json":
        await run_hidden_json(ctx)
        return
    if ctx.action_id == "public_stream":
        await run_public_stream(ctx)
        return
    raise ValueError(f"Unknown action: {ctx.action_id}")


async def run_steps(ctx) -> None:
    user_input = ctx.input.text
    await _sleeping_step(ctx, "Prepare input", "Capturing user input.", 1)
    await _sleeping_step(ctx, "Simulate data read", "Pretending to read local data.", 2)
    await _sleeping_step(ctx, "Simulate processing", "Processing the input.", 3)
    await _sleeping_step(ctx, "Render final report", "Building final markdown.", 0.5)

    await ctx.reply_markdown(
        "# Step Test Complete\n\n"
        f"- Input: {user_input}\n"
        "- Steps: 4\n"
        "- Simulated work: about 6.5 seconds"
    )


async def run_hidden_json(ctx) -> None:
    user_input = ctx.input.text
    prompt = ""
    buffer: list[str] = []

    step = ctx.run.start_step("Build extraction prompt", message="Building structured extraction prompt.")
    try:
        prompt = user_input
        ctx.run.complete_step(step.step_id, message="Extraction prompt ready.")
    except Exception as exc:
        ctx.run.fail_step(step.step_id, error_message=str(exc) or "Prompt build failed.")
        raise

    step = ctx.run.start_step("LLM extracts structured JSON", message="Streaming structured data internally.")
    try:
        async for chunk in ctx.llm.stream(system=EXTRACTION_SYSTEM_PROMPT, user=prompt):
            buffer.append(chunk.text)
        ctx.run.complete_step(step.step_id, message="Internal JSON stream received.")
    except Exception as exc:
        ctx.run.fail_step(step.step_id, error_message=str(exc) or "LLM extraction failed.")
        await ctx.reply_markdown(
            "# JSON extraction failed\n\n"
            "The model response could not be parsed as JSON.\n\n"
            "LLM extraction failed before a valid response was available."
        )
        return

    step = ctx.run.start_step("Parse JSON", message="Parsing internal model response.")
    try:
        data = _parse_json_object("".join(buffer))
        ctx.run.complete_step(step.step_id, message="JSON parsed.")
    except ValueError as exc:
        ctx.run.fail_step(step.step_id, error_message=str(exc))
        await ctx.reply_markdown(
            "# JSON extraction failed\n\n"
            "The model response could not be parsed as JSON."
        )
        return

    step = ctx.run.start_step("Normalize fields", message="Normalizing required fields.")
    try:
        normalized = _normalize_brief(data)
        ctx.run.complete_step(step.step_id, message="Fields normalized.")
    except Exception as exc:
        ctx.run.fail_step(step.step_id, error_message=str(exc) or "Field normalization failed.")
        raise

    step = ctx.run.start_step("Render final markdown", message="Rendering public markdown.")
    try:
        markdown = _render_brief(normalized)
        ctx.run.complete_step(step.step_id, message="Markdown ready.")
    except Exception as exc:
        ctx.run.fail_step(step.step_id, error_message=str(exc) or "Markdown rendering failed.")
        raise

    await ctx.reply_markdown(markdown)


async def run_public_stream(ctx) -> None:
    system = "You write clear, concise explanations."
    user = f"Explain the following topic in three concise paragraphs:\n{ctx.input.text}"

    step = ctx.run.start_step("Prepare streaming response", message="Building public streaming prompt.")
    try:
        ctx.run.complete_step(step.step_id, message="Streaming prompt ready.")
    except Exception as exc:
        ctx.run.fail_step(step.step_id, error_message=str(exc) or "Prompt preparation failed.")
        raise

    step = ctx.run.start_step("Stream response to chat", message="Streaming text to the assistant message.")
    try:
        await ctx.llm.stream_to_output(system=system, user=user, format="markdown")
        ctx.run.complete_step(step.step_id, message="Public stream completed.")
    except Exception as exc:
        ctx.run.fail_step(step.step_id, error_message=str(exc) or "Public stream failed.")
        raise

    step = ctx.run.start_step("Finalize", message="Finalizing streamed output.")
    try:
        await ctx.output.finish()
        ctx.run.complete_step(step.step_id, message="Output finalized.")
    except Exception as exc:
        ctx.run.fail_step(step.step_id, error_message=str(exc) or "Finalize failed.")
        raise


async def _sleeping_step(ctx, label: str, message: str, seconds: float) -> None:
    step = ctx.run.start_step(label, message=message)
    try:
        await asyncio.sleep(seconds)
        ctx.run.complete_step(step.step_id, message=message)
    except Exception as exc:
        ctx.run.fail_step(step.step_id, error_message=str(exc) or f"{label} failed.")
        raise


def _parse_json_object(content: str) -> dict[str, Any]:
    text = _extract_json_text(content)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON root must be an object.")
    return parsed


def _extract_json_text(content: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return content.strip()


def _normalize_brief(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _string_field(data.get("title"), "Untitled brief"),
        "summary": _string_field(data.get("summary"), "No summary provided."),
        "features": _string_list(data.get("features")),
        "risks": _string_list(data.get("risks")),
        "next_steps": _string_list(data.get("next_steps")),
    }


def _string_field(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _render_brief(data: dict[str, Any]) -> str:
    return (
        f"# {data['title']}\n\n"
        f"## Summary\n{data['summary']}\n\n"
        f"## Features\n{_render_list(data['features'])}\n\n"
        f"## Risks\n{_render_list(data['risks'])}\n\n"
        f"## Next steps\n{_render_list(data['next_steps'])}"
    )


def _render_list(items: list[str]) -> str:
    if not items:
        return "- None identified."
    return "\n".join(f"- {item}" for item in items)
