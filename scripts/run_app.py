from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Agent Workbench in production web mode.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host. Default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port. Default: {DEFAULT_PORT}")
    parser.add_argument("--frontend-dist", default=None, help="Path to built frontend dist. Default: frontend/dist")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload for local development.")
    open_group = parser.add_mutually_exclusive_group()
    open_group.add_argument("--open", dest="open_browser", action="store_true", help="Open the app in a browser after startup.")
    open_group.add_argument("--no-open", dest="open_browser", action="store_false", help="Do not open a browser.")
    parser.set_defaults(open_browser=False)
    return parser.parse_args()


def ensure_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise SystemExit(
                f"Port {port} on {host} is already in use. "
                f"Try: uv run python scripts/run_app.py --port {port + 1} --open"
            ) from exc


def open_later(url: str) -> None:
    def _open() -> None:
        time.sleep(1.0)
        webbrowser.open(url)

    thread = threading.Thread(target=_open, daemon=True)
    thread.start()


def main() -> None:
    args = parse_args()
    root = project_root()
    frontend_dist = Path(args.frontend_dist) if args.frontend_dist else root / "frontend" / "dist"
    frontend_dist = frontend_dist.expanduser().resolve()

    if not frontend_dist.is_dir():
        print(
            f"Frontend build not found at {frontend_dist}. "
            "The API will still start; run `cd frontend && npm run build` to enable the web UI.",
            file=sys.stderr,
        )

    ensure_port_available(args.host, args.port)

    os.environ["AGENT_WORKBENCH_FRONTEND_DIST"] = str(frontend_dist)
    os.environ["AGENT_WORKBENCH_PRODUCTION_WEB"] = "1"

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    url = f"http://{args.host}:{args.port}"
    if args.open_browser:
        open_later(url)

    uvicorn.run(
        "ai_workbench.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        factory=False,
    )


if __name__ == "__main__":
    main()
