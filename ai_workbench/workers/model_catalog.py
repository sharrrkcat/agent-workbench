"""Directory discovery for local LLM, TTS and tagging, without inference imports."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

if __package__:
    from .common import WorkerError, safe_reference
    from .audio_catalog import CHATTERBOX_FILES, validate_qwen3tts
else:
    from common import WorkerError, safe_reference
    from audio_catalog import CHATTERBOX_FILES, validate_qwen3tts


@dataclass
class DirectoryInformation:
    kind: str
    model_ref: str
    engine: str | None = None
    architecture: str | None = None
    main_model_ref: str | None = None
    mmproj_ref: str | None = None
    model_files: list[str] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)

    def diagnostic(self, file, code, message, *, blocking=True):
        self.diagnostics.append(dict(file=file, code=code, message=message, blocking=blocking))

    def require_complete(self):
        for item in self.diagnostics:
            if item["blocking"]:
                missing = item["code"] in {"missing_directory", "missing_file", "incomplete_shards"}
                raise WorkerError("MODEL_NOT_FOUND" if missing else "UNSUPPORTED_CAPABILITY", 404 if missing else 422)
        if self.engine is None:
            raise WorkerError("UNSUPPORTED_CAPABILITY")
        return self


def directory_path(root: Path, ref: str) -> Path:
    safe_reference(ref)
    if '\0' in ref:
        raise WorkerError("INVALID_REQUEST")
    path = (root / ref).resolve()
    if not path.is_relative_to(root.resolve()):
        raise WorkerError("INVALID_REQUEST")
    if path.exists() and not path.is_dir():
        raise WorkerError("INVALID_REQUEST")
    return path


def _file(path, name):
    target = path / safe_reference(name)
    if not target.resolve().is_relative_to(path):
        raise WorkerError("INVALID_REQUEST")
    return target


def _config(path, info, *, required=False, blocking=True):
    source = _file(path, "config.json")
    if not source.is_file():
        if required:
            info.diagnostic("config.json", "missing_file", "The model configuration is missing.", blocking=blocking)
        return {}
    try:
        if not 0 < source.stat().st_size <= 1024 * 1024:
            raise ValueError()
        value = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError):
        info.diagnostic("config.json", "invalid_config", "The configuration is not a readable JSON object.", blocking=blocking)
        return {}


def _required(path, info, names, *, nonempty=False):
    for name in names:
        source = _file(path, name)
        if not source.is_file() or nonempty and source.stat().st_size == 0:
            info.diagnostic(name, "missing_file", "A required model file is missing or empty.")


def _tts(path, info):
    chatterbox = _file(path, "t3_cfg.safetensors").is_file()
    config = _config(path, info, blocking=not chatterbox)
    model_type = config.get("model_type")
    candidates = (["chatterbox"] if chatterbox else [])
    if model_type == "style_text_to_speech_2":
        candidates.append("kokoro")
    if model_type == "qwen3_tts":
        candidates.append("qwen3tts")
    if len(candidates) > 1:
        info.diagnostic(".", "ambiguous_model", "The directory contains more than one TTS architecture.")
        return
    if not candidates:
        info.diagnostic(".", "unsupported_configuration", "No supported Kokoro ONNX, English Chatterbox or Qwen3-TTS Base layout was identified.")
        return
    engine = candidates[0]
    if engine == "qwen3tts" and (config.get("tts_model_type"), config.get("tokenizer_type")) != ("base", "qwen3_tts_tokenizer_12hz"):
        info.diagnostic("config.json", "unsupported_configuration", "Only Qwen3-TTS 12Hz Base is supported.")
        return
    if chatterbox and _file(path, "t3_turbo_v1.safetensors").is_file():
        info.diagnostic(".", "ambiguous_model", "Keep English Chatterbox and unsupported Turbo checkpoints in separate directories.")
        return
    info.engine = info.architecture = engine
    if engine == "kokoro":
        _required(path, info, ("config.json", "tokenizer.json", "tokenizer_config.json", "model.onnx"))
    elif engine == "chatterbox":
        _required(path, info, CHATTERBOX_FILES, nonempty=True)
    else:
        try:
            validate_qwen3tts(path)
        except WorkerError as exc:
            if exc.code == "INVALID_REQUEST":
                raise
            info.diagnostic(".", "missing_file" if exc.code == "MODEL_NOT_FOUND" else "unsupported_configuration",
                "Qwen3-TTS Base requires complete checkpoint, generation configuration, text tokenizer and nested speech_tokenizer files.")


def _vision(path, info):
    _required(path, info, ("model.onnx", "selected_tags.csv"))
    config = _config(path, info, blocking=False)
    if not any(item["blocking"] for item in info.diagnostics):
        info.engine = "wd14"
    declared = config.get("architecture")
    info.architecture = declared if isinstance(declared, str) and declared else None


SHARD = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)


def _llm(path, info):
    files = sorted((item for item in path.iterdir() if item.is_file()), key=lambda item: item.name.lower())
    gguf, projectors, weights = [], [], []
    for item in files:
        if item.suffix.lower() == ".gguf":
            _file(path, item.name)
            (projectors if item.name.lower().startswith("mmproj") else gguf).append(item.name)
        elif item.name.startswith(("model", "pytorch_model")) and item.suffix in {".safetensors", ".bin"}:
            _file(path, item.name)
            weights.append(item.name)
    config_file = _file(path, "config.json").is_file()
    if (gguf or projectors) and config_file and weights:
        info.diagnostic(".", "ambiguous_model", "Keep GGUF and Transformers checkpoints in separate model directories.")
        return
    if not gguf and not projectors:
        config = _config(path, info, required=True)
        if config_file:
            info.engine = "transformers"
            architectures = config.get("architectures")
            info.architecture = (architectures[0] if isinstance(architectures, list) and architectures
                and isinstance(architectures[0], str) else config.get("model_type") if isinstance(config.get("model_type"), str) else None)
        if not weights:
            info.diagnostic(".", "missing_file", "No Transformers checkpoint weights were found.")
        return
    info.engine = "llama-server"
    groups, candidates = {}, []
    for name in gguf:
        shard = SHARD.fullmatch(name)
        if shard:
            prefix, index, total = shard.groups()
            groups.setdefault((prefix.lower(), int(total)), []).append((int(index), name))
        else:
            candidates.append([name])
    for (_, total), parts in groups.items():
        ordered = sorted(parts)
        if total == 0 or len(parts) != total or [index for index, _ in ordered] != list(range(1, total + 1)):
            info.diagnostic(ordered[0][1], "incomplete_shards", "All numbered shards of the GGUF model must be present.")
        candidates.append([name for _, name in ordered])
    if len(candidates) != 1:
        info.diagnostic(".", "ambiguous_model" if candidates else "missing_file",
            "Use one GGUF main model or one complete shard group per directory.")
    else:
        info.model_files = [f"{info.model_ref}/{name}" for name in candidates[0]]
        if not any(item["code"] == "incomplete_shards" for item in info.diagnostics):
            info.main_model_ref = info.model_files[0]
    if len(projectors) > 1:
        info.diagnostic(".", "ambiguous_projector", "Use at most one mmproj GGUF file per directory.")
    elif projectors:
        info.mmproj_ref = f"{info.model_ref}/{projectors[0]}"


def inspect_directory(root: Path, kind: str, model_ref: str) -> DirectoryInformation:
    path = directory_path(root, model_ref)
    info = DirectoryInformation(kind=kind, model_ref=model_ref)
    if not path.is_dir():
        info.diagnostic(".", "missing_directory", "The model directory does not exist.")
        return info
    {"llm": _llm, "tts": _tts, "vision": _vision}[kind](path, info)
    return info
