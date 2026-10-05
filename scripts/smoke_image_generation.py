"""Make two explicit, billable image requests using a read-only saved provider.

The application runs with isolated in-memory profiles/settings. Only a sanitized
report is saved; image bytes are decoded in memory and never added to attachments.
"""
import argparse
import base64
from io import BytesIO
import json
import logging
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from ai_workbench.api.main import create_app
from ai_workbench.db.database import get_database_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--model-ref", required=True)
    parser.add_argument("--report", type=Path, default=Path("build/image-generation-smoke/report.json"))
    args = parser.parse_args()
    url = get_database_url()
    if not url.startswith("sqlite:///"):
        parser.error("The saved provider must use the local SQLite database.")
    database = Path(url.removeprefix("sqlite:///")).resolve()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        before = db.execute("SELECT name,enabled,connection_json FROM provider_profiles WHERE id=?", (args.provider_id,)).fetchone()
    if before is None or not before[1]:
        parser.error("Select an existing enabled provider.")
    logging.basicConfig(level=logging.WARNING)
    results = []
    with TemporaryDirectory(prefix="cogita-image-smoke-") as directory:
        with TestClient(create_app(root=Path(directory), use_memory=True), client=("127.0.0.1", 40001)) as client:
            provider = client.post("/api/models/providers", json={"name": before[0], "connection": json.loads(before[2])})
            provider.raise_for_status()
            profile = client.post("/api/models/profiles", json={"name": "Image acceptance", "alias": "image-smoke",
                "kind": "image_generation", "source": {"type": "provider", "provider_profile_id": provider.json()["id"]},
                "model_ref": args.model_ref, "external_enabled": True})
            profile.raise_for_status()
            client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "isolated-smoke-key"}).raise_for_status()
            for fmt in ("url", "b64_json"):
                print(f"Generating one image with response_format={fmt}...", flush=True)
                started = time.monotonic()
                response = client.post("/v1/images/generations", headers={"Authorization": "Bearer isolated-smoke-key"},
                    json={"model": "image-smoke", "prompt": "A simple blue ceramic cup on a white background, studio product photo, no text.",
                          "n": 1, "response_format": fmt})
                result = {"response_format": fmt, "http_status": response.status_code,
                    "elapsed_seconds": round(time.monotonic() - started, 2), "request_id": response.headers.get("X-Request-Id"), "success": False}
                if response.is_success:
                    try:
                        item = response.json()["data"][0]
                        if fmt == "url":
                            data = bytearray()
                            # CDN requests deliberately carry no provider credentials.
                            with httpx.stream("GET", item["url"], timeout=60, trust_env=False, follow_redirects=True) as download:
                                download.raise_for_status()
                                for chunk in download.iter_bytes():
                                    if len(data) + len(chunk) > 64 * 1024 * 1024:
                                        raise ValueError("Image exceeds smoke download limit")
                                    data.extend(chunk)
                        else:
                            data = base64.b64decode(item["b64_json"], validate=True)
                        with Image.open(BytesIO(data)) as image:
                            image.load()
                            result.update(success=True, bytes=len(data), width=image.width, height=image.height, image_format=image.format)
                    except (httpx.HTTPError, ValueError, OSError) as exc:
                        result["error"] = type(exc).__name__
                else:
                    result["error"] = response.json().get("error", {}).get("code", "UNKNOWN")
                results.append(result)
                print(json.dumps(result), flush=True)
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        unchanged = db.execute("SELECT name,enabled,connection_json FROM provider_profiles WHERE id=?", (args.provider_id,)).fetchone() == before
    report = {"model_ref": args.model_ref, "provider_unchanged": unchanged, "results": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if unchanged and all(item["success"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
