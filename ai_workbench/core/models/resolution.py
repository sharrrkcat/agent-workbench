"""Apply directory-derived engine semantics at the model service boundary."""
from pathlib import Path

from pydantic import ValidationError

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import engine_options, local_engine
from ai_workbench.core.models.schema import ChatterboxParameters, KokoroParameters, LocalSource, Qwen3TTSParameters
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers.model_catalog import inspect_directory


TTS_SCHEMAS = {"kokoro": KokoroParameters, "chatterbox": ChatterboxParameters, "qwen3tts": Qwen3TTSParameters}


def resolve_profile(root: Path, profile):
    if isinstance(profile.source, LocalSource) and profile.kind in {"llm", "tts", "vision"} and profile._directory is None:
        try:
            profile._directory = inspect_directory(root / "data/models", profile.kind, profile.model_ref)
        except WorkerError as exc:
            raise ModelError(exc.code, "Use a model directory with a safe relative path under data/models.", exc.status) from exc
    return profile


def configure_profile(profile):
    engine = local_engine(profile)
    if engine is None:
        return profile
    try:
        profile.source.execution_options = engine_options(engine, profile.source.execution_options).model_validate(profile.source.execution_options).model_dump()
        if profile.kind == "tts":
            profile.parameters = TTS_SCHEMAS[engine].model_validate(profile.parameters).model_dump()
        if engine == "transformers":
            if profile.capabilities.json_object or profile.capabilities.json_schema:
                raise ValueError("Transformers does not support structured JSON output")
            if any(profile.parameters.get(key, 0) != 0 for key in ("presence_penalty", "frequency_penalty")):
                raise ValueError("Transformers does not support nonzero presence or frequency penalties")
    except (ValidationError, ValueError) as exc:
        raise ModelError("INVALID_REQUEST", "Parameters or execution options do not match the detected local engine.", 422) from exc
    return profile


def require_directory(profile):
    info = profile._directory
    if info is None:
        return
    try:
        info.require_complete()
    except WorkerError as exc:
        message = next(item["message"] for item in info.diagnostics if item["blocking"])
        raise ModelError(exc.code, message, exc.status) from exc
    if info.engine == "llama-server" and profile.capabilities.vision and info.mmproj_ref is None:
        raise ModelError("UNSUPPORTED_CAPABILITY", "Vision requires one mmproj GGUF in the selected directory.", 422)
