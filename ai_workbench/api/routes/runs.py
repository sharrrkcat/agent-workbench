from __future__ import annotations

from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.schema.run import RunStatus


router = APIRouter(tags=["runs"])


@router.get("/api/sessions/{session_id}/runs")
def list_runs(session_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    _require_session(state, session_id)
    return [_run_payload(state, run) for run in state.runs.list_runs(session_id)]


@router.get("/api/runs/{run_id}")
def get_run(run_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return _run_payload(state, state.runs.get_run(run_id))
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")


@router.get("/api/runs/{run_id}/steps")
def list_run_steps(run_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    try:
        state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")
    return [step.model_dump(mode="json") for step in state.runs.list_steps(run_id)]


@router.get("/api/runs/{run_id}/events")
def list_run_events(run_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    try:
        state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")
    return [event.model_dump(mode="json") for event in state.run_events.list_events(run_id)]


@router.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        run = state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")
    terminal = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
    if run.status in terminal:
        return {"run": _run_payload(state, run), "cancelled": False, "reason": f"Run status {run.status.value} is not cancellable."}
    was_waiting = run.status == RunStatus.WAITING_FOR_USER
    requested = state.runs.update_status(
        run_id,
        RunStatus.CANCELLING,
        current_step="cancelling",
        cancel_requested=True,
    )
    task_cancelled = state.active_runs.cancel(run_id)
    if not task_cancelled:
        requested = state.runs.update_status(
            run_id,
            RunStatus.CANCELLED,
            current_step="cancelled",
            error="Run was cancelled.",
            error_code="RUN_CANCELLED",
            cancel_requested=True,
        )
        state.events.emit("run_cancelled", session_id=requested.session_id, run_id=requested.run_id)
    if was_waiting:
        try:
            session = state.sessions.get_session(requested.session_id)
            if session.waiting_run_id == requested.run_id:
                state.sessions.set_waiting_run(requested.session_id, None)
        except KeyError:
            pass
    return {
        "run": _run_payload(state, state.runs.get_run(run_id)),
        "cancelled": True,
        "task_cancelled": task_cancelled,
        "reason": "Run cancellation was requested." if task_cancelled else "Run was marked cancelled.",
    }


def _require_session(state: RuntimeState, session_id: str) -> None:
    try:
        state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")


def _run_payload(state: RuntimeState, run) -> dict:
    payload = run.model_dump(mode="json")
    payload["steps"] = [step.model_dump(mode="json") for step in state.runs.list_steps(run.run_id)]
    return payload
