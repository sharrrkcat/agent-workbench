"""Private token-protected loopback RPC for the bundled DLSS NR component."""
import ctypes
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).parent))


def reject_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise RuntimeError("DLSS NR worker networking is disabled")


sys.addaudithook(reject_network)
from engine import Engine, WorkerError, fields, load_bridge

MAX_BYTES = 64 * 1024 * 1024


def self_check(bridge, caller):
    load_bridge(bridge)
    helper = ctypes.CDLL(caller)
    for name in ("Init", "Create", "Evaluate", "Release", "Shutdown"):
        getattr(helper, "DLSSNR_Call" + name)
    print("DLSS NR component imports and native entry points verified offline.", flush=True)


def main():
    token = os.environ["COGITA_WORKER_TOKEN"]
    engine = Engine(os.environ["COGITA_MODELS_ROOT"], os.environ["COGITA_DLSS_BRIDGE"],
                    os.environ["COGITA_DLSS_CALLER"], os.environ["COGITA_DLSS_WORK"])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, value, status=200):
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            if len(data) > MAX_BYTES:
                data, status = b'{"error":{"code":"REQUEST_TOO_LARGE"}}', 413
            self.send_response(status)
            self.send_header("Content-Type", "image/png" if isinstance(value, bytes) and status == 200 else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            if not secrets.compare_digest(self.headers.get("X-Worker-Token", ""), token):
                self.respond({"error": {"code": "UNAUTHORIZED"}}, 401)
                return False
            return True

        def do_GET(self):
            if self.authorized():
                self.respond({"protocol_version": 1} if self.path == "/health" else {"error": {"code": "NOT_FOUND"}},
                             200 if self.path == "/health" else 404)

        def do_POST(self):
            if not self.authorized():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BYTES:
                    raise WorkerError("REQUEST_TOO_LARGE", 413)
                value = json.loads(self.rfile.read(length))
                if self.path == "/load":
                    result = engine.load(value)
                elif self.path == "/process":
                    result = engine.process(value)
                else:
                    raise WorkerError("INVALID_REQUEST", 404)
                self.respond(result)
            except WorkerError as exc:
                self.respond({"error": {"code": exc.code}}, exc.status)
            except (ValueError, TypeError, KeyError, OSError) as exc:
                print("DLSS NR request failed: " + type(exc).__name__, flush=True)
                self.respond({"error": {"code": "INVALID_REQUEST"}}, 422)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    ready = Path(os.environ["COGITA_WORKER_READY"])
    pending = ready.with_suffix(".tmp")
    pending.write_text(json.dumps({"protocol_version": 1, "port": server.server_port}), encoding="utf-8")
    pending.replace(ready)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--self-check":
        self_check(sys.argv[2], sys.argv[3])
    else:
        main()
