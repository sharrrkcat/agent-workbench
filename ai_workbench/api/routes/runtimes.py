from fastapi import APIRouter, Depends, Query

from ai_workbench.api.deps import get_state
from ai_workbench.api.schemas.common import TextResponse, error_responses
from ai_workbench.api.schemas.models import InstallationResponse, RuntimeCatalogResponse, RuntimeJobResponse
from ai_workbench.core.models.runtimes.schema import (
    CacheCleanupRequest, LlamaCPUOptions, LlamaCUDAOptions, OnnxCPUOptions, PythonOptions, RuntimeStorage,
)
from pydantic import TypeAdapter

router = APIRouter(prefix="/api/models", tags=["runtimes"])


@router.get("/backends/local/runtime/catalog", response_model=RuntimeCatalogResponse)
def catalog(state=Depends(get_state)):
    release = state.runtime_supervisor.release
    schemas = {"llama-server": LlamaCPUOptions | LlamaCUDAOptions, "transformers": PythonOptions,
               "kokoro": OnnxCPUOptions, "chatterbox": PythonOptions, "qwen3tts": PythonOptions}
    return {**release.model_dump(include={"version", "platform", "architecture", "supported", "reason"}),
            "engines": [{"engine": engine, "kind": "llm" if engine in {"llama-server", "transformers"} else "tts",
                         "options_schema": TypeAdapter(schema).json_schema()} for engine, schema in schemas.items()]}


@router.get("/backends/local/runtime", response_model=InstallationResponse, response_model_exclude_unset=True)
def installation(state=Depends(get_state)):
    return state.runtime_supervisor.installation().model_dump(mode="json", exclude={"manifest_sha256"})


@router.get("/runtimes/storage", response_model=RuntimeStorage)
async def storage(state=Depends(get_state)):
    return await state.runtime_supervisor.storage()


@router.post("/runtimes/cache/cleanup", status_code=202, response_model=RuntimeJobResponse,
             response_model_exclude_unset=True, responses=error_responses(409, 503))
async def cleanup_cache(payload: CacheCleanupRequest, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit_cache(payload.mode))


@router.get("/runtimes/jobs", response_model=list[RuntimeJobResponse], response_model_exclude_unset=True)
def jobs(limit: int = Query(100, ge=1, le=200), state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return [supervisor.public_job(job) for job in supervisor.store.jobs()[:limit]]


@router.get("/runtimes/jobs/{job_id}", response_model=RuntimeJobResponse, response_model_exclude_unset=True, responses=error_responses(404))
def job(job_id: str, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(supervisor.store.job(job_id))


@router.post("/runtimes/jobs/{job_id}/cancel", response_model=RuntimeJobResponse, response_model_exclude_unset=True,
             responses=error_responses(404, 409))
async def cancel(job_id: str, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.cancel(job_id))


@router.get("/runtimes/jobs/{job_id}/log", response_model=TextResponse, responses=error_responses(404))
def log(job_id: str, state=Depends(get_state)):
    return {"text": state.runtime_supervisor.log_text(job_id)}


@router.post("/backends/local/runtime/install", status_code=202, response_model=RuntimeJobResponse,
             response_model_exclude_unset=True, responses=error_responses(404, 409, 422, 503))
async def install(state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit("install"))


@router.post("/backends/local/runtime/repair", status_code=202, response_model=RuntimeJobResponse,
             response_model_exclude_unset=True, responses=error_responses(404, 409, 422, 503))
async def repair(state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit("repair"))


@router.post("/backends/local/runtime/uninstall", status_code=202, response_model=RuntimeJobResponse,
             response_model_exclude_unset=True, responses=error_responses(404, 409, 422, 503))
async def uninstall(state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit("uninstall"))
