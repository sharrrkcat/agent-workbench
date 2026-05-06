from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from ai_workbench.api.deps import RuntimeState, build_runtime_state
from ai_workbench.api.routes import agents, commands, configs, health, llm_profiles, messages, runs, sessions
from ai_workbench.api.ws import router as ws_router


def create_app(
    runtime_state: RuntimeState = None,
    llm_runtime: Any = None,
    database_url: str = None,
    use_memory: bool = False,
) -> FastAPI:
    app = FastAPI(title="Agent Workbench")
    app.state.runtime_state = runtime_state or build_runtime_state(
        llm_runtime=llm_runtime,
        database_url=database_url,
        use_memory=use_memory,
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

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc: RequestValidationError):
        message = str(exc.errors()[0].get("msg", "Invalid request")) if exc.errors() else "Invalid request"
        code = "INVALID_USER_CONFIG" if "user_config" in str(exc.errors()) else "VALIDATION_ERROR"
        return JSONResponse(status_code=422, content={"error": {"code": code, "message": message}})

    app.include_router(agents.router)
    app.include_router(commands.router)
    app.include_router(configs.router)
    app.include_router(llm_profiles.router)
    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(messages.router)
    app.include_router(runs.router)
    app.include_router(ws_router)
    return app


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

