"""Dependency-free contracts for the managed Audio family."""
from pathlib import Path

if __package__:
    from .common import WorkerError, safe_reference, local_model
else:
    from common import WorkerError, safe_reference, local_model

CHATTERBOX_FILES = ("ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json")
MAX_REFERENCE_BYTES = 8 * 1024 * 1024
MAX_REFERENCE_SECONDS = 30
MAX_DECODED_BYTES = 32 * 1024 * 1024
CHATTERBOX_DEFAULTS = {
    "exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8,
    "repetition_penalty": 1.2, "min_p": 0.05, "top_p": 1.0,
}


def chatterbox_files(path: Path) -> bool:
    try:
        return all((path / name).is_file() and (path / name).stat().st_size > 0
                   and (path / name).resolve().is_relative_to(path.resolve()) for name in CHATTERBOX_FILES)
    except OSError:
        return False


def audio_model(root: Path, ref: str, architecture: str) -> Path:
    if architecture != "chatterbox":
        return local_model(root, ref)
    path = (root / safe_reference(ref)).resolve()
    if not path.is_relative_to(root.resolve()) or any(
        not item.resolve().is_relative_to(path) for item in path.rglob("*")
    ):
        raise WorkerError("INVALID_REQUEST")
    if not chatterbox_files(path):
        raise WorkerError("MODEL_NOT_FOUND", 404)
    return path


def reference_path(root: Path, ref: str) -> Path:
    safe_reference(ref)
    path = (root / ref).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or path.suffix not in {".wav", ".mp3"}:
        raise WorkerError("VOICE_UNAVAILABLE", 404)
    if not 0 < path.stat().st_size <= MAX_REFERENCE_BYTES:
        raise WorkerError("REQUEST_TOO_LARGE", 413)
    return path
