from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

from ai_workbench.api.deps import RuntimeState, build_runtime_state
from ai_workbench.api.routes import agents, assets, attachments, commands, configs, data, diagnostics, health, inference, intent, knowledge, llm_profiles, llm_provider_profiles, messages, openai_compatible, pets, runs, runtime, sessions, settings, worldbook
from ai_workbench.api.ws import router as ws_router
from ai_workbench.core.inference.observability import (
    REQUEST_ID_HEADER,
    elapsed_ms,
    is_inference_observability_path,
    log_access_event,
    log_unhandled_exception,
    monotonic_time,
    reset_current_request_id,
    resolve_request_id,
    set_current_request_id,
)


@asynccontextmanager
async def runtime_lifespan(app: FastAPI):
    try:
        yield
    finally:
        state = app.state.runtime_state
        state.events.close()
        await state.active_runs.cancel_all()


def create_app(
    runtime_state: RuntimeState = None,
    llm_runtime: Any = None,
    database_url: str = None,
    use_memory: bool = False,
    frontend_dist: str | Path | None = None,
    root: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Agent Workbench", lifespan=runtime_lifespan)
    app.state.runtime_state = runtime_state or build_runtime_state(
        llm_runtime=llm_runtime,
        database_url=database_url,
        use_memory=use_memory,
        root=root,
    )
    from ai_workbench.core.inference.clip_runtime import register_clip_open_clip_runtime_factories
    from ai_workbench.core.inference.dinov2_runtime import register_dinov2_runtime_factory
    from ai_workbench.core.inference.florence2_runtime import register_florence2_runtime_factory
    from ai_workbench.core.inference.siglip2_runtime import register_siglip2_runtime_factory

    register_clip_open_clip_runtime_factories(
        repo_root=app.state.runtime_state.repo_root,
        provider_profile_store=app.state.runtime_state.provider_profiles,
    )
    register_siglip2_runtime_factory(
        repo_root=app.state.runtime_state.repo_root,
        provider_profile_store=app.state.runtime_state.provider_profiles,
    )
    register_dinov2_runtime_factory(
        repo_root=app.state.runtime_state.repo_root,
        provider_profile_store=app.state.runtime_state.provider_profiles,
    )
    register_florence2_runtime_factory(
        repo_root=app.state.runtime_state.repo_root,
        provider_profile_store=app.state.runtime_state.provider_profiles,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def inference_observability_middleware(request, call_next):
        path = request.url.path
        if not is_inference_observability_path(path):
            return await call_next(request)

        repo_root = getattr(app.state.runtime_state, "repo_root", None)
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = set_current_request_id(request_id)
        request.state.inference_request_id = request_id
        start = monotonic_time()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        except Exception as exc:
            log_unhandled_exception(
                repo_root=repo_root,
                method=request.method,
                path=path,
                exception=exc,
            )
            raise
        finally:
            log_access_event(
                repo_root=repo_root,
                method=request.method,
                path=path,
                status_code=status_code,
                duration_ms=elapsed_ms(start),
                error_code=getattr(request.state, "inference_error_code", None),
            )
            reset_current_request_id(token)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            _record_inference_error_code(request, exc.detail)
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        _record_inference_error_code(request, {"error": {"code": "HTTP_ERROR"}})
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc: RequestValidationError):
        message = str(exc.errors()[0].get("msg", "Invalid request")) if exc.errors() else "Invalid request"
        code = "INVALID_USER_CONFIG" if "user_config" in str(exc.errors()) else "VALIDATION_ERROR"
        _record_inference_error_code(request, {"error": {"code": code}})
        return JSONResponse(status_code=422, content={"error": {"code": code, "message": message}})

    app.include_router(agents.router)
    app.include_router(assets.router)
    app.include_router(attachments.router)
    app.include_router(commands.router)
    app.include_router(configs.router)
    app.include_router(data.router)
    app.include_router(diagnostics.router)
    app.include_router(intent.router)
    app.include_router(openai_compatible.router)
    app.include_router(inference.router)
    app.include_router(llm_profiles.router)
    app.include_router(llm_provider_profiles.router)
    app.include_router(knowledge.router)
    app.include_router(worldbook.router)
    app.include_router(settings.router)
    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(messages.router)
    app.include_router(messages.message_router)
    app.include_router(pets.router)
    app.include_router(runs.router)
    app.include_router(runtime.router)
    app.include_router(ws_router)
    configure_frontend_routes(app, frontend_dist)
    return app


def configure_frontend_routes(app: FastAPI, frontend_dist: str | Path | None = None) -> None:
    dist = _resolve_frontend_dist(frontend_dist)
    index_html = dist / "index.html"
    app.state.frontend_dist = dist

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def frontend_root():
        if index_html.is_file():
            return FileResponse(index_html)
        return PlainTextResponse(
            "frontend build not found; please run: cd frontend && npm run build",
            status_code=503,
        )

    @app.get("/{path:path}", include_in_schema=False)
    def frontend_fallback(path: str):
        if _is_backend_path(path):
            raise HTTPException(status_code=404, detail="Not found")
        if not index_html.is_file():
            return PlainTextResponse(
                "frontend build not found; please run: cd frontend && npm run build",
                status_code=503,
            )
        requested = (dist / path).resolve()
        try:
            requested.relative_to(dist.resolve())
        except ValueError:
            requested = index_html
        if requested.is_file():
            return FileResponse(requested)
        return FileResponse(index_html)


def _resolve_frontend_dist(frontend_dist: str | Path | None) -> Path:
    configured = frontend_dist or os.environ.get("AGENT_WORKBENCH_FRONTEND_DIST")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()


def _is_backend_path(path: str) -> bool:
    first_segment = path.split("/", 1)[0]
    return first_segment in {"api", "v1", "docs", "openapi.json", "redoc"}


def _record_inference_error_code(request, detail: dict) -> None:
    try:
        if not is_inference_observability_path(request.url.path):
            return
        error = detail.get("error") if isinstance(detail, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if code:
            request.state.inference_error_code = str(code)
    except Exception:
        return


class LazyApp:
    def __init__(self) -> None:
        self._app: Optional[FastAPI] = None

    def get_app(self) -> FastAPI:
        if self._app is None:
            self._app = create_app()
        return self._app

    async def __call__(self, scope, receive, send) -> None:
        await self.get_app()(scope, receive, send)


app = LazyApp()

