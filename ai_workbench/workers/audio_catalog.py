"""Dependency-free contracts for the managed Audio family."""
import json
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
QWEN3TTS_DEFAULTS = {
    "do_sample": True, "temperature": 0.9, "top_p": 1.0, "top_k": 50,
    "repetition_penalty": 1.05, "max_new_tokens": 2048,
}
QWEN3TTS_SUBTALKER = {
    "subtalker_dosample": True, "subtalker_temperature": 0.9,
    "subtalker_top_p": 1.0, "subtalker_top_k": 50,
}
AUDIO_DEFAULTS = {"chatterbox": CHATTERBOX_DEFAULTS, "qwen3tts": QWEN3TTS_DEFAULTS}
QWEN3TTS_LANGUAGES = {
    "auto": "Auto", "en-US": "English", "en-GB": "English", "zh-CN": "Chinese",
    "ja-JP": "Japanese", "ko-KR": "Korean", "de-DE": "German", "fr-FR": "French",
    "ru-RU": "Russian", "pt-BR": "Portuguese", "es-ES": "Spanish", "it-IT": "Italian",
}


def _local_file(path: Path, root: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0 and path.resolve().is_relative_to(root.resolve())


def _config(path: Path) -> dict:
    if not 0 < path.stat().st_size <= 1024 * 1024:
        raise ValueError("Invalid model metadata size")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid model metadata")
    return value


def _safetensors(path: Path) -> bool:
    index = path / "model.safetensors.index.json"
    if index.is_file():
        if not _local_file(index, path):
            return False
        shards = _config(index).get("weight_map")
        if not isinstance(shards, dict) or not shards:
            return False
        return all(isinstance(name, str) and name.endswith(".safetensors")
                   and _local_file(path / safe_reference(name), path) for name in shards.values())
    return _local_file(path / "model.safetensors", path)


def validate_qwen3tts(path: Path) -> None:
    """Inspect the complete local Base layout before an engine can import or load."""
    try:
        if not path.is_dir():
            raise WorkerError("MODEL_NOT_FOUND", 404)
        if any(not item.resolve().is_relative_to(path.resolve()) for item in path.rglob("*")):
            raise WorkerError("INVALID_REQUEST")
        config = _config(path / "config.json")
        if (config.get("model_type"), config.get("tts_model_type"), config.get("tokenizer_type")) != (
            "qwen3_tts", "base", "qwen3_tts_tokenizer_12hz"
        ):
            raise WorkerError("UNSUPPORTED_CAPABILITY")
        for name in ("generation_config.json", "tokenizer_config.json", "preprocessor_config.json",
                     "speech_tokenizer/config.json", "speech_tokenizer/preprocessor_config.json"):
            if not _local_file(path / name, path):
                raise WorkerError("MODEL_NOT_FOUND", 404)
            _config(path / name)
        text_tokenizer = _local_file(path / "tokenizer.json", path) or all(
            _local_file(path / name, path) for name in ("vocab.json", "merges.txt"))
        tokenizer = path / "speech_tokenizer"
        if (_config(tokenizer / "config.json").get("model_type") != "qwen3_tts_tokenizer_12hz"
                or not text_tokenizer or not _safetensors(path) or not _safetensors(tokenizer)):
            raise WorkerError("MODEL_NOT_FOUND", 404)
    except (OSError, ValueError, TypeError) as exc:
        raise WorkerError("MODEL_NOT_FOUND", 404) from exc


def qwen3tts_files(path: Path) -> bool:
    try:
        validate_qwen3tts(path)
        return True
    except WorkerError:
        return False


def chatterbox_files(path: Path) -> bool:
    try:
        return all((path / name).is_file() and (path / name).stat().st_size > 0
                   and (path / name).resolve().is_relative_to(path.resolve()) for name in CHATTERBOX_FILES)
    except OSError:
        return False


def audio_model(root: Path, ref: str, architecture: str) -> Path:
    if architecture not in AUDIO_DEFAULTS:
        return local_model(root, ref)
    path = (root / safe_reference(ref)).resolve()
    if not path.is_relative_to(root.resolve()) or any(
        not item.resolve().is_relative_to(path) for item in path.rglob("*")
    ):
        raise WorkerError("INVALID_REQUEST")
    if architecture == "qwen3tts":
        validate_qwen3tts(path)
    elif not chatterbox_files(path):
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
