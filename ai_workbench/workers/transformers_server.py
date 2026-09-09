"""Authenticated, offline, single-model endpoint for Transformers v5 serve."""
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import math
import os
from pathlib import Path
import socket
import sys
from uuid import uuid4

if __package__:
    from .common import WorkerError, fields, integer, local_model
else:
    sys.path.insert(0, str(Path(__file__).parent))
    from common import WorkerError, fields, integer, local_model

MAX_BODY = 32 * 1024 * 1024
PROTOCOL_VERSION = 1


def options_request(value):
    fields(value, ("device", "intraop_threads"))
    if value["device"] not in {"cpu", "cuda"}:
        raise WorkerError("INVALID_REQUEST")
    integer(value["intraop_threads"], 1, 256)
    return value


def chat_request(body):
    fields(body, ("model", "messages"), ("stream", "n", "temperature", "top_p", "max_tokens", "seed", "stop",
        "presence_penalty", "frequency_penalty", "tools", "tool_choice", "parallel_tool_calls", "response_format", "stream_options"))
    if body["model"] != "managed" or type(body.get("stream", False)) is not bool:
        raise WorkerError("INVALID_REQUEST")
    integer(body.get("n", 1), 1, 1)
    if body.get("tool_choice") not in (None, "auto") or body.get("parallel_tool_calls") is not None:
        raise WorkerError("UNSUPPORTED_CAPABILITY")
    for name in ("presence_penalty", "frequency_penalty"):
        if body.get(name) not in (None, 0):
            raise WorkerError("UNSUPPORTED_CAPABILITY")
    if body.get("response_format") not in (None, {"type": "text"}):
        raise WorkerError("UNSUPPORTED_CAPABILITY")
    for name, high in (("temperature", 2), ("top_p", 1)):
        if name in body and (type(body[name]) not in {int, float} or not math.isfinite(body[name]) or not 0 <= body[name] <= high):
            raise WorkerError("INVALID_REQUEST")
    if "max_tokens" in body:
        integer(body["max_tokens"], 1, sys.maxsize)
    if "seed" in body and type(body["seed"]) is not int:
        raise WorkerError("INVALID_REQUEST")
    if "stop" in body:
        stop = body["stop"]
        if not isinstance(stop, str) and not (isinstance(stop, list) and 1 <= len(stop) <= 4 and all(isinstance(s, str) for s in stop)):
            raise WorkerError("INVALID_REQUEST")
    messages = body["messages"]
    if not isinstance(messages, list) or not messages:
        raise WorkerError("INVALID_REQUEST")
    for message in messages:
        fields(message, ("role",), ("content", "name", "tool_calls", "tool_call_id", "reasoning_content"))
        if message["role"] not in {"system", "developer", "user", "assistant", "tool"}:
            raise WorkerError("INVALID_REQUEST")
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                fields(part, ("type", "text"))
                if part["type"] != "text" or not isinstance(part["text"], str):
                    raise WorkerError("UNSUPPORTED_CAPABILITY")
        elif content is not None and not isinstance(content, str):
            raise WorkerError("INVALID_REQUEST")
    # These explicitly accepted values all mean the upstream default. Do not
    # send fields that serve would silently ignore or reinterpret as penalties.
    return {key: value for key, value in body.items() if key not in {
        "presence_penalty", "frequency_penalty", "tool_choice", "parallel_tool_calls", "response_format"}}


def build_app(engine, token):
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            engine.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def authorize(request: Request, call_next):
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
            return JSONResponse({"error": {"code": "AUTH_INVALID"}}, status_code=401)
        return await call_next(request)

    @app.exception_handler(WorkerError)
    async def worker_error(_request, error):
        return JSONResponse({"error": {"code": error.code}}, status_code=error.status)

    @app.exception_handler(HTTPException)
    async def invalid_request(_request, error):
        return JSONResponse({"error": {"code": "INVALID_REQUEST"}}, status_code=error.status_code)

    @app.get("/health")
    async def health():
        return dict(engine.metadata)

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": "managed", "object": "model", "owned_by": "workbench"}]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_BODY:
                raise WorkerError("REQUEST_TOO_LARGE", 413)
            raw.extend(chunk)
        try:
            body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            body = chat_request(body)
        except (ValueError, TypeError, KeyError) as exc:
            raise WorkerError("INVALID_REQUEST") from exc
        return await engine.chat(body, str(uuid4()))

    return app


def main():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      TOKENIZERS_PARALLELISM="false")
    ready = Path(os.environ["WORKBENCH_WORKER_READY"])
    listener, loop = None, None
    try:
        token = os.environ["WORKBENCH_WORKER_TOKEN"]
        if len(token) < 32:
            raise WorkerError("INVALID_REQUEST")
        options = options_request(json.loads(os.environ["WORKBENCH_RUNTIME_OPTIONS"]))
        path = local_model(Path(os.environ["WORKBENCH_MODELS_ROOT"]).resolve(), os.environ["WORKBENCH_MODEL_REF"])
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.setblocking(False)
        # Windows creates a loopback socket pair for its event loop. Establish
        # that infrastructure before the engine prohibits all outbound connects.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        if __package__:
            from .transformers_engine import TransformersEngine
        else:
            from transformers_engine import TransformersEngine
        engine = TransformersEngine(path, options)
        app = build_app(engine, token)
        import uvicorn
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
        ready.write_text(json.dumps({**engine.metadata, "port": listener.getsockname()[1]}), encoding="utf-8")
        loop.run_until_complete(server.serve(sockets=[listener]))
    except Exception as exc:
        code = exc.code if isinstance(exc, WorkerError) else "MODEL_UNAVAILABLE"
        print(f"Transformers startup failed: {code} ({type(exc).__name__})", flush=True)
        ready.write_text(json.dumps({"protocol_version": PROTOCOL_VERSION, "error_code": code}), encoding="utf-8")
        raise SystemExit(1) from None
    finally:
        if loop:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            asyncio.set_event_loop(None)
        if listener:
            listener.close()


if __name__ == "__main__":
    main()
