"""Standard-library validation for the private, local worker protocol."""
import math

if __package__:
    from .common import WorkerError, fields, strings, integer, local_model
    from .tts_catalog import FORMATS, LANGUAGES, MAX_INPUT_CHARS, VOICE_IDS
    from .model_catalog import inspect_directory
else:
    from common import WorkerError, fields, strings, integer, local_model
    from tts_catalog import FORMATS, LANGUAGES, MAX_INPUT_CHARS, VOICE_IDS
    from model_catalog import inspect_directory


def load_request(body, root):
    fields(body, ("profile_id", "kind", "model_ref", "parameters", "options"))
    if not isinstance(body["profile_id"], str) or not body["profile_id"] or len(body["profile_id"]) > 128:
        raise WorkerError("INVALID_REQUEST")
    if body["kind"] not in {"tts", "vision"}:
        raise WorkerError("MODEL_KIND_MISMATCH")
    params, options = body["parameters"], body["options"]
    fields(options, ("device", "intraop_threads", "max_batch_size"))
    if options["device"] != "cpu":
        raise WorkerError("RUNTIME_UNSUPPORTED")
    integer(options["intraop_threads"], 1, 256)
    integer(options["max_batch_size"], 1, 1)
    if body["kind"] == "vision":
        fields(params, ("task", "thresholds"))
        if params["task"] != "tags":
            raise WorkerError("UNSUPPORTED_CAPABILITY")
        tag_thresholds(params["thresholds"])
    else:
        fields(params, ("speed", "response_format"))
        speech_request({"input": "validation", "voice": "af_heart", "speed": params["speed"],
                        "response_format": params["response_format"], "language": None})
    info = inspect_directory(root, body["kind"], body["model_ref"]).require_complete()
    if info.engine != ("wd14" if body["kind"] == "vision" else "kokoro"):
        raise WorkerError("UNSUPPORTED_CAPABILITY")
    return local_model(root, body["model_ref"], tts=body["kind"] == "tts", wd14=body["kind"] == "vision")


def tag_thresholds(value):
    fields(value, ("general", "character"))
    if any(type(score) not in {int, float} or not math.isfinite(score) or not 0 <= score <= 1
           for score in value.values()):
        raise WorkerError("INVALID_REQUEST")


def tags_request(body):
    fields(body, ("profile_id", "images", "thresholds"))
    if not isinstance(body["profile_id"], str) or not body["profile_id"] or len(body["profile_id"]) > 128:
        raise WorkerError("INVALID_REQUEST")
    strings(body["images"], limit=16)
    if any(not image.startswith("data:image/png;base64,") for image in body["images"]):
        raise WorkerError("INVALID_REQUEST")
    tag_thresholds(body["thresholds"])


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
