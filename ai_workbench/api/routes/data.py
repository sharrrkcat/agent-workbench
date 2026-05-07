from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.storage_maintenance import cleanup_orphan_attachments, scan_orphan_attachments, storage_stats


router = APIRouter(prefix="/api/data", tags=["data"])


class CleanupOrphansRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False


@router.get("/storage-stats")
def get_storage_stats(state: RuntimeState = Depends(get_state)) -> dict:
    return storage_stats(state.messages, database_url=state.database_url)


@router.post("/attachments/scan-orphans")
def scan_attachment_orphans(state: RuntimeState = Depends(get_state)) -> dict:
    scan = scan_orphan_attachments(state.messages)
    return {
        "orphan_count": scan["orphan_count"],
        "orphan_size_bytes": scan["orphan_size_bytes"],
        "orphans": scan["orphans"],
    }


@router.post("/attachments/cleanup-orphans")
def cleanup_attachment_orphans(payload: CleanupOrphansRequest, state: RuntimeState = Depends(get_state)) -> dict:
    if payload.confirm is not True:
        raise_error(400, "CONFIRMATION_REQUIRED", "Clean orphan attachments requires confirm=true.")
    return cleanup_orphan_attachments(state.messages)
