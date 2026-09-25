import json

from ai_workbench.core.models.schema import ModelProfile

REF = "asr/native-model"
OPTIONS = {"device": "cuda", "intraop_threads": 4}
PARAMETERS = {"language": "auto", "prompt": "", "temperature": 0.0, "response_format": "json"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def model_tree(root, *, ref=REF, multilingual=True, features=80):
    path = root / "data/models" / ref
    write_json(path / "config.json", {"model_type": "whisper", "architectures": ["WhisperForConditionalGeneration"],
        "num_mel_bins": features, "max_source_positions": 1500})
    write_json(path / "preprocessor_config.json", {"processor_class": "WhisperProcessor",
        "feature_extractor_type": "WhisperFeatureExtractor", "sampling_rate": 16000,
        "feature_size": features, "chunk_length": 30})
    write_json(path / "generation_config.json", {"is_multilingual": multilingual,
        "lang_to_id": {"<|en|>": 10, "<|zh|>": 11}, "task_to_id": {"transcribe": 20}, "no_timestamps_token_id": 30})
    write_json(path / "tokenizer_config.json", {"tokenizer_class": "WhisperTokenizer"})
    write_json(path / "tokenizer.json", {})
    (path / "model.safetensors").write_bytes(b"synthetic model")
    return path


def profile(**values):
    return ModelProfile(**{"name": "ASR", "alias": "asr", "kind": "asr", "model_ref": REF,
        "source": {"type": "local"}, "external_enabled": True, **values})
