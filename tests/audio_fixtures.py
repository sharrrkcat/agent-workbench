"""Small local model layouts for Audio boundary tests; no inference weights."""
import json


def qwen_model(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "speech_tokenizer").mkdir(exist_ok=True)
    configs = {
        "config.json": {"model_type": "qwen3_tts", "tts_model_type": "base", "tokenizer_type": "qwen3_tts_tokenizer_12hz"},
        "generation_config.json": {}, "tokenizer_config.json": {}, "preprocessor_config.json": {},
        "vocab.json": {"hello": 0}, "speech_tokenizer/preprocessor_config.json": {},
        "speech_tokenizer/config.json": {"model_type": "qwen3_tts_tokenizer_12hz"},
    }
    for name, value in configs.items():
        (path / name).write_text(json.dumps(value), encoding="utf-8")
    for name in ("merges.txt", "model.safetensors", "speech_tokenizer/model.safetensors"):
        (path / name).write_bytes(b"fixture")
    return path
