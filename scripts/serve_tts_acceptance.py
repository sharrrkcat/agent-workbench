"""Serve isolated Cogita for Voxia acceptance; use a mock supplier by default.

--saved-profile reads one enabled TTS profile and its supplier in read-only mode.
It makes billable requests only when the caller explicitly submits speech.
Production profiles, API settings, and credentials are never modified.
"""
import argparse
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import logging
import math
from pathlib import Path
import sqlite3
import struct
import threading
import wave

import httpx
import uvicorn

from ai_workbench.api.main import create_app
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.db.database import get_database_url


def mock_audio(text):
    if text == "wav-corrupt":
        return b"RIFF\x00\x00\x00\x00WAVEbroken"
    if text == "wav-oversize":
        return b"RIFF\xff\xff\xff\xffWAVE" + bytes(32 * 1024 * 1024)
    rate = 44100 if text == "wav-44100" else 48000
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(b"".join(struct.pack("<hh", value, value) for index in range(rate // 4)
            for value in [round(6000 * math.sin(2 * math.pi * 440 * index / rate))]))
    data = bytearray(output.getvalue())
    if text == "wav-placeholder":
        data[4:8] = data[40:44] = b"\xff\xff\xff\xff"
    return bytes(data)


def saved_supplier(profile_id):
    url = get_database_url()
    if not url.startswith("sqlite:///"):
        raise ValueError("Acceptance requires the saved local SQLite database")
    database = Path(url.removeprefix("sqlite:///")).resolve()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        profile = db.execute("SELECT model_ref,provider_profile_id,parameters_json FROM model_profiles "
            "WHERE id=? AND kind='tts' AND source_type='provider' AND enabled=1", (profile_id,)).fetchone()
        if profile is None:
            raise ValueError("Select an enabled provider TTS profile")
        supplier = db.execute("SELECT name,enabled,connection_json FROM provider_profiles WHERE id=?", (profile[1],)).fetchone()
    if supplier is None or not supplier[1]:
        raise ValueError("The selected supplier must be enabled")
    return database, profile, supplier


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--saved-profile")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING)
    records = []
    mock = None
    saved = saved_supplier(args.saved_profile) if args.saved_profile else None
    if saved:
        _, profile, supplier = saved
        connection = json.loads(supplier[2])
        model_ref = profile[0]
    else:
        class MockSupplier(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path != "/v1/audio/speech" or set(payload) != {"model", "input", "voice", "speed", "response_format", "language"}:
                    self.send_error(400)
                    return
                data = mock_audio(payload["input"])
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Expected when the bounded client rejects oversized audio.

        mock = ThreadingHTTPServer(("127.0.0.1", 0), MockSupplier)
        threading.Thread(target=mock.serve_forever, daemon=True).start()
        connection = {"base_url": f"http://127.0.0.1:{mock.server_port}/v1", "api_key": "mock-supplier-key"}
        model_ref = "mock-speech"

    def record():
        unchanged = True
        if saved:
            database, profile, supplier = saved
            with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
                unchanged = db.execute("SELECT name,enabled,connection_json FROM provider_profiles WHERE id=?", (profile[1],)).fetchone() == supplier
        (args.output / "requests.json").write_text(json.dumps({"mode": "live" if saved else "mock",
            "supplier_unchanged": unchanged, "requests": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    class RecordingAdapter(OpenAIAdapter):
        async def speech(self, profile, text, voice, speed, response_format, language):
            item = {"model": profile.model_ref, "text": text, "voice": voice,
                    "speed": speed, "format": response_format, "language": language, "success": False}
            records.append(item)
            try:
                result = await super().speech(profile, text, voice, speed, response_format, language)
                item.update(success=True, bytes=len(result.data))
                return result
            finally:
                record()

    app = create_app(root=args.output / "cogita", use_memory=True, adapter_factory=RecordingAdapter)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def acceptance_lifespan(app):
        async with original_lifespan(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 40001)), base_url="http://localhost") as client:
                response = await client.post("/api/models/providers", json={"name": "Isolated acceptance supplier", "connection": connection})
                response.raise_for_status()
                supplier_id = response.json()["id"]
                for alias, architecture in [("accept-catalog", "grok-voice-latest"), ("accept-custom", "customize")]:
                    response = await client.post("/api/models/profiles", json={"name": "Grok catalog" if alias == "accept-catalog" else "Custom voice ID",
                        "alias": alias, "kind": "tts", "source": {"type": "provider", "provider_profile_id": supplier_id},
                        "model_ref": model_ref, "parameters": {"architecture": architecture, "voice": "alloy"}, "external_enabled": True})
                    response.raise_for_status()
                response = await client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "isolated-voxia-acceptance-key"})
                response.raise_for_status()
            record()
            (args.output / "ready.json").write_text(json.dumps({"base_url": f"http://127.0.0.1:{args.port}", "mode": "live" if saved else "mock"}) + "\n", encoding="utf-8")
            yield
            record()

    app.router.lifespan_context = acceptance_lifespan
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    finally:
        if mock:
            mock.shutdown()
        record()


if __name__ == "__main__":
    main()
