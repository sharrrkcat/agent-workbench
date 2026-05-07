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
    return [_run_payload(state, run) for run in state.runs.list_runs(session_id)]


@router.get("/api/runs/{run_id}")
def get_run(run_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        run = state.runs.get_run(run_id)
        return _run_payload(state, run)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")


@router.get("/api/runs/{run_id}/steps")
def list_run_steps(run_id: str, state: RuntimeState = Depends(get_state)) -> list:
    try:
        state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")
    return [step.model_dump() for step in state.runs.list_steps(run_id)]


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

    cancellable = {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.CANCELLING, RunStatus.WAITING_FOR_USER}
    if run.status not in cancellable:
        return {
            "run": _run_payload(state, run),
            "cancelled": False,
            "reason": f"Run status {run.status.value} is not cancellable.",
        }

    was_waiting = run.status == RunStatus.WAITING_FOR_USER
    lifecycle = getattr(getattr(state, "agent_runner", None), "run_lifecycle", None)
    if lifecycle is not None and run.status != RunStatus.CANCELLING:
        run = lifecycle.request_cancel(run_id)
    else:
        run = state.runs.update_status(run_id, RunStatus.CANCELLING, current_step="cancelling", cancel_requested=True)

    task_cancelled = False
    active_runs = getattr(state, "active_runs", None)
    if active_runs is not None:
        task_cancelled = bool(active_runs.cancel(run_id))

    if task_cancelled:
        run = state.runs.get_run(run_id)
    elif lifecycle is not None:
        run = lifecycle.cancel_run(run_id)
    else:
        run = state.runs.update_status(run_id, RunStatus.CANCELLED, current_step="cancelled", cancel_requested=True)
    if was_waiting:
        try:
            session = state.sessions.get_session(run.session_id)
            if session.waiting_run_id == run.run_id:
                state.sessions.set_waiting_run(run.session_id, None)
        except KeyError:
            pass
    if not task_cancelled and lifecycle is None:
        state.events.emit("run_cancelled", session_id=run.session_id, run_id=run.run_id)
    return {
        "run": _run_payload(state, run),
        "cancelled": True,
        "task_cancelled": task_cancelled,
        "reason": "Run cancellation was requested." if task_cancelled else "Run was marked cancelled.",
    }


def _run_payload(state: RuntimeState, run) -> dict:
    payload = run.model_dump()
    payload["steps"] = [step.model_dump() for step in state.runs.list_steps(run.run_id)]
    return payload
