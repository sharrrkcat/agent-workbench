import asyncio
from pathlib import Path

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.router import Router
from ai_workbench.core.runner import AgentRunner, CommandRunner
from ai_workbench.core.runtime import WorkbenchRuntime
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore


ROOT = Path(__file__).resolve().parents[1]


class FakeLLMRuntime:
    def __init__(self, response: str = "fake response", fail: bool = False, unload_result=None) -> None:
        self.response = response
        self.fail = fail
        self.unload_result = unload_result or {"success": True}
        self.calls = []
        self.unload_calls = []

    def chat(self, messages, model_config=None, stream=False):
        self.calls.append({"messages": messages, "model_config": model_config or {}, "stream": stream})
        if self.fail:
            raise RuntimeError("LLM failed")
        return self.response

    def generate(self, prompt, model_config=None, stream=False):
        self.calls.append({"prompt": prompt, "model_config": model_config or {}, "stream": stream})
        if self.fail:
            raise RuntimeError("LLM failed")
        return self.response

    def unload(self, model_config=None):
        self.unload_calls.append({"model_config": model_config or {}})
        return self.unload_result


class PromptRuntimeFixture:
    def __init__(self, llm=None) -> None:
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
        self.llm = llm or FakeLLMRuntime()
        self.router = Router(agent_registry=agents, command_registry=commands)
        self.command_runner = CommandRunner(
            command_registry=commands,
            runtime_registry=runtimes,
            run_store=self.runs,
            message_store=self.messages,
            event_bus=self.events,
        )
        self.agent_runner = AgentRunner(
            agent_registry=agents,
            run_store=self.runs,
            message_store=self.messages,
            event_bus=self.events,
            llm_runtime=self.llm,
            session_store=self.sessions,
            runtime_registry=runtimes,
        )
        self.runtime = WorkbenchRuntime(
            router=self.router,
            command_runner=self.command_runner,
            agent_runner=self.agent_runner,
        )


def run(coro):
    return asyncio.run(coro)


def test_translate_agent_executes_and_writes_agent_message() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@translate 你好"))
    messages = fixture.messages.list_messages(session.session_id)

    assert result.success is True
    assert result.data == "hello"
    assert len(messages) == 2
    assert messages[1].role == "assistant"
    assert messages[1].agent_id == "translate"
    assert messages[1].action_id == "default"
    assert messages[1].content == "hello"


def test_plain_text_routes_to_default_agent_and_executes() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="chat reply"))
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert result.data == "chat reply"
    assert fixture.runs.get_run(result.run_id).target_id == "chat"


def test_chat_agent_session_context_includes_history() -> None:
    llm = FakeLLMRuntime(response="chat reply")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.messages.add_message(session_id=session.session_id, role="user", content="old user")
    fixture.messages.add_message(session_id=session.session_id, role="assistant", content="old assistant", agent_id="chat")

    run(fixture.runtime.handle_input(session, "new user"))
    sent = llm.calls[0]["messages"]

    assert sent[0]["role"] == "system"
    assert {"role": "user", "content": "old user"} in sent
    assert {"role": "assistant", "content": "old assistant"} in sent
    assert sent[-1] == {"role": "user", "content": "new user"}


def test_chat_agent_session_context_excludes_model_change_events() -> None:
    llm = FakeLLMRuntime(response="chat reply")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.messages.add_message(
        session_id=session.session_id,
        role="system",
        content="Session model switched to My Qwen3",
        output_type="event",
        metadata={"event_type": "model_changed"},
    )

    run(fixture.runtime.handle_input(session, "new user"))
    sent = llm.calls[0]["messages"]

    assert {"role": "system", "content": "Session model switched to My Qwen3"} not in sent
    assert sent[-1] == {"role": "user", "content": "new user"}


def test_translate_current_message_context_excludes_history() -> None:
    llm = FakeLLMRuntime(response="hello")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session()
    fixture.messages.add_message(session_id=session.session_id, role="user", content="unrelated history")

    run(fixture.runtime.handle_input(session, "@translate 你好"))
    sent = llm.calls[0]["messages"]

    assert {"role": "user", "content": "unrelated history"} not in sent
    assert sent[-1] == {"role": "user", "content": "你好"}


def test_prompt_agent_success_creates_done_run() -> None:
    fixture = PromptRuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@chat hello"))
    prompt_run = fixture.runs.get_run(result.run_id)

    assert prompt_run.kind == "agent"
    assert prompt_run.status == RunStatus.DONE


def test_prompt_agent_failure_marks_run_failed() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(fail=True))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@chat hello"))
    prompt_run = fixture.runs.get_run(result.run_id)

    assert result.success is False
    assert result.error == "LLM failed"
    assert prompt_run.status == RunStatus.FAILED
    assert prompt_run.error == "LLM failed"


def test_after_run_lifecycle_attempts_unload() -> None:
    llm = FakeLLMRuntime(response="hello")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@translate 你好"))

    assert result.success is True
    assert len(llm.unload_calls) == 1


def test_unload_unsupported_warn_does_not_fail_run_and_records_warning() -> None:
    llm = FakeLLMRuntime(
        response="hello",
        unload_result={"success": False, "unsupported": True, "message": "unsupported unload"},
    )
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@translate 你好"))
    prompt_run = fixture.runs.get_run(result.run_id)

    assert result.success is True
    assert prompt_run.status == RunStatus.DONE
    assert prompt_run.metadata["warnings"] == ["unsupported unload"]
    assert "run_warning" in [event.type for event in fixture.events.list_events()]


def test_selected_message_context_without_source_falls_back_stably() -> None:
    llm = FakeLLMRuntime(response="formal")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@translate:formal make this formal"))
    sent = llm.calls[0]["messages"]
    messages = fixture.messages.list_messages(session.session_id)

    assert result.success is True
    assert sent[-1] == {"role": "user", "content": "make this formal"}
    assert messages[-1].metadata["context_warnings"] == [
        "selected_message context requested without source_message_id; used current_message fallback"
    ]


def test_base64_still_executes_with_prompt_runtime_configured() -> None:
    fixture = PromptRuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/base64 hello"))

    assert result.success is True
    assert result.data == "aGVsbG8="
