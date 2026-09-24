"""Private HTTP service for one fixed SigLIP target tower."""
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
import traceback

if __package__:
    from .common import WorkerError, fields, integer, publish_ready, strings
    from .server import PROTOCOL_VERSION, handler
    from .siglip_catalog import model_directory, model_files
else:
    sys.path.insert(0, str(Path(__file__).parent))
    from common import WorkerError, fields, integer, publish_ready, strings
    from server import PROTOCOL_VERSION, handler
    from siglip_catalog import model_directory, model_files


class SiglipWorker:
    def __init__(self, root, model_ref, tower, options, revision, engine_factory=None):
        fields(options, ("device", "intraop_threads", "max_batch_size"))
        if options["device"] not in {"cpu", "cuda"} or tower not in {"image", "text"}:
            raise WorkerError("INVALID_REQUEST")
        integer(options["intraop_threads"], 1, 256)
        integer(options["max_batch_size"], 1, 16)
        if not isinstance(revision, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", revision):
            raise WorkerError("INVALID_REQUEST")
        path = model_directory(root, model_ref)
        model_files(path)
        self.tower, self.lock = tower, threading.Lock()
        if engine_factory is None:
            if __package__:
                from .siglip_engine import SiglipEngine
            else:
                from siglip_engine import SiglipEngine
            engine_factory = SiglipEngine
        self.engine = engine_factory(path, tower, options, revision)

    def health(self):
        return {"protocol_version": PROTOCOL_VERSION, **self.engine.info}

    def dispatch(self, operation, body):
        if operation != "/embed":
            raise WorkerError("UNSUPPORTED_CAPABILITY", 404)
        fields(body, ("inputs",))
        inputs = strings(body["inputs"], limit=16)
        if self.tower == "image" and any(not value.startswith("data:image/png;base64,") for value in inputs):
            raise WorkerError("INVALID_REQUEST")
        if not self.lock.acquire(blocking=False):
            raise WorkerError("MODEL_BUSY", 409)
        try:
            return self.engine.embed(inputs)
        finally:
            self.lock.release()


def main():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    ready = Path(os.environ["WORKBENCH_WORKER_READY"])
    try:
        token = os.environ["WORKBENCH_WORKER_TOKEN"]
        if len(token) < 32:
            raise WorkerError("INVALID_REQUEST")
        worker = SiglipWorker(Path(os.environ["WORKBENCH_MODELS_ROOT"]), os.environ["WORKBENCH_MODEL_REF"],
            os.environ["WORKBENCH_SIGLIP_TOWER"], json.loads(os.environ["WORKBENCH_RUNTIME_OPTIONS"]),
            os.environ["WORKBENCH_MODEL_REVISION"])
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(worker, token))
        server.daemon_threads = True
    except Exception as exc:
        traceback.print_exc()
        publish_ready(ready, {"error_code": exc.code if isinstance(exc, WorkerError) else "MODEL_UNAVAILABLE"})
        return
    publish_ready(ready, {"port": server.server_port, "protocol_version": PROTOCOL_VERSION})
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
