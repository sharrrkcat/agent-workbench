"""Token-authenticated, single-engine private Audio worker."""
import gc
import json
import math
import os
from pathlib import Path
import sys
import threading
from http.server import ThreadingHTTPServer

if __package__:
    from .common import WorkerError, fields, integer
    from .audio_catalog import CHATTERBOX_DEFAULTS, reference_path, audio_model
    from .server import handler
else:
    sys.path.insert(0, str(Path(__file__).parent))
    from common import WorkerError, fields, integer
    from audio_catalog import CHATTERBOX_DEFAULTS, reference_path, audio_model
    from server import handler


def options_request(value):
    fields(value, ("device", "intraop_threads"))
    if value["device"] not in {"cpu", "cuda"}:
        raise WorkerError("INVALID_REQUEST")
    integer(value["intraop_threads"], 1, 256)
    return value


def generation_options(value):
    fields(value, (), CHATTERBOX_DEFAULTS)
    bounds = {"exaggeration": (0, 2), "cfg_weight": (0, 1), "temperature": (0, 5),
              "repetition_penalty": (1, 2), "min_p": (0, 1), "top_p": (0, 1)}
    for key, number in value.items():
        low, high = bounds[key]
        if type(number) not in {int, float} or not math.isfinite(number) or not low <= number <= high or key in {"temperature", "top_p"} and number == 0:
            raise WorkerError("INVALID_REQUEST")
    return value


class AudioWorker:
    def __init__(self, root, references, engine_factory=None, validation=False):
        self.root, self.references = root, references
        self.engine_factory, self.validation = engine_factory, validation
        self.engine = None
        self.profile_id = None
        self.architecture = None
        self.lock = threading.Lock()

    def health(self):
        return {"protocol_version": 1, "loaded": [self.profile_id] if self.engine else [],
                "device_name": getattr(self.engine, "device_name", None),
                "device": getattr(self.engine, "device", None),
                "dtype": str(self.engine.dtype) if self.engine and hasattr(self.engine, "dtype") else None}

    def dispatch(self, operation, body):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("MODEL_BUSY", 409)
        try:
            if operation == "/reference":
                fields(body, ("reference",))
                if __package__:
                    from .audio_engine import decode_audio
                else:
                    from audio_engine import decode_audio
                audio, rate = decode_audio(reference_path(self.references, body["reference"]))
                return {"frames": len(audio), "sample_rate": rate}
            if operation == "/load":
                fields(body, ("profile_id", "kind", "model_ref", "parameters", "options"))
                if not isinstance(body["profile_id"], str) or not 1 <= len(body["profile_id"]) <= 128:
                    raise WorkerError("INVALID_REQUEST")
                parameters = body["parameters"]
                fields(parameters, ("architecture",), ("speed", "response_format", *CHATTERBOX_DEFAULTS))
                architecture = parameters["architecture"]
                allowed = {"chatterbox", "qwen3tts", "whisper"} if self.validation else {"chatterbox"}
                if architecture not in allowed or body["kind"] != ("asr" if architecture == "whisper" else "tts"):
                    raise WorkerError("UNSUPPORTED_CAPABILITY")
                options = options_request(body["options"])
                generation_options({key: value for key, value in parameters.items() if key in CHATTERBOX_DEFAULTS})
                path = audio_model(self.root, body["model_ref"], architecture)
                if self.engine and self.profile_id != body["profile_id"]:
                    raise WorkerError("MODEL_BUSY", 409)
                if not self.engine:
                    factory = self.engine_factory
                    if factory is None:
                        if __package__:
                            from .audio_engine import ChatterboxEngine, QwenTTSEngine, WhisperEngine
                        else:
                            from audio_engine import ChatterboxEngine, QwenTTSEngine, WhisperEngine
                        factory = {"chatterbox": ChatterboxEngine, "qwen3tts": QwenTTSEngine, "whisper": WhisperEngine}[architecture]
                    self.engine = factory(path, options)
                    self.profile_id, self.architecture = body["profile_id"], architecture
                return self.health()
            if operation == "/unload":
                fields(body, ("profile_id",))
                if body["profile_id"] != self.profile_id:
                    raise WorkerError("MODEL_NOT_FOUND", 404)
                self.engine, self.profile_id, self.architecture = None, None, None
                gc.collect()
                return self.health()
            if operation == "/speech":
                fields(body, ("profile_id", "input", "reference", "speed", "response_format", "language", "model_options"))
                if not isinstance(body["input"], str) or not body["input"].strip() or len(body["input"]) > 4096:
                    raise WorkerError("INVALID_REQUEST")
                speed = body["speed"]
                if type(speed) not in {int, float} or not math.isfinite(speed) or not 0.25 <= speed <= 4:
                    raise WorkerError("INVALID_REQUEST")
                if body["response_format"] not in {"mp3", "wav"} or body["language"] not in {None, "en-US"}:
                    raise WorkerError("INVALID_REQUEST")
                values = generation_options(body["model_options"])
                self.require_model(body["profile_id"], {"chatterbox", "qwen3tts"})
                return self.engine.speech(body["input"], reference_path(self.references, body["reference"]),
                    speed, body["response_format"], values)
            if operation == "/transcribe" and self.validation:
                fields(body, ("profile_id", "reference"))
                self.require_model(body["profile_id"], {"whisper"})
                return self.engine.transcribe(reference_path(self.references, body["reference"]))
            raise WorkerError("UNSUPPORTED_CAPABILITY", 404)
        finally:
            self.lock.release()

    def require_model(self, profile_id, architectures):
        if not self.engine or self.profile_id != profile_id:
            raise WorkerError("MODEL_UNAVAILABLE", 503)
        if self.architecture not in architectures:
            raise WorkerError("MODEL_KIND_MISMATCH")


def main():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
    token = os.environ["WORKBENCH_WORKER_TOKEN"]
    if len(token) < 32:
        raise RuntimeError("Worker token is invalid")
    worker = AudioWorker(Path(os.environ["WORKBENCH_MODELS_ROOT"]).resolve(),
        Path(os.environ["WORKBENCH_AUDIO_REFERENCES_ROOT"]).resolve(), validation=os.environ.get("WORKBENCH_AUDIO_VALIDATION") == "1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(worker, token))
    server.daemon_threads = True
    Path(os.environ["WORKBENCH_WORKER_READY"]).write_text(json.dumps({"port": server.server_port, "protocol_version": 1}), encoding="utf-8")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
