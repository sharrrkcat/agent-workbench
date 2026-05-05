import asyncio
from pathlib import Path

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.router import Router
from ai_workbench.core.runner import CommandRunner
from ai_workbench.core.runtime import WorkbenchRuntime
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore


ROOT = Path(__file__).resolve().parents[1]


class RuntimeFixture:
    def __init__(self) -> None:
        agents = AgentRegistry()
        agents.load_from_directory(ROOT / "agents")

        capabilities = CapabilityRegistry()
        capabilities.load_from_directory(ROOT / "capabilities")

        commands = CommandRegistry.from_capability_registry(capabilities)

        runtimes = CapabilityRuntimeRegistry()
        runtimes.load_from_directory(ROOT / "capabilities")

        self.sessions = SessionStore()
        self.messages = MessageStore()
        self.runs = RunStore()
        self.events = EventBus()
        self.router = Router(agent_registry=agents, command_registry=commands)
        self.command_runner = CommandRunner(
            command_registry=commands,
            runtime_registry=runtimes,
            run_store=self.runs,
            message_store=self.messages,
            event_bus=self.events,
        )
        self.runtime = WorkbenchRuntime(router=self.router, command_runner=self.command_runner)


def run(coro):
    return asyncio.run(coro)


def test_base64_encode_executes_end_to_end() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/base64 hello"))

    assert result.success is True
    assert result.data == "aGVsbG8="
    assert fixture.runs.get_run(result.run_id).status == RunStatus.DONE


def test_base64_decode_executes_end_to_end() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/base64-decode aGVsbG8="))

    assert result.success is True
    assert result.data == "hello"
    assert fixture.runs.get_run(result.run_id).status == RunStatus.DONE


def test_base64_decode_invalid_input_returns_failed_result_and_run() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/base64-decode invalid!!!"))
    failed_run = fixture.runs.get_run(result.run_id)

    assert result.success is False
    assert result.error == "Invalid base64 input."
    assert failed_run.status == RunStatus.FAILED
    assert failed_run.error == "Invalid base64 input."


def test_successful_command_creates_done_run() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/base64 hello"))
    runs = fixture.runs.list_runs(session.session_id)

    assert len(runs) == 1
    assert runs[0].run_id == result.run_id
    assert runs[0].target_id == "/base64"
    assert runs[0].status == RunStatus.DONE


def test_failed_command_creates_failed_run() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/base64-decode invalid!!!"))
    runs = fixture.runs.list_runs(session.session_id)

    assert len(runs) == 1
    assert runs[0].run_id == result.run_id
    assert runs[0].target_id == "/base64-decode"
    assert runs[0].status == RunStatus.FAILED


def test_successful_command_writes_message_store() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/base64 hello"))
    messages = fixture.messages.list_messages(session.session_id)

    assert len(messages) == 1
    assert messages[0].role == "command"
    assert messages[0].command_name == "/base64"
    assert messages[0].run_id == result.run_id
    assert messages[0].content == "aGVsbG8="
    assert messages[0].output_type == "text"


def test_success_event_bus_records_started_and_done() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/base64 hello"))
    events = fixture.events.list_events()

    assert [event.type for event in events] == ["run_started", "run_done", "message_done"]
    assert events[0].run_id == result.run_id
    assert events[1].run_id == result.run_id


def test_failure_event_bus_records_started_and_failed() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/base64-decode invalid!!!"))
    events = fixture.events.list_events()

    assert [event.type for event in events] == ["run_started", "run_failed", "message_done"]
    assert events[0].run_id == result.run_id
    assert events[1].run_id == result.run_id
    assert events[1].payload == {"error": "Invalid base64 input."}


def test_command_uses_current_args_not_session_history() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()
    fixture.messages.add_message(
        session_id=session.session_id,
        role="user",
        content="this previous message should not be encoded",
    )

    result = run(fixture.runtime.handle_input(session, "/base64 hello"))

    assert result.data == "aGVsbG8="


def test_unknown_command_returns_structured_error_without_run() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/missing hello"))

    assert result.success is False
    assert result.run_id == ""
    assert result.error == "Unknown command: /missing"
    assert fixture.runs.list_runs(session.session_id) == []

