"""Exercise local WD14 CPU image tagging through the API using an existing installation."""
from __future__ import annotations

import argparse
import asyncio
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import subprocess
import time

import httpx
from PIL import Image, ImageDraw
import uvicorn

from ai_workbench.api.deps import build_runtime_state
from ai_workbench.api.main import create_app
from ai_workbench.api.schemas.inference import ImageTagsResponse
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.store import LocalRuntimeSettingsStore
from ai_workbench.db.database import get_engine, init_db


async def until(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "WD14 state did not settle before the deadline"
        await asyncio.sleep(0.02)


async def checked_json(client, method, path, **kwargs):
    response = await client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()


def fixture_images():
    picture = Image.new("RGB", (192, 128), "white")
    drawing = ImageDraw.Draw(picture)
    drawing.rectangle((24, 12, 112, 108), fill="red")
    drawing.ellipse((104, 40, 170, 112), fill="blue")
    images = []
    for format_name, mime in (("PNG", "png"), ("JPEG", "jpeg"), ("WEBP", "webp")):
        output = BytesIO()
        picture.save(output, format=format_name)
        images.append(f"data:image/{mime};base64," + base64.b64encode(output.getvalue()).decode())
    return images


async def check_disconnect(manager, profile, port, token, image):
    adapter = manager._slots[manager.execution_key(profile)].adapter
    process = adapter.process
    body = json.dumps({"model": profile.alias, "images": [image] * 16}).encode()
    _, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write((f"POST /v1/images/tags HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {token}\r\n"
                      f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body)
        await writer.drain()
        await until(lambda: manager.status(profile.id).active == 1)
        await asyncio.sleep(0.1)
        assert manager.status(profile.id).active == 1, "Disconnect fixture finished before cancellation"
    finally:
        writer.close()
        await writer.wait_closed()
    await until(lambda: manager.status(profile.id).active == 0)
    assert manager.status(profile.id).queued == 0
    assert process.process.returncode is not None and adapter.process is None


async def validate(state, client, model_ref, port, token):
    manager = state.model_manager
    saved = await checked_json(client, "POST", "/api/models/profiles", json={
        "name": "WD14 CPU smoke", "alias": "wd14-smoke", "kind": "vision", "model_ref": model_ref,
        "source": {"type": "local"}, "external_enabled": True})
    profile = manager.profiles.get(saved["id"])
    model_path = f"/api/models/profiles/{profile.id}"
    discovery = await checked_json(client, "GET", "/v1/models?kind=vision")
    assert [model["id"] for model in discovery["data"]] == [profile.alias]
    assert not manager._slots, "Model discovery loaded a worker"
    health = await checked_json(client, "POST", model_path + "/health")
    assert health["residency"] == "unloaded"
    images, timings = fixture_images(), []

    async def infer(name, inputs, **overrides):
        start = time.monotonic()
        payload = await checked_json(client, "POST", "/v1/images/tags",
            json={"model": profile.alias, "images": inputs, **overrides})
        result = ImageTagsResponse.model_validate(payload)
        assert "usage" not in payload and result.model == profile.alias
        assert [item.index for item in result.data] == list(range(len(inputs)))
        for item in result.data:
            assert [tag.score for tag in item.tags] == sorted((tag.score for tag in item.tags), reverse=True)
        measurement = {"case": name, "seconds": round(time.monotonic() - start, 3),
                       "tag_counts": [len(item.tags) for item in result.data]}
        timings.append(measurement)
        print(json.dumps(measurement), flush=True)
        return result.data

    defaults = profile.parameters["thresholds"]
    initial = await infer("single_autoload", images[:1])
    adapter = manager._slots[manager.execution_key(profile)].adapter
    process = adapter.process.process
    assert (await infer("warm_reuse", images[:1])) == initial
    all_tags = (await infer("zero_thresholds", images[:1], thresholds={"general": 0, "character": 0}))[0].tags
    assert all_tags, "The selected model returned no general or character scores"
    assert initial[0].tags == [tag for tag in all_tags if tag.score >= defaults[tag.category]]
    inherited = await infer("nullable_inheritance", images[:1], thresholds={"general": None, "character": None})
    assert inherited == initial
    partial = await infer("partial_override", images[:1], thresholds={"general": 0})
    assert partial[0].tags == [tag for tag in all_tags if tag.category == "general" or tag.score >= defaults["character"]]
    maximum = await infer("one_thresholds", images[:1], thresholds={"general": 1, "character": 1})
    assert maximum[0].tags == [tag for tag in all_tags if tag.score == 1]
    multiple = await infer("multiple_png_jpeg_webp", images)
    assert multiple[0] == initial[0]
    assert adapter.process.process is process and manager.status(profile.id).residency == "loaded"
    assert manager.profiles.get(profile.id).parameters["thresholds"] == defaults

    await check_disconnect(manager, profile, port, token, images[0])
    await checked_json(client, "POST", model_path + "/load")
    assert (await infer("after_disconnect_reload", images[:1])) == initial
    crashed = adapter.process.process
    crashed.kill()
    await until(lambda: manager.status(profile.id).state == "failed")
    failed = await client.post("/v1/images/tags", json={"model": profile.alias, "images": images[:1]})
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "MODEL_UNAVAILABLE"
    assert adapter.process.process is crashed, "A crashed worker restarted without explicit loading"
    await checked_json(client, "POST", model_path + "/load")
    assert (await infer("after_crash_reload", images[:1])) == initial
    recovered = adapter.process.process
    assert recovered.pid != crashed.pid
    assert "network access rejected" not in manager.process_log(profile)
    unloaded = await checked_json(client, "POST", model_path + "/unload")
    assert unloaded["residency"] == "unloaded" and adapter.process is None and recovered.returncode is not None
    return {"model_ref": model_ref, "parameters": profile.parameters, "execution_options": profile.source.execution_options,
            "timings": timings, "discovery": "passed", "process_reuse": "passed", "offline": "passed",
            "disconnect_cleanup": "passed", "crash_requires_reload": "passed", "unload": "passed"}


async def smoke(root, model_ref):
    engine = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    init_db(engine)
    state = build_runtime_state(root=root, use_memory=True)
    supervisor = state.runtime_supervisor
    supervisor.store = RuntimeStore(engine)
    state.local_runtime_settings = supervisor.settings = LocalRuntimeSettingsStore(engine)
    server, server_task, listener = None, None, None
    started = time.monotonic()
    try:
        supervisor.assert_available()
        versions = json.loads(subprocess.check_output([str(supervisor.executable("wd14", "cpu")), "-c",
            "import importlib.metadata as m,json,sys; print(json.dumps({'python':sys.version,"
            "'packages':{p:m.version(p) for p in ('onnxruntime','numpy','pillow')}}))"], text=True))
        token = secrets.token_urlsafe(32)
        state.model_settings.patch({"external_enabled": True, "external_api_key": token})
        app = create_app(runtime_state=state)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", ws="none"))
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        await until(lambda: server.started)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=310,
                headers={"Authorization": f"Bearer {token}"}, trust_env=False) as client:
            result = await validate(state, client, model_ref, port, token)
        report = {"hardware": {"os": platform.platform(), "architecture": platform.machine(),
                  "processor": platform.processor(), "logical_processors": os.cpu_count()},
                  "runtime": {"version": supervisor.release.version, **versions}, "result": result,
                  "elapsed_seconds": round(time.monotonic() - started, 2)}
        output = root / "build/wd14-smoke/report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"wd14": "passed", "report": str(output)}), flush=True)
    finally:
        if server:
            server.should_exit = True
        if server_task:
            await server_task
        if listener:
            listener.close()
        await state.model_manager.close()
        await supervisor.close()
        engine.dispose()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-ref", required=True, help="Existing WD14-family directory relative to data/models")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(smoke(args.root.resolve(), args.model_ref))
