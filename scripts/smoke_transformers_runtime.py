"""Install and validate a local Transformers checkpoint without persistent model/chat records."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import aclosing
import json
import os
from pathlib import Path
import secrets
import socket
import time

import httpx
import uvicorn

from ai_workbench.api.deps import build_runtime_state
from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.schema import ChatRequest, ModelProfile
from ai_workbench.db.database import get_engine, init_db


async def until(predicate, seconds=20):
    deadline = asyncio.get_running_loop().time() + seconds
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Runtime state did not settle before the deadline")
        await asyncio.sleep(0.05)


async def checked_json(client, method, path, **kwargs):
    response = await client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()


async def validate_device(state, client, model_ref, device):
    manager = state.model_manager
    profile = manager.profiles.create(ModelProfile(name=f"Transformers {device} smoke", alias=f"transformers-{device}",
        kind="llm", model_ref=model_ref, runtime_id="python-worker", runtime_variant="transformers-cuda",
        runtime_options={"device": device}, capabilities={"streaming": True, "tools": True},
        parameters={"temperature": 0, "max_tokens": 128}, external_enabled=True))
    manager.settings.patch({"utility_model_profile_id": profile.id})
    loaded = await manager.load(profile.id)
    assert loaded.residency == "loaded" and loaded.runtime.device_name
    adapter = manager._slots[manager.backend_key(profile)].adapter
    metadata = (await adapter.client.get("/health")).json()
    assert metadata["device"] == ("cpu" if device == "cpu" else "cuda:0")
    assert metadata["dtype"] == "torch.float32" if device == "cpu" else metadata["dtype"] in {"torch.bfloat16", "torch.float16", "torch.float32"}
    request = {"model": profile.alias, "messages": [{"role": "user", "content": "Say hello in a short sentence."}],
               "temperature": 0, "max_tokens": 32}
    reply = await checked_json(client, "POST", "/v1/chat/completions", json=request)
    assert reply["choices"][0]["message"]["content"]
    pieces, finished, done = [], False, False
    async with client.stream("POST", "/v1/chat/completions", json={**request, "stream": True}) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line == "data: [DONE]":
                done = True
            elif line.startswith("data: "):
                chunk = json.loads(line[6:])
                assert "error" not in chunk, chunk
                for choice in chunk["choices"]:
                    pieces.append(choice["delta"].get("content") or "")
                    finished = finished or choice.get("finish_reason") is not None
    assert done and finished and "".join(pieces)
    assert manager.status(profile.id).residency == "loaded"

    session = await checked_json(client, "POST", "/api/sessions", json={"model_profile_id": profile.id,
        "generation": {"temperature": 0, "max_tokens": 32}, "tools_allowed": []})
    chat = await checked_json(client, "POST", f"/api/sessions/{session['session_id']}/messages",
                              json={"content": "Greet me briefly."})
    assert chat["success"] and chat["run"]["status"] == "DONE" and chat["data"]
    title = await state.utility_llm.generate_title("Plan a simple afternoon walk")
    assert title

    harness_session = await checked_json(client, "POST", "/api/sessions", json={"model_profile_id": profile.id,
        "harness_enabled": True, "tools_allowed": ["base64_encode"], "generation": {"temperature": 0, "max_tokens": 192}})
    harness = await checked_json(client, "POST", f"/api/sessions/{harness_session['session_id']}/messages", json={
        "content": "Call the base64_encode tool with value hello. After receiving its result, return only the encoded value. Use the tool; do not calculate it yourself."})
    tool_results = [part for message in harness["messages"] for part in message["parts"] if part["type"] == "tool_result"]
    assert harness["success"] and harness["run"]["status"] == "DONE", harness["run"]
    assert any(part["data"].get("value") == "aGVsbG8=" for part in tool_results), "The model did not complete the requested Harness tool call"
    assert harness["data"]

    original_process = adapter.process
    cancel_request = ChatRequest(model=profile.alias, messages=[{"role": "user", "content": "Count from 1 to 1000, one number per line."}],
                                 stream=True, temperature=0, max_tokens=1024)
    async with aclosing(manager.chat_stream(profile.id, cancel_request)) as stream:
        async for chunk in stream:
            if chunk.delta.content:
                break
    assert original_process.process.returncode is not None and adapter.process is None
    assert manager.status(profile.id).active == 0 and manager.status(profile.id).queued == 0
    await manager.load(profile.id)
    adapter.process.process.kill()
    await until(lambda: adapter.failed)
    try:
        await manager.chat(profile.id, ChatRequest(**request))
    except ModelError:
        pass
    else:
        raise AssertionError("A crashed model was implicitly reloaded")
    await manager.load(profile.id)
    assert (await manager.chat(profile.id, ChatRequest(**request))).message.content
    await manager.unload(profile.id)

    if device == "cuda":
        old = os.environ.get("CUDA_VISIBLE_DEVICES")
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        try:
            try:
                await manager.load(profile.id)
            except ModelError as exc:
                assert exc.code == "RUNTIME_DEVICE_UNAVAILABLE", exc.code
            else:
                raise AssertionError("Unavailable CUDA did not fail explicitly")
        finally:
            if old is None:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            else:
                os.environ["CUDA_VISIBLE_DEVICES"] = old
        await manager.unload(profile.id)
    result = {"device": device, "device_name": metadata["device_name"], "dtype": metadata["dtype"],
              "text": "passed", "stream": "passed", "chat": "passed", "title": "passed", "harness": "passed",
              "cancellation": "passed", "crash_reload": "passed", "manual_unload": "passed"}
    print(json.dumps(result), flush=True)
    return result


async def smoke(root, model_ref, devices, install_only):
    engine = get_engine(f"sqlite:///{root / 'data/agent_workbench.db'}")
    init_db(engine)
    state = build_runtime_state(root=root, use_memory=True)
    supervisor = state.runtime_supervisor
    supervisor.store = RuntimeStore(engine)
    server, server_task = None, None
    started = time.monotonic()
    try:
        job = await supervisor.submit("python-worker", "transformers-cuda", "install")
        last_stage = None
        while supervisor.task and not supervisor.task.done():
            current = supervisor.store.job(job.id)
            if current.stage != last_stage:
                last_stage = current.stage
                print(json.dumps({"stage": current.stage}), flush=True)
            await asyncio.wait({supervisor.task}, timeout=1)
        result = supervisor.store.job(job.id)
        print(json.dumps({"installation_job": job.id, "state": result.state, "error_code": result.error_code}), flush=True)
        if result.state != "completed":
            print(supervisor.log_text(job.id), flush=True)
            raise RuntimeError("Transformers installation failed")
        if install_only:
            return
        state.app_settings.patch({"auto_generate_session_titles": False})
        token = secrets.token_urlsafe(32)
        state.model_settings.patch({"external_enabled": True, "external_api_key": token})
        app = create_app(runtime_state=state)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", ws="none"))
            server_task = asyncio.create_task(server.serve(sockets=[listener]))
            await until(lambda: server.started)
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=360,
                    headers={"Authorization": f"Bearer {token}"}, trust_env=False) as client:
                results = [await validate_device(state, client, model_ref, device) for device in devices]
            output = root / "build/transformers-smoke"
            output.mkdir(parents=True, exist_ok=True)
            report = {"model_ref": model_ref, "runtime_version": supervisor.entry("python-worker", "transformers-cuda").version,
                      "results": results, "elapsed_seconds": round(time.monotonic() - started, 2)}
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        if server:
            server.should_exit = True
        if server_task:
            await server_task
        await state.model_manager.close()
        await supervisor.close()
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-ref", default="llms/Qwen3.5-0.8B-TF")
    parser.add_argument("--device", choices=("cpu", "cuda", "both"), default="both")
    parser.add_argument("--install-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(smoke(args.root.resolve(), args.model_ref, ("cuda", "cpu") if args.device == "both" else (args.device,), args.install_only))
