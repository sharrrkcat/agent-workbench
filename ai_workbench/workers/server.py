"""Private worker HTTP endpoint; its control server needs only the stdlib."""
from __future__ import annotations

import gc
from functools import partial
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading

if __package__:
    from .common import publish_ready
    from .protocol import WorkerError, fields, load_request, speech_request
    from .timing import TRACE_ENV, TRACE_HEADER, current_trace, stage, tracing, worker_trace
else:
    sys.path.insert(0, str(Path(__file__).parent))
    from common import publish_ready
    from protocol import WorkerError, fields, load_request, speech_request
    from timing import TRACE_ENV, TRACE_HEADER, current_trace, stage, tracing, worker_trace

PROTOCOL_VERSION = 1
MAX_BODY = 32 * 1024 * 1024


class Worker:
    def __init__(self, root, engine_factory=None):
        self.root = root
        self.models = {}
        self.lock = threading.Lock()
        self.engine_factory = engine_factory

    def health(self):
        return {"protocol_version": PROTOCOL_VERSION, "loaded": list(self.models)}

    def dispatch(self, operation, body):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("MODEL_BUSY", 409)
        try:
            if operation == "/load":
                with stage("model_resources"):
                    path = load_request(body, self.root)
                model_id = body["profile_id"]
                trace = current_trace()
                if trace:
                    trace.reused["model_reused"] = model_id in self.models
                if model_id not in self.models:
                    factory = self.engine_factory
                    if factory is None:
                        if __package__:
                            from .tts_engine import TTSEngine
                        else:
                            from tts_engine import TTSEngine
                        factory = partial(TTSEngine, models_root=self.root)
                    with stage("engine_init"):
                        self.models[model_id] = factory(path, body["kind"], body["parameters"], body["options"])
                with stage("worker_ready"):
                    return self.health()
            if operation == "/unload":
                fields(body, ("profile_id",))
                if not isinstance(body["profile_id"], str) or not body["profile_id"] or len(body["profile_id"]) > 128:
                    raise WorkerError("INVALID_REQUEST")
                self.models.pop(body["profile_id"], None)
                gc.collect()
                return self.health()
            if operation != "/speech":
                raise WorkerError("UNSUPPORTED_CAPABILITY", 404)
            fields(body, ("profile_id", "input", "voice", "speed", "response_format", "language"))
            values = {key: value for key, value in body.items() if key != "profile_id"}
            speech_request(values)
            model = self.models.get(body["profile_id"])
            if model is None:
                raise WorkerError("MODEL_UNAVAILABLE", 503)
            return model.speech(values["input"], values["voice"], values["speed"], values["response_format"], values["language"])
        finally:
            self.lock.release()


def handler(worker, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, data):
            binary = isinstance(data, tuple)
            payload = data[0] if binary else json.dumps(data, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", data[1] if binary else "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            self.close_connection = True

        def _authorized(self):
            if not hmac.compare_digest(self.headers.get("X-Worker-Token", "").encode(), token.encode()):
                self._send(401, {"error": {"code": "AUTH_INVALID"}})
                return False
            return True

        def do_GET(self):
            if self._authorized():
                self._send(200, worker.health()) if self.path == "/health" else self._send(404, {"error": {"code": "INVALID_REQUEST"}})

        def do_POST(self):
            if not self._authorized():
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise WorkerError("INVALID_REQUEST")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY:
                    raise WorkerError("REQUEST_TOO_LARGE", 413)
                self.connection.settimeout(30)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise WorkerError("INVALID_REQUEST")
                data = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                trace = worker_trace(self.headers.get(TRACE_HEADER), "worker_load" if self.path == "/load" else "reference_validate") if self.path in {"/load", "/reference"} else None
                with tracing(trace):
                    result = worker.dispatch(self.path, data)
                self._send(200, result)
            except WorkerError as exc:
                self._send(exc.status, {"error": {"code": exc.code}})
            except (ValueError, TypeError, KeyError):
                self._send(422, {"error": {"code": "INVALID_REQUEST"}})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                print(f"Worker operation failed: {type(exc).__name__}", flush=True)
                self._send(503, {"error": {"code": "MODEL_UNAVAILABLE"}})
    return Handler


def main():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    with tracing(worker_trace(os.environ.get(TRACE_ENV), "worker_startup")):
        with stage("worker_setup"):
            token = os.environ["WORKBENCH_WORKER_TOKEN"]
            if len(token) < 32:
                raise RuntimeError("Worker token is invalid")
            worker = Worker(Path(os.environ["WORKBENCH_MODELS_ROOT"]).resolve())
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler(worker, token))
            server.daemon_threads = True
        with stage("ready_file"):
            publish_ready(Path(os.environ["WORKBENCH_WORKER_READY"]), {"port": server.server_port, "protocol_version": PROTOCOL_VERSION})
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
