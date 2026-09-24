"""Local SigLIP-family file selection. No inference imports or checkpoint validation."""
import json
from pathlib import Path

if __package__:
    from .common import WorkerError, safe_reference
else:
    from common import WorkerError, safe_reference

STRUCTURES = {"siglip": "fixres", "siglip2": "naflex"}
CONFIG_FILES = ("config.json", "preprocessor_config.json", "tokenizer_config.json")


def model_directory(root: Path, ref: str) -> Path:
    try:
        path = (root / safe_reference(ref)).resolve()
    except ValueError as exc:
        raise WorkerError("INVALID_REQUEST") from exc
    if not path.is_relative_to(root.resolve()):
        raise WorkerError("INVALID_REQUEST")
    if not path.is_dir():
        raise WorkerError("MODEL_NOT_FOUND", 404)
    return path


def model_file(path: Path, name: str) -> Path:
    try:
        target = (path / safe_reference(name)).resolve()
    except ValueError as exc:
        raise WorkerError("INVALID_REQUEST") from exc
    if not target.is_relative_to(path.resolve()):
        raise WorkerError("INVALID_REQUEST")
    return target


def read_config(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"),
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
    if not isinstance(value, dict):
        raise ValueError("Configuration must be an object")
    return value


def model_presence(root: Path, ref: str) -> Path:
    """Cheap status checks: no config/index parsing and no weight content reads."""
    path = model_directory(root, ref)
    if (any(not model_file(path, name).is_file() for name in (*CONFIG_FILES, "tokenizer.json"))
            or not any(model_file(path, name).is_file() for name in ("model.safetensors", "model.safetensors.index.json"))):
        raise WorkerError("MODEL_NOT_FOUND", 404)
    return path


def model_files(path: Path) -> list[str]:
    """Select the same safetensors and tokenizer assets used by the native loaders."""
    names = [*CONFIG_FILES, "tokenizer.json"]
    if model_file(path, "model.safetensors").is_file():
        names.append("model.safetensors")
    else:
        names.append("model.safetensors.index.json")
        try:
            index = read_config(model_file(path, names[-1]))
            shards = index["weight_map"]
            if not isinstance(shards, dict) or not shards or any(not isinstance(k, str) for k in shards):
                raise ValueError("Invalid shard index")
            names.extend(safe_reference(name) for name in shards.values())
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise WorkerError("MODEL_NOT_FOUND", 404) from exc
    if any(not model_file(path, name).is_file() for name in names):
        raise WorkerError("MODEL_NOT_FOUND", 404)
    try:
        tokenizer = read_config(model_file(path, "tokenizer_config.json"))
    except (OSError, ValueError) as exc:
        raise WorkerError("MODEL_UNAVAILABLE", 503) from exc
    # Transformers 5 reads these optional files only without an embedded token map.
    if "added_tokens_decoder" not in tokenizer:
        names.extend(name for name in ("special_tokens_map.json", "added_tokens.json")
                     if model_file(path, name).is_file())
    return sorted(set(names))
