from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from ai_workbench.api.schemas.history import RunEventsPage

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.schemas.common import error_responses
from ai_workbench.api.schemas.chat import RunResponse, RunStepResponse, RunEventResponse, RunCancellation, HistoryResult
from ai_workbench.core.conversation_history import HistoryPruned
from ai_workbench.api.errors import raise_error
from ai_workbench.api.routes.messages import _result_payload
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.schema.context_snapshot import ContextDetail
from ai_workbench.core.context_snapshot import context_detail


router = APIRouter(tags=["runs"])


@router.get("/api/runs/{run_id}", response_model=RunResponse, response_model_exclude_unset=True,
    responses=error_responses(404))
def get_run(run_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        return _run_payload(state, state.runs.get_run(run_id))
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")


@router.delete("/api/runs/{run_id}", response_model=HistoryPruned, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 409))
async def delete_run(run_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    return state.history.delete_reply(run_id).model_dump()


@router.post("/api/runs/{run_id}/retry", response_model=HistoryResult, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 409, 422))
async def retry_run(run_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    run, source, change = state.history.retry(run_id)
    session = state.sessions.get_session(run.session_id)
    result = await state.runtime.retry_chat_run(session, run, source)
    if not result.success and not result.run_id:
        raise_error(400, result.error_code or "RUN_RETRY_FAILED", result.error or "Reply retry failed.")
    return {**_result_payload(state, run.session_id, result), **change.model_dump()}


@router.get("/api/runs/{run_id}/steps", response_model=list[RunStepResponse], response_model_exclude_unset=True,
    responses=error_responses(404))
def list_run_steps(run_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    try:
        state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")
    return [step.model_dump(mode="json") for step in state.runs.list_steps(run_id)]


@router.get("/api/runs/{run_id}/steps/{step_id}/context", response_model=ContextDetail, response_model_exclude_unset=True,
    responses=error_responses(404))
def get_run_context(run_id: str, step_id: str, state: RuntimeState = Depends(get_state)) -> ContextDetail:
    try:
        state.runs.get_run(run_id)
        step = state.runs.get_step(step_id)
        if step.run_id != run_id or step.kind != "model":
            raise KeyError(step_id)
        snapshot = state.runs.get_context_snapshot(step_id)
    except KeyError:
        raise_error(404, "CONTEXT_NOT_FOUND", "No recorded context exists for this model call.")
    detail = context_detail(snapshot)
    detail.reference_numbers = state.history_reader.reference_numbers(
        state.runs.get_run(run_id).session_id, {source.reference_id for source in detail.sources if source.reference_id})
    return detail


@router.get("/api/runs/{run_id}/events", response_model=RunEventsPage, response_model_exclude_unset=True,
    responses=error_responses(404, 422))
def list_run_events(run_id: str, after: str | None = Query(default=None, max_length=1024),
                    limit: int = Query(default=100, ge=1, le=500), state: RuntimeState = Depends(get_state)) -> dict:
    try:
        state.runs.get_run(run_id)
    except KeyError:
        raise_error(404, "RUN_NOT_FOUND", f"Run not found: {run_id}")
    try:
        return state.run_events.page_events(run_id, after, limit)
    except ValueError:
        raise_error(422, "INVALID_HISTORY_CURSOR", "Invalid event cursor.")


@router.post("/api/runs/{run_id}/cancel", response_model=RunCancellation, response_model_exclude_unset=True,
    responses=error_responses(404))
async def cancel_run(run_id: str, state: RuntimeState = Depends(get_state)) -> dict:
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
        if (run.metadata or {}).get("harness"):
            state.chat_runner.harness_loop.cancel(requested)
        else:
            requested = state.runs.update_status(
            run_id,
            RunStatus.CANCELLED,
            current_step="cancelled",
            error="Run was cancelled.",
            error_code="RUN_CANCELLED",
            cancel_requested=True,
        )
            state.events.emit("run_cancelled", session_id=requested.session_id, run_id=requested.run_id,
                              payload={"run": requested.model_dump(mode="json")})
    if was_waiting:
        try:
            state.runs.update_harness_state(requested.run_id, {})
        except KeyError:
            pass
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
