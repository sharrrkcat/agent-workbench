"""Run the real UI/API against isolated state and a deterministic model fixture.

Use from the repository root: uv run python -m tests.browser_smoke_server
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi.testclient import TestClient

from ai_workbench.api.main import create_app
from tests.model_fixtures import MockOpenAI, configure_model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="workbench-browser-") as directory:
        root = Path(directory)
        os.environ["AGENT_WORKBENCH_ATTACHMENTS_DIR"] = str(root / "data/attachments")
        note = root / "data/knowledge/note.txt"
        note.parent.mkdir(parents=True)
        note.write_text("Browser approval result", encoding="utf-8")
        upstream = MockOpenAI("Browser chat reply")
        app = create_app(root=root, use_memory=True, adapter_factory=upstream.factory,
                         frontend_dist=repository / "frontend/dist")
        client = TestClient(app)
        configure_model(client, alias="chat-model", capabilities={"streaming": True, "tools": True})
        configure_model(client, kind="embedding", alias="embedding-model", parameters={"dimensions": 2})
        client.patch("/api/models/settings", json={"external_api_key": "browser-test-key", "external_enabled": True}).raise_for_status()
        client.patch("/api/settings/general", json={"auto_generate_session_titles": False}).raise_for_status()
        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
