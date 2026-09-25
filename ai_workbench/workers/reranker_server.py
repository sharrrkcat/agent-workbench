"""Private token-authenticated CrossEncoder worker, one profile per process."""
import os
from pathlib import Path
import sys
import threading
from http.server import ThreadingHTTPServer

if __package__:
    from .common import WorkerError, fields, integer, publish_ready, strings
    from .reranker_catalog import load_configuration
    from .server import handler
    from .timing import TRACE_ENV, stage, tracing, worker_trace
else:
    sys.path.insert(0, str(Path(__file__).parent))
    from common import WorkerError, fields, integer, publish_ready, strings
    from reranker_catalog import load_configuration
    from server import handler
    from timing import TRACE_ENV, stage, tracing, worker_trace


class RerankerWorker:
    def __init__(self, root, engine_factory=None):
        self.root, self.engine_factory = root, engine_factory
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
                if (body["kind"] != "reranker" or not isinstance(body["profile_id"], str)
                        or not 1 <= len(body["profile_id"]) <= 128):
                    raise WorkerError("INVALID_REQUEST")
                fields(body["parameters"], ())
                options = body["options"]
                fields(options, ("device", "intraop_threads", "max_batch_size"))
                if options["device"] not in ("cpu", "cuda"):
                    raise WorkerError("INVALID_REQUEST")
                integer(options["intraop_threads"], 1, 256)
                integer(options["max_batch_size"], 1, 16)
                with stage("model_resources"):
                    path, information = load_configuration(self.root, body["model_ref"])
                if self.engine and self.profile_id != body["profile_id"]:
                    raise WorkerError("MODEL_BUSY", 409)
                if self.engine is None:
                    factory = self.engine_factory
                    if factory is None:
                        if __package__:
                            from .reranker_engine import RerankerEngine
                        else:
                            from reranker_engine import RerankerEngine
                        factory = RerankerEngine
                    self.engine = factory(path, options, information)
                    self.profile_id = body["profile_id"]
                return self.health()
            if operation == "/unload":
                fields(body, ("profile_id",))
                self.require_model(body["profile_id"])
                self.engine, self.profile_id = None, None
                return self.health()
            if operation == "/rerank":
                fields(body, ("profile_id", "query", "documents"))
                strings([body["query"]], limit=1)
                strings(body["documents"], limit=2048)
                self.require_model(body["profile_id"])
                return self.engine.rerank(body["query"], body["documents"])
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
        worker = RerankerWorker(Path(os.environ["COGITA_MODELS_ROOT"]).resolve())
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(worker, token))
        server.daemon_threads = True
        publish_ready(Path(os.environ["COGITA_WORKER_READY"]), {"port": server.server_port, "protocol_version": 1})
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
