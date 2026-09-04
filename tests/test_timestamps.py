from datetime import datetime

from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.schema.run import RunSchema, RunStepSchema


def test_run_and_step_timestamp_serialization_is_utc() -> None:
    run = RunSchema(run_id="run", session_id="session", kind="chat", target="chat")
    step = RunStepSchema(step_id="step", run_id="run", kind="context")

    assert run.model_dump(mode="json")["created_at"].endswith("Z")
    assert step.model_dump(mode="json")["updated_at"].endswith("Z")


def test_naive_datetime_serializes_as_utc() -> None:
    naive = datetime(2026, 5, 7, 16, 49, 0, 123000)
    run = RunSchema(
        run_id="run",
        session_id="session",
        kind="chat",
        target="chat",
        created_at=naive,
        updated_at=naive,
    )
    step = RunStepSchema(
        step_id="step",
        run_id="run",
        kind="context",
        started_at=naive,
        created_at=naive,
        updated_at=naive,
    )
    message = MessageSchema(
        message_id="message",
        session_id="session",
        role="assistant",
        parts=[{"type": "text", "text": "reply"}],
        created_at=naive,
    )

    assert run.model_dump(mode="json")["created_at"] == "2026-05-07T16:49:00.123000Z"
    assert step.model_dump(mode="json")["started_at"] == "2026-05-07T16:49:00.123000Z"
    assert message.model_dump(mode="json")["created_at"] == "2026-05-07T16:49:00.123000Z"
