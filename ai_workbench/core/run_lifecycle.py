from __future__ import annotations

from typing import Any, Optional

from ai_workbench.core.events import EventBus
from ai_workbench.core.schema.run import RunSchema, RunStatus, RunStepSchema, RunStepStatus
from ai_workbench.core.stores import RunStore


TERMINAL_STATUSES = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}


class RunLifecycle:
    def __init__(self, run_store: RunStore, event_bus: EventBus) -> None:
        self.run_store = run_store
        self.event_bus = event_bus

    def start_run(self, run_id: str, stage: str = "running", message: str = "") -> RunSchema:
        run = self.run_store.update_status(run_id, RunStatus.RUNNING, current_step=stage)
        if message:
            run = self.run_store.update_progress(run_id, stage=stage, message=message)
        self._emit_run("run_updated", run)
        return run

    def set_status(
        self,
        run_id: str,
        status: RunStatus,
        stage: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        cancel_requested: Optional[bool] = None,
    ) -> RunSchema:
        run = self.run_store.update_status(
            run_id,
            status,
            current_step=stage,
            error_code=error_code,
            error_message=error_message,
            cancel_requested=cancel_requested,
        )
        self._emit_run("run_updated", run)
        return run

    def start_step(self, run_id: str, label: str, message: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> RunStepSchema:
        step = self.run_store.create_step(run_id=run_id, label=label, message=message, metadata=metadata, status=RunStepStatus.RUNNING)
        self.update_progress(run_id, stage=label, message=message)
        self._emit_step("run_step_created", step)
        return step

    def complete_step(self, step_id: str, message: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> RunStepSchema:
        step = self.run_store.update_step(step_id, status=RunStepStatus.COMPLETED, message=message, metadata=metadata)
        self._emit_step("run_step_updated", step)
        return step

    def fail_step(self, step_id: str, error_code: Optional[str] = None, error_message: Optional[str] = None) -> RunStepSchema:
        step = self.run_store.update_step(step_id, status=RunStepStatus.FAILED, error_code=error_code, error_message=error_message)
        self._emit_step("run_step_updated", step)
        return step

    def skip_step(self, step_id: str, message: Optional[str] = None) -> RunStepSchema:
        step = self.run_store.update_step(step_id, status=RunStepStatus.SKIPPED, message=message)
        self._emit_step("run_step_updated", step)
        return step

    def update_progress(
        self,
        run_id: str,
        stage: Optional[str] = None,
        message: Optional[str] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
    ) -> RunSchema:
        run = self.run_store.update_progress(run_id, stage=stage, message=message, current=current, total=total)
        self._emit_run("run_updated", run)
        return run

    def complete_run(self, run_id: str) -> RunSchema:
        run = self.run_store.update_status(run_id, RunStatus.DONE, current_step="done")
        self._emit_run("run_completed", run)
        return run

    def fail_run(self, run_id: str, error_code: Optional[str], error_message: str) -> RunSchema:
        run = self.run_store.update_status(
            run_id,
            RunStatus.FAILED,
            current_step="failed",
            error=error_message,
            error_code=error_code,
            error_message=error_message,
        )
        self._emit_run("run_failed", run, payload={"error": error_message, "error_code": error_code})
        return run

    def request_cancel(self, run_id: str) -> RunSchema:
        run = self.run_store.update_status(run_id, RunStatus.CANCELLING, current_step="cancelling", cancel_requested=True)
        self._emit_run("run_cancel_requested", run)
        return run

    def cancel_run(self, run_id: str, message: str = "Run was cancelled.") -> RunSchema:
        run = self.run_store.update_status(
            run_id,
            RunStatus.CANCELLED,
            current_step="cancelled",
            error=message,
            error_code="RUN_CANCELLED",
            error_message=message,
            cancel_requested=True,
        )
        self._emit_run("run_cancelled", run)
        return run

    def _emit_run(self, event_type: str, run: RunSchema, payload: Optional[dict[str, Any]] = None) -> None:
        body = {"run": run.model_dump(mode="json"), **(payload or {})}
        self.event_bus.emit(event_type, session_id=run.session_id, run_id=run.run_id, payload=body)

    def _emit_step(self, event_type: str, step: RunStepSchema) -> None:
        run = self.run_store.get_run(step.run_id)
        self.event_bus.emit(event_type, session_id=run.session_id, run_id=run.run_id, payload={"step": step.model_dump(mode="json")})
