from datetime import datetime

from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.schema.run import RunSchema, RunStepSchema


def test_run_timestamp_serialization_is_utc_with_timezone() -> None:
    run = RunSchema(run_id="run", session_id="session", kind="agent", target_id="chat")

    payload = run.model_dump(mode="json")

    assert payload["created_at"].endswith("Z") or payload["created_at"].endswith("+00:00")
    assert payload["updated_at"].endswith("Z") or payload["updated_at"].endswith("+00:00")


def test_run_step_timestamp_serialization_is_utc_with_timezone() -> None:
    step = RunStepSchema(step_id="step", run_id="run", label="Working")

    payload = step.model_dump(mode="json")

    assert payload["created_at"].endswith("Z") or payload["created_at"].endswith("+00:00")
    assert payload["updated_at"].endswith("Z") or payload["updated_at"].endswith("+00:00")


def test_legacy_naive_datetime_serializes_as_utc() -> None:
    legacy = datetime(2026, 5, 7, 16, 49, 0, 123000)
    run = RunSchema(run_id="run", session_id="session", kind="agent", target_id="chat", created_at=legacy, updated_at=legacy)
    step = RunStepSchema(step_id="step", run_id="run", label="Working", started_at=legacy, created_at=legacy, updated_at=legacy)
    message = MessageSchema(message_id="message", session_id="session", role="assistant", content="", created_at=legacy)

    assert run.model_dump(mode="json")["created_at"] == "2026-05-07T16:49:00.123000Z"
    assert step.model_dump(mode="json")["started_at"] == "2026-05-07T16:49:00.123000Z"
    assert message.model_dump(mode="json")["created_at"] == "2026-05-07T16:49:00.123000Z"
