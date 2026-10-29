from __future__ import annotations

import base64
import binascii

from ai_workbench.core.harness.schema import ToolExecutionContext, ToolExecutionError, ToolSpec


CODEC_MAX_BYTES = 1024 * 1024


async def base64_encode(arguments: dict, _context: ToolExecutionContext) -> dict:
    value = str(arguments["value"])
    data = value.encode("utf-8")
    if len(data) > CODEC_MAX_BYTES:
        raise ToolExecutionError("CODEC_INPUT_TOO_LARGE", "Codec input exceeds the 1 MiB limit.")
    encoded = base64.b64encode(data)
    if len(encoded) > CODEC_MAX_BYTES:
        raise ToolExecutionError("CODEC_OUTPUT_TOO_LARGE", "Codec output exceeds the 1 MiB limit.")
    return {"value": encoded.decode("ascii"), "encoding": "base64", "input_bytes": len(data)}


async def base64_decode(arguments: dict, _context: ToolExecutionContext) -> dict:
    value = str(arguments["value"])
    if len(value.encode("utf-8")) > CODEC_MAX_BYTES:
        raise ToolExecutionError("CODEC_INPUT_TOO_LARGE", "Codec input exceeds the 1 MiB limit.")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ToolExecutionError("CODEC_INVALID_BASE64", "Value is not valid base64.") from exc
    if len(data) > CODEC_MAX_BYTES:
        raise ToolExecutionError("CODEC_OUTPUT_TOO_LARGE", "Codec output exceeds the 1 MiB limit.")
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolExecutionError("CODEC_INVALID_UTF8", "Decoded bytes are not valid UTF-8 text.") from exc
    return {"value": decoded, "encoding": "utf-8", "output_bytes": len(data)}


def register_builtin_tools(registry) -> None:
    obj = {"type": "object"}
    for name, description, handler in (("base64_encode", "Encode UTF-8 text as base64.", base64_encode), ("base64_decode", "Decode base64 as UTF-8 text.", base64_decode)):
        registry.register(ToolSpec(name, description, {**obj, "properties": {"value": {"type": "string"}}, "required": ["value"], "additionalProperties": False}, handler, "safe", False, True))
