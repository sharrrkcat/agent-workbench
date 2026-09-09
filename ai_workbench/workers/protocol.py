"""Standard-library validation for the private, local worker protocol."""
from pathlib import Path, PurePosixPath
import math

if __package__:
    from .tts_catalog import FORMATS, LANGUAGES, MAX_INPUT_CHARS, VOICE_IDS, model_files
else:
    from tts_catalog import FORMATS, LANGUAGES, MAX_INPUT_CHARS, VOICE_IDS, model_files


class WorkerError(Exception):
    def __init__(self, code, status=422):
        self.code, self.status = code, status


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise WorkerError("INVALID_REQUEST")


def strings(value, limit=2048):
    if not isinstance(value, list) or not 1 <= len(value) <= limit or any(not isinstance(x, str) or not x.strip() for x in value):
        raise WorkerError("INVALID_REQUEST")
    return value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise WorkerError("INVALID_REQUEST")
    return value


def local_model(root: Path, ref, *, wd14=False, tts=False):
    if not isinstance(ref, str) or not ref or "\\" in ref or ":" in ref or PurePosixPath(ref).is_absolute() or any(p in {"", ".", ".."} or p.rstrip(" .") != p for p in ref.split("/")):
        raise WorkerError("INVALID_REQUEST")
    path = (root / ref).resolve()
    if not path.is_relative_to(root.resolve()):
        raise WorkerError("INVALID_REQUEST")
    if not path.is_dir():
        raise WorkerError("MODEL_NOT_FOUND", 404)
    if tts:
        if not model_files(path):
            raise WorkerError("MODEL_NOT_FOUND", 404)
    elif wd14:
        if not all((path / name).is_file() for name in ("model.onnx", "selected_tags.csv")):
            raise WorkerError("MODEL_NOT_FOUND", 404)
    else:
        if not (path / "config.json").is_file():
            raise WorkerError("MODEL_NOT_FOUND", 404)
        if not any(item.is_file() and item.name.startswith(("model", "pytorch_model")) and
                   item.suffix in {".bin", ".safetensors"} for item in path.iterdir()):
            raise WorkerError("MODEL_NOT_FOUND", 404)
    # Tokenizers and weights may follow local links, so validate the full model tree.
    if any(not p.resolve().is_relative_to(root.resolve()) for p in path.rglob("*")):
        raise WorkerError("INVALID_REQUEST")
    return path


def load_request(body, root):
    fields(body, ("profile_id", "kind", "model_ref", "parameters", "options"))
    if not isinstance(body["profile_id"], str) or not body["profile_id"] or len(body["profile_id"]) > 128:
        raise WorkerError("INVALID_REQUEST")
    kind = body["kind"]
    allowed = {
        "embedding": {"dimensions", "normalize", "document_instruction", "query_instruction", "batch_size"},
        "reranker": {"batch_size"},
        "image_embedding": {"architecture", "dimensions", "normalize", "batch_size"},
        "vision": {"architecture", "task", "batch_size"},
        "tts": {"architecture", "speed", "response_format"},
    }
    if kind not in allowed:
        raise WorkerError("MODEL_KIND_MISMATCH")
    params, options = body["parameters"], body["options"]
    fields(params, (), allowed[kind])
    fields(options, ("device", "intraop_threads", "max_batch_size"))
    if options["device"] != "cpu":
        raise WorkerError("RUNTIME_UNSUPPORTED")
    integer(options["intraop_threads"], 1, 256)
    integer(options["max_batch_size"], 1, 2048)
    if "batch_size" in params:
        integer(params["batch_size"], 1, 2048)
    if params.get("dimensions") is not None:
        integer(params["dimensions"], 1, 65536)
    if "normalize" in params and type(params["normalize"]) is not bool:
        raise WorkerError("INVALID_REQUEST")
    if any(key in params and not isinstance(params[key], str) for key in ("document_instruction", "query_instruction")):
        raise WorkerError("INVALID_REQUEST")
    if kind == "image_embedding" and params.get("architecture") not in {"clip", "siglip2", "dinov2"}:
        raise WorkerError("UNSUPPORTED_CAPABILITY")
    if kind == "vision":
        if params.get("architecture") not in {"florence2", "wd14"}:
            raise WorkerError("UNSUPPORTED_CAPABILITY")
        if params.get("task", "caption") not in {"caption", "detailed_caption", "more_detailed_caption", "ocr", "tags"}:
            raise WorkerError("UNSUPPORTED_CAPABILITY")
    if kind == "tts":
        integer(options["max_batch_size"], 1, 1)
        if params.get("architecture") != "kokoro":
            raise WorkerError("UNSUPPORTED_CAPABILITY")
        speech_request({"input": "validation", "voice": "af_heart", "speed": params.get("speed"),
                        "response_format": params.get("response_format"), "language": None})
    return local_model(root, body["model_ref"], wd14=kind == "vision" and params["architecture"] == "wd14", tts=kind == "tts")


def speech_request(body):
    fields(body, ("input", "voice", "speed", "response_format", "language"))
    if not isinstance(body["input"], str) or not body["input"].strip() or len(body["input"]) > MAX_INPUT_CHARS:
        raise WorkerError("INVALID_REQUEST")
    if not isinstance(body["voice"], str) or body["voice"] not in VOICE_IDS:
        raise WorkerError("VOICE_UNAVAILABLE", 404)
    speed = body["speed"]
    if type(speed) not in {int, float} or not math.isfinite(speed) or not 0.25 <= speed <= 4:
        raise WorkerError("INVALID_REQUEST")
    if body["response_format"] not in FORMATS or body["language"] not in (None, LANGUAGES[body["voice"][0]]):
        raise WorkerError("INVALID_REQUEST")
