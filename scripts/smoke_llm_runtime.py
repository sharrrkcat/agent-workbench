"""Validate local llama-server or Transformers inference without persistent chat records."""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import aclosing
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import socket
import time
import re

import httpx
import uvicorn
from PIL import Image

from ai_workbench.api.deps import build_runtime_state
from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.schema import ChatRequest, ModelProfile
from ai_workbench.core.models.store import LocalRuntimeSettingsStore
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


async def validate_device(state, client, model_ref, device, engine_name, vision=False):
    manager = state.model_manager
    options = {"device": device}
    profile = manager.profiles.create(ModelProfile(name=f'{engine_name} {device} smoke', alias=f'{engine_name}-{device}', kind='llm', model_ref=model_ref, capabilities={'streaming': True, 'tools': not vision, 'vision': vision}, parameters={'temperature': 0, 'max_tokens': 128}, external_enabled=True, source={'type': 'local', 'execution_options': options}))
    manager.settings.patch({"utility_model_profile_id": profile.id})
    loaded = await manager.load(profile.id)
    profile = manager.profile(profile.id)
    assert loaded.residency == "loaded"
    if engine_name == "transformers" or device == "cuda":
        assert loaded.runtime.device_name
    adapter = manager._slots[manager.execution_key(profile)].adapter
    metadata = (await adapter.client.get("/health")).json()
    if engine_name == "transformers":
        assert metadata["device"] == ("cpu" if device == "cpu" else "cuda:0")
        assert metadata["dtype"] == "torch.float32" if device == "cpu" else metadata["dtype"] in {"torch.bfloat16", "torch.float16", "torch.float32"}
    elif device == "cuda":
        assert loaded.runtime.gpu_layers_loaded > 0
    else:
        assert profile.source.execution_options["gpu_layers"] == 0
    if vision:
        if engine_name == "transformers":
            assert metadata["vision"] is True
        result = await validate_vision(state, client, profile, engine_name)
        await manager.unload(profile.id)
        result.update(engine=engine_name, device=device, device_name=loaded.runtime.device_name, dtype=metadata.get("dtype"))
        print(json.dumps(result), flush=True)
        return result
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
    if engine_name == "transformers":
        assert original_process.process.returncode is not None and adapter.process is None
    else:
        assert adapter.process is original_process and original_process.process.returncode is None
        assert (await manager.chat(profile.id, ChatRequest(**request))).message.content
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
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
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
    result = {"engine": engine_name, "device": device, "device_name": loaded.runtime.device_name, "dtype": metadata.get("dtype"),
              "text": "passed", "stream": "passed", "chat": "passed", "title": "passed", "harness": "passed",
              "cancellation": "passed", "cancel_effect": "worker_stopped" if engine_name == "transformers" else "request_closed",
              "crash_reload": "passed", "manual_unload": "passed"}
    print(json.dumps(result), flush=True)
    return result


def vision_image(format_, color):
    output = BytesIO()
    Image.new("RGB", (224, 224), color).save(output, format=format_)
    return output.getvalue()


def image_part(data, mime):
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")}}


def check_colors(text, expected):
    visible = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).lower()
    colors = re.findall(r"\b(red|blue)\b", visible)
    assert colors and all(color in colors for color in expected), f"Expected visible answer colors {expected}, received {text!r}"
    if len(expected) > 1:
        assert colors.index(expected[0]) < colors.index(expected[1]), f"Image order was not preserved: {text!r}"


async def validate_vision(state, client, profile, engine_name):
    manager = state.model_manager
    answers = {}
    red = vision_image("PNG", "red")
    blue = vision_image("PNG", "blue")
    system = {"role": "system", "content": "Answer the visual question briefly, without reasoning. If the user sends only an image, name its main color."}
    base = {"model": profile.alias, "temperature": 0, "max_tokens": 256}
    for format_, mime in (("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")):
        request = {**base, "messages": [system, {"role": "user", "content": [image_part(vision_image(format_, "red"), mime)]}]}
        response = await checked_json(client, "POST", "/v1/chat/completions", json=request)
        answer = response["choices"][0]["message"]["content"]
        check_colors(answer, ["red"])
        answers[format_] = answer
        print(json.dumps({"engine": engine_name, "stage": "vision_format", "format": format_, "answer": answer}), flush=True)

    messages = [system, {"role": "user", "content": [{"type": "text", "text": "Name the main colors of the first and second images, in that order."},
                image_part(red, "image/png"), image_part(blue, "image/png")]}]
    comparison = await checked_json(client, "POST", "/v1/chat/completions", json={**base, "messages": messages})
    answers["comparison"] = comparison["choices"][0]["message"]["content"]
    check_colors(answers["comparison"], ["red", "blue"])
    pieces, finished, done = [], False, False
    async with client.stream("POST", "/v1/chat/completions", json={**base, "messages": messages, "stream": True}) as response:
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
    assert finished and done
    answers["stream"] = "".join(pieces)
    check_colors(answers["stream"], ["red", "blue"])

    session = await checked_json(client, "POST", "/api/sessions", json={"model_profile_id": profile.id,
        "generation": {"temperature": 0, "max_tokens": 256}, "tools_allowed": []})
    attachment = await checked_json(client, "POST", "/api/attachments", files={"file": ("input.png", red, "image/png")})
    path = f"/api/sessions/{session['session_id']}/messages"
    first = await checked_json(client, "POST", path, json={"content": "Remember this image for my next question. Reply only READY.", "attachments": [attachment]})
    assert first["success"], first
    assert "ready" in first["data"].lower() and not re.search(r"\b(red|blue)\b", first["data"], re.IGNORECASE), first["data"]
    followup = await checked_json(client, "POST", path, json={"content": "Name the color in my earlier image again. Answer with one color word."})
    assert followup["success"], followup
    check_colors(followup["data"], ["red"])
    answers["history_acknowledgment"], answers["history"] = first["data"], followup["data"]

    adapter = manager._slots[manager.execution_key(profile)].adapter
    process = adapter.process
    cancel = ChatRequest(**{**base, "messages": messages, "stream": True, "max_tokens": 1024})
    async with aclosing(manager.chat_stream(profile.id, cancel)) as stream:
        async for chunk in stream:
            if chunk.delta.content:
                break
    if engine_name == "transformers":
        assert process.process.returncode is not None and adapter.process is None
    else:
        assert adapter.process is process and process.process.returncode is None
    assert manager.status(profile.id).active == 0 and manager.status(profile.id).queued == 0
    return {"vision": "passed", "formats": ["PNG", "JPEG", "WebP"], "image_only": "passed", "multi_image": "passed",
            "history": "passed", "stream": "passed", "cancellation": "passed", "answers": answers}


async def smoke(root, model_ref, devices, install_only, engine_name, vision=False):
    engine = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    init_db(engine)
    state = build_runtime_state(root=root, use_memory=True)
    supervisor = state.runtime_supervisor
    supervisor.store = RuntimeStore(engine)
    state.local_runtime_settings = supervisor.settings = LocalRuntimeSettingsStore(engine)
    server, server_task, listener = None, None, None
    started = time.monotonic()
    try:
        if install_only:
            job = await supervisor.submit('install')
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
                raise RuntimeError("Local runtime installation failed")
            return
        supervisor.assert_available()
        state.app_settings.patch({"auto_generate_session_titles": False})
        token = secrets.token_urlsafe(32)
        state.model_settings.patch({"external_enabled": True, "external_api_key": token})
        app = create_app(runtime_state=state)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", ws="none"))
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        await until(lambda: server.started)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=360,
                headers={"Authorization": f"Bearer {token}"}, trust_env=False) as client:
            results = [await validate_device(state, client, model_ref, device, engine_name, vision) for device in devices]
        output = root / "build/llm-smoke" / engine_name
        output.mkdir(parents=True, exist_ok=True)
        report = {"model_ref": model_ref, "runtime_version": supervisor.release.version,
                  "results": results, "elapsed_seconds": round(time.monotonic() - started, 2)}
        (output / ("vision-report.json" if vision else "report.json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
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
    parser.add_argument("--engine", choices=("transformers", "llama-server"), default="transformers")
    parser.add_argument("--model-ref", help="Existing model directory relative to data/models")
    parser.add_argument("--device", choices=("cpu", "cuda", "both"), default="both")
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--vision", action="store_true", help="Verify static images, multi-image order, history, streaming and cancellation")
    args = parser.parse_args(argv)
    return args


if __name__ == "__main__":
    args = parse_args()
    reference = args.model_ref or ("llms/Qwen3.5-0.8B-TF" if args.engine == "transformers" else "llms/Qwen3.5-0.8B-GGUF")
    asyncio.run(smoke(args.root.resolve(), reference, ("cuda", "cpu") if args.device == "both" else (args.device,), args.install_only, args.engine, args.vision))
