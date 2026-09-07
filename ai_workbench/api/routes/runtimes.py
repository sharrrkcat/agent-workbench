from fastapi import APIRouter, Depends, Query

from ai_workbench.api.deps import get_state
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import CacheCleanupRequest, RuntimeStorage

router = APIRouter(prefix="/api/models", tags=["runtimes"])


@router.get("/runtime/settings")
def settings(state=Depends(get_state)):
    return state.runtime_supervisor.store.settings().model_dump()


@router.patch("/runtime/settings")
def patch_settings(payload: dict, state=Depends(get_state)):
    if state.runtime_supervisor.active_job:
        raise ModelError("RUNTIME_INSTALLING", "Wait for the runtime task before editing download settings.", 409)
    return state.runtime_supervisor.store.patch_settings(payload).model_dump()


@router.get("/runtimes/catalog")
def catalog(state=Depends(get_state)):
    return [entry.model_dump() for entry in state.runtime_supervisor.entries]


@router.get("/runtimes")
def installations(state=Depends(get_state)):
    return [value.model_dump(mode="json", exclude={"manifest_sha256"}) for value in state.runtime_supervisor.installations()]


@router.get("/runtimes/storage", response_model=RuntimeStorage)
async def storage(state=Depends(get_state)):
    return await state.runtime_supervisor.storage()


@router.post("/runtimes/cache/cleanup", status_code=202)
async def cleanup_cache(payload: CacheCleanupRequest, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit_cache(payload.mode))


@router.get("/runtimes/jobs")
def jobs(limit: int = Query(100, ge=1, le=200), state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return [supervisor.public_job(job) for job in supervisor.store.jobs()[:limit]]


@router.get("/runtimes/jobs/{job_id}")
def job(job_id: str, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(supervisor.store.job(job_id))


@router.post("/runtimes/jobs/{job_id}/cancel")
async def cancel(job_id: str, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.cancel(job_id))


@router.get("/runtimes/jobs/{job_id}/log")
def log(job_id: str, state=Depends(get_state)):
    return {"text": state.runtime_supervisor.log_text(job_id)}


@router.get("/runtimes/{runtime_id}/{variant}")
def installation(runtime_id: str, variant: str, state=Depends(get_state)):
    return state.runtime_supervisor.installation(runtime_id, variant).model_dump(mode="json", exclude={"manifest_sha256"})


@router.post("/runtimes/{runtime_id}/{variant}/install", status_code=202)
async def install(runtime_id: str, variant: str, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit(runtime_id, variant, "install"))


@router.post("/runtimes/{runtime_id}/{variant}/uninstall", status_code=202)
async def uninstall(runtime_id: str, variant: str, state=Depends(get_state)):
    supervisor = state.runtime_supervisor
    return supervisor.public_job(await supervisor.submit(runtime_id, variant, "uninstall"))
