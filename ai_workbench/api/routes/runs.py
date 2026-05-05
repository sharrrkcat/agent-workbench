from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.schema.run import RunStatus


router = APIRouter(tags=["runs"])


@router.get("/api/sessions/{session_id}/runs")
def list_runs(session_id: str, state: RuntimeState = Depends(get_state)) -> list:
    try:
        state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")
    return [run.model_dump() for run in state.runs.list_runs(session_id)]


@router.get("/api/runs/{run_id}")
def get_run(run_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return state.runs.get_run(run_id).model_dump()
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")


@router.get("/api/runs/{run_id}/events")
def list_run_events(run_id: str, state: RuntimeState = Depends(get_state)) -> list:
    try:
        state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")
    return [event.model_dump() for event in state.run_events.list_events(run_id)]


@router.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        run = state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")

    cancellable = {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_FOR_USER}
    if run.status not in cancellable:
        return {
            "run": run.model_dump(),
            "cancelled": False,
            "reason": f"Run status {run.status.value} is not cancellable.",
        }

    was_waiting = run.status == RunStatus.WAITING_FOR_USER
    run = state.runs.update_status(run_id, RunStatus.CANCELLED, current_step="cancelled")
    if was_waiting:
        try:
            session = state.sessions.get_session(run.session_id)
            if session.waiting_run_id == run.run_id:
                state.sessions.set_waiting_run(run.session_id, None)
        except KeyError:
            pass
    state.events.emit("run_cancelled", session_id=run.session_id, run_id=run.run_id)
    return {
        "run": run.model_dump(),
        "cancelled": True,
        "reason": "Run was marked cancelled.",
    }
