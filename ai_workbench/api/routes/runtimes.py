from fastapi import APIRouter, Depends, Query

from ai_workbench.api.deps import get_state
from ai_workbench.api.schemas.common import TextResponse, error_responses
from ai_workbench.api.schemas.models import InstallationResponse, RuntimeCatalogResponse, RuntimeJobResponse, LocalRuntimeSettingsPatch
from ai_workbench.api.openapi import request_body
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import (
    CacheCleanupRequest, LocalRuntimeSettings, LlamaCPUOptions, LlamaCUDAOptions, OnnxCPUOptions, PythonOptions, SiglipOptions, EmbeddingOptions, RerankerOptions, RuntimeStorage,
)
from pydantic import TypeAdapter

router = APIRouter(prefix="/api/models/local-runtime", tags=["runtimes"])


@router.get("/settings", response_model=LocalRuntimeSettings)
def settings(state=Depends(get_state)):
    return state.local_runtime_settings.get()


@router.patch("/settings", response_model=LocalRuntimeSettings,
              openapi_extra=request_body(LocalRuntimeSettingsPatch), responses=error_responses(409, 422))
async def update_settings(payload: dict, state=Depends(get_state)):
    current = state.local_runtime_settings.get()
    merged = current.model_dump()
    for key, value in payload.items():
        merged[key] = {**merged[key], **value} if key == "download" and isinstance(value, dict) else value
    values = LocalRuntimeSettings.model_validate(merged)
    if state.runtime_supervisor.active_job:
        raise ModelError("RUNTIME_INSTALLING", "Wait for runtime maintenance before changing local settings.", 409)
    if values.enabled != current.enabled:
        await state.model_manager.invalidate_local()
    result = state.local_runtime_settings.patch(values.model_dump())
    state.model_manager.runtime_changed()
    return result


@router.get("/catalog", response_model=RuntimeCatalogResponse)
def catalog(state=Depends(get_state)):
    release = state.runtime_supervisor.release
    schemas = {"llama-server": LlamaCPUOptions | LlamaCUDAOptions, "transformers": PythonOptions,
               "kokoro": OnnxCPUOptions, "wd14": OnnxCPUOptions, "chatterbox": PythonOptions, "qwen3tts": PythonOptions,
               "siglip2": SiglipOptions, "sentence-transformers": EmbeddingOptions, "cross-encoder": RerankerOptions}
    return {**release.model_dump(include={"version", "platform", "architecture", "supported", "reason"}),
            "engines": [{"engine": engine, "kind": "llm" if engine in {"llama-server", "transformers"} else "vision" if engine == "wd14" else "image_embedding" if engine == "siglip2" else "embedding" if engine == "sentence-transformers" else "reranker" if engine == "cross-encoder" else "tts",
                         "options_schema": TypeAdapter(schema).json_schema()} for engine, schema in schemas.items()]}


@router.get("", response_model=InstallationResponse, response_model_exclude_unset=True)
def installation(state=Depends(get_state)):
    return state.runtime_supervisor.installation().model_dump(mode="json", exclude={"manifest_sha256"})


@router.get("/storage", response_model=RuntimeStorage)
async def storage(state=Depends(get_state)):
    return await state.runtime_supervisor.storage()


@router.post("/cache/cleanup", status_code=202, response_model=RuntimeJobResponse,
             response_model_exclude_unset=True, responses=error_responses(409, 503))
async def cleanup_cache(payload: CacheCleanupRequest, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit_cache(payload.mode))


@router.get("/jobs", response_model=list[RuntimeJobResponse], response_model_exclude_unset=True)
def jobs(limit: int = Query(100, ge=1, le=200), state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return [supervisor.public_job(job) for job in supervisor.store.jobs()[:limit]]


@router.get("/jobs/{job_id}", response_model=RuntimeJobResponse, response_model_exclude_unset=True, responses=error_responses(404))
def job(job_id: str, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(supervisor.store.job(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=RuntimeJobResponse, response_model_exclude_unset=True,
             responses=error_responses(404, 409))
async def cancel(job_id: str, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.cancel(job_id))


@router.get("/jobs/{job_id}/log", response_model=TextResponse, responses=error_responses(404))
def log(job_id: str, state=Depends(get_state)):
    return {"text": state.runtime_supervisor.log_text(job_id)}


@router.post("/install", status_code=202, response_model=RuntimeJobResponse,
             response_model_exclude_unset=True, responses=error_responses(404, 409, 422, 503))
async def install(state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit("install"))


@router.post("/repair", status_code=202, response_model=RuntimeJobResponse,
             response_model_exclude_unset=True, responses=error_responses(404, 409, 422, 503))
async def repair(state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit("repair"))


@router.post("/uninstall", status_code=202, response_model=RuntimeJobResponse,
             response_model_exclude_unset=True, responses=error_responses(404, 409, 422, 503))
async def uninstall(state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit("uninstall"))
