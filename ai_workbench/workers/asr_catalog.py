"""Native Whisper directory information and private protocol, without model hashing."""
import json
import math
from pathlib import Path
import re

if __package__:
    from .common import WorkerError, fields, safe_reference
    from .embedding_catalog import package_file, package_path, validate_module_files
else:
    from common import WorkerError, fields, safe_reference
    from embedding_catalog import package_file, package_path, validate_module_files

ASR_DEFAULTS = {"language": "auto", "prompt": "", "temperature": 0.0, "response_format": "json"}
RESPONSE_FORMATS = ("json", "text", "verbose_json")


def transcription_options(value):
    fields(value, ASR_DEFAULTS)
    if (not isinstance(value["language"], str) or not re.fullmatch(r"auto|[a-z]{2,3}", value["language"])
            or not isinstance(value["prompt"], str) or value["response_format"] not in RESPONSE_FORMATS
            or type(value["temperature"]) not in (int, float) or not math.isfinite(value["temperature"])
            or not 0 <= value["temperature"] <= 1):
        raise WorkerError("INVALID_REQUEST")
    return value


def inspect_asr(root: Path, model_ref: str) -> dict:
    path = package_path(root, model_ref)
    diagnostics = []

    def problem(file, code, message):
        diagnostics.append({"file": file, "code": code, "message": message, "blocking": True})

    def read(name, *, required=True):
        try:
            value = json.loads(package_file(path, name).read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except FileNotFoundError:
            if required:
                problem(name, "missing_config", "Required native Whisper configuration is missing.")
        except (OSError, ValueError):
            problem(name, "invalid_config", "Configuration must contain a JSON object.")
        return {}

    def positive(config, key, file):
        value = config.get(key)
        if type(value) is int and value > 0:
            return value
        problem(file, "invalid_field", f"The declared {key} must be a positive integer.")
        return None

    config = read("config.json")
    processor = read("preprocessor_config.json")
    generation = read("generation_config.json")
    tokenizer = read("tokenizer_config.json", required=False)
    architecture = "whisper" if config.get("model_type") == "whisper" else None
    if architecture is None:
        problem("config.json", "unsupported_configuration", "Only native Whisper speech-to-text models are supported.")
    if config.get("architectures") not in (None, ["WhisperForConditionalGeneration"]):
        problem("config.json", "unsupported_configuration", "A native Whisper transcription model is required.")
    if any(value.get("auto_map") for value in (config, processor, tokenizer)):
        problem("config.json", "remote_code", "Custom model or processor code is unsupported.")
    sample_rate = positive(processor, "sampling_rate", "preprocessor_config.json")
    features = positive(processor, "feature_size", "preprocessor_config.json")
    mel_bins = positive(config, "num_mel_bins", "config.json")
    if features is not None and mel_bins is not None and features != mel_bins:
        problem("preprocessor_config.json", "unsupported_configuration", "Processor features do not match the model's mel bins.")
    window = processor.get("chunk_length")
    if type(window) is not int or window <= 0:
        window = None
    processor_name = processor.get("processor_class", tokenizer.get("processor_class"))
    if not isinstance(processor_name, str):
        processor_name = None
    if (processor_name not in (None, "WhisperProcessor")
            or processor.get("feature_extractor_type") not in (None, "WhisperFeatureExtractor")
            or tokenizer.get("tokenizer_class") not in (None, "WhisperTokenizer", "WhisperTokenizerFast")):
        problem("preprocessor_config.json", "unsupported_configuration", "Native Whisper preprocessing and tokenization are required.")
    multilingual = generation.get("is_multilingual")
    languages = []
    if type(multilingual) is not bool:
        multilingual = None
        problem("generation_config.json", "invalid_field", "The native multilingual setting is missing or invalid.")
    elif not multilingual:
        languages = ["en"]
    else:
        mapping = generation.get("lang_to_id", {})
        if isinstance(mapping, dict):
            languages = sorted(match[1] for token, identifier in mapping.items()
                if (match := re.fullmatch(r"<\|([a-z]{2,3})\|>", token))
                and type(identifier) is int and identifier >= 0)
        if not languages:
            problem("generation_config.json", "invalid_field", "Native language tokens are missing.")
        tasks = generation.get("task_to_id", {})
        if not isinstance(tasks, dict) or type(tasks.get("transcribe")) is not int:
            problem("generation_config.json", "invalid_field", "The native transcription task token is missing.")
    timestamp_token = generation.get("no_timestamps_token_id")
    timestamps = type(timestamp_token) is int and timestamp_token >= 0
    if not timestamps:
        problem("generation_config.json", "invalid_field", "Native timestamp configuration is required for long-form transcription.")
    return {"kind": "asr", "model_ref": model_ref, "architecture": architecture, "processor": processor_name,
        "sample_rate": sample_rate, "feature_size": features, "window_seconds": window,
        "multilingual": multilingual, "languages": languages, "segment_timestamps": timestamps,
        "diagnostics": diagnostics}


def load_configuration(root: Path, model_ref: str) -> tuple[Path, dict]:
    information = inspect_asr(root, model_ref)
    if information["diagnostics"]:
        code = "MODEL_NOT_FOUND" if any(item["code"] == "missing_config" for item in information["diagnostics"]) else "UNSUPPORTED_CAPABILITY"
        raise WorkerError(code, 404 if code == "MODEL_NOT_FOUND" else 422)
    path = package_path(root, model_ref)
    validate_module_files(path, [{"path": "", "type": "Transformer"}])
    if not package_file(path, "tokenizer.json").is_file() and not all(
            package_file(path, name).is_file() for name in ("vocab.json", "merges.txt")):
        raise WorkerError("MODEL_NOT_FOUND", 404)
    return path, information


def input_path(root: Path, reference: str) -> Path:
    path = (root / safe_reference(reference)).resolve()
    if (not path.is_relative_to(root.resolve()) or not path.is_file()
            or path.suffix not in (".wav", ".mp3")):
        raise WorkerError("INVALID_AUDIO")
    return path
