"""Private ASR service: one offline model, queue and cancellation scope per process."""
import os
from pathlib import Path
import sys
import threading
from http.server import ThreadingHTTPServer

if __package__:
    from .asr_catalog import input_path, load_configuration, transcription_options
    from .common import WorkerError, fields, integer, publish_ready
    from .server import handler
    from .timing import TRACE_ENV, stage, tracing, worker_trace
else:
    sys.path.insert(0, str(Path(__file__).parent))
    from asr_catalog import input_path, load_configuration, transcription_options
    from common import WorkerError, fields, integer, publish_ready
    from server import handler
    from timing import TRACE_ENV, stage, tracing, worker_trace


class ASRWorker:
    def __init__(self, root, inputs, engine_factory=None):
        self.root, self.inputs, self.engine_factory = root, inputs, engine_factory
        self.engine, self.profile_id = None, None
        self.lock = threading.Lock()

    def health(self):
        return {"protocol_version": 1, "loaded": [self.profile_id] if self.engine else [],
            "device_name": self.engine.device_name if self.engine else None,
            "device": self.engine.device if self.engine else None,
            "dtype": str(self.engine.dtype) if self.engine else None}

    def dispatch(self, operation, body):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("MODEL_BUSY", 409)
        try:
            if operation == "/load":
                fields(body, ("profile_id", "kind", "model_ref", "parameters", "options"))
                if (body["kind"] != "asr" or not isinstance(body["profile_id"], str)
                        or not 1 <= len(body["profile_id"]) <= 128):
                    raise WorkerError("INVALID_REQUEST")
                transcription_options(body["parameters"])
                options = body["options"]
                fields(options, ("device", "intraop_threads"))
                if options["device"] not in ("cpu", "cuda"):
                    raise WorkerError("INVALID_REQUEST")
                integer(options["intraop_threads"], 1, 256)
                with stage("model_resources"):
                    path, information = load_configuration(self.root, body["model_ref"])
                if self.engine and self.profile_id != body["profile_id"]:
                    raise WorkerError("MODEL_BUSY", 409)
                if self.engine is None:
                    factory = self.engine_factory
                    if factory is None:
                        if __package__:
                            from .asr_engine import ASREngine
                        else:
                            from asr_engine import ASREngine
                        factory = ASREngine
                    with stage("engine_init"):
                        self.engine = factory(path, options, information)
                    self.profile_id = body["profile_id"]
                return self.health()
            if operation == "/unload":
                fields(body, ("profile_id",))
                self.require_model(body["profile_id"])
                self.engine, self.profile_id = None, None
                return self.health()
            if operation == "/transcribe":
                fields(body, ("profile_id", "input", "options"))
                options = transcription_options(body["options"])
                self.require_model(body["profile_id"])
                return self.engine.transcribe(input_path(self.inputs, body["input"]), options)
            raise WorkerError("UNSUPPORTED_CAPABILITY", 404)
        finally:
            self.lock.release()

    def require_model(self, profile_id):
        if self.engine is None or profile_id != self.profile_id:
            raise WorkerError("MODEL_UNAVAILABLE", 503)


def main():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
    with tracing(worker_trace(os.environ.get(TRACE_ENV), "worker_startup")):
        token = os.environ["COGITA_WORKER_TOKEN"]
        if len(token) < 32:
            raise RuntimeError("Worker token is invalid")
        worker = ASRWorker(Path(os.environ["COGITA_MODELS_ROOT"]).resolve(),
            Path(os.environ["COGITA_ASR_INPUTS_ROOT"]).resolve())
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(worker, token))
        server.daemon_threads = True
        publish_ready(Path(os.environ["COGITA_WORKER_READY"]), {"port": server.server_port, "protocol_version": 1})
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
