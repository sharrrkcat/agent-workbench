from pathlib import Path

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.router import Router
from ai_workbench.core.runner import AgentRunner, CommandRunner
from ai_workbench.core.runtime import WorkbenchRuntime
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore
from tests.test_prompt_agent_execution import FakeLLMRuntime, run


ROOT = Path(__file__).resolve().parents[1]


class ScriptRuntimeFixture:
    def __init__(self, agents=None, llm=None) -> None:
        self.agents = agents or AgentRegistry()
        if agents is None:
            self.agents.load_from_directory(ROOT / "agents")

        capabilities = CapabilityRegistry()
        capabilities.load_from_directory(ROOT / "capabilities")
        commands = CommandRegistry.from_capability_registry(capabilities)

        self.runtimes = CapabilityRuntimeRegistry()
        self.runtimes.load_from_directory(ROOT / "capabilities")

        self.sessions = SessionStore()
        self.messages = MessageStore()
        self.runs = RunStore()
        self.events = EventBus()
        self.llm = llm or FakeLLMRuntime(response="llm reply")
        self.router = Router(agent_registry=self.agents, command_registry=commands)
        self.command_runner = CommandRunner(
            command_registry=commands,
            runtime_registry=self.runtimes,
            run_store=self.runs,
            message_store=self.messages,
            event_bus=self.events,
        )
        self.agent_runner = AgentRunner(
            agent_registry=self.agents,
            run_store=self.runs,
            message_store=self.messages,
            event_bus=self.events,
            llm_runtime=self.llm,
            session_store=self.sessions,
            runtime_registry=self.runtimes,
        )
        self.runtime = WorkbenchRuntime(
            router=self.router,
            command_runner=self.command_runner,
            agent_runner=self.agent_runner,
        )


def script_agent_schema(agent_id: str, entry: str) -> AgentSchema:
    return AgentSchema.model_validate(
        {
            "id": agent_id,
            "name": agent_id,
            "type": "script",
            "entry": entry,
            "actions": [{"id": "default"}],
            "context_policy": {"mode": "current_message"},
            "model_lifecycle": {"load": "on_demand", "unload": "manual", "unload_failure": "warn"},
        }
    )


def write_script_agent(tmp_path: Path, agent_id: str, code: str, entry: str = "agent.py") -> AgentRegistry:
    agent_dir = tmp_path / agent_id
    agent_dir.mkdir()
    (agent_dir / entry).write_text(code, encoding="utf-8")
    registry = AgentRegistry()
    registry.register(script_agent_schema(agent_id, entry), agent_dir=agent_dir)
    return registry


def test_script_agent_manifest_loads() -> None:
    agents = AgentRegistry()
    agents.load_from_directory(ROOT / "agents")

    agent = agents.get("echo_script")

    assert agent.type == "script"
    assert agent.entry == "agent.py"


def test_echo_script_executes_through_runtime() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@echo_script hello"))

    assert result.success is True
    assert fixture.runs.get_run(result.run_id).status == RunStatus.DONE


def test_script_agent_reply_writes_agent_message() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@echo_script hello"))
    messages = fixture.messages.list_messages(session.session_id)

    assert messages[-1].role == "agent"
    assert messages[-1].content == "aGVsbG8="
    assert messages[-1].agent_id == "echo_script"
    assert messages[-1].action_id == "default"
    assert messages[-1].run_id == result.run_id


def test_script_agent_step_emits_run_step_event() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session()

    run(fixture.runtime.handle_input(session, "@echo_script hello"))

    assert [event.type for event in fixture.events.list_events()] == [
        "run_started",
        "run_step",
        "message_done",
        "run_done",
    ]
    assert fixture.events.list_events()[1].payload == {"step": "encoding"}


def test_script_agent_can_call_base64_capability() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session()

    run(fixture.runtime.handle_input(session, "@echo_script hello"))

    assert fixture.messages.list_messages(session.session_id)[-1].content == "aGVsbG8="


def test_script_agent_exception_marks_run_failed(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "bad_script",
        "async def run(ctx):\n    raise RuntimeError('script exploded')\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@bad_script hello"))
    failed_run = fixture.runs.get_run(result.run_id)

    assert result.success is False
    assert result.error == "script exploded"
    assert failed_run.status == RunStatus.FAILED


def test_script_missing_async_run_returns_structured_error(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "sync_script",
        "def run(ctx):\n    return None\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@sync_script hello"))

    assert result.success is False
    assert result.error == "script entry must export async def run(ctx)"
    assert fixture.runs.get_run(result.run_id).status == RunStatus.FAILED


def test_script_entry_cannot_escape_agent_directory(tmp_path: Path) -> None:
    agent_dir = tmp_path / "escape_script"
    agent_dir.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("async def run(ctx):\n    await ctx.reply('bad')\n", encoding="utf-8")
    registry = AgentRegistry()
    registry.register(script_agent_schema("escape_script", "../outside.py"), agent_dir=agent_dir)
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@escape_script hello"))

    assert result.success is False
    assert result.error == "script entry must stay inside the agent directory"


def test_ctx_ask_marks_run_waiting_and_sets_session_waiting_run(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "ask_script",
        "async def run(ctx):\n    await ctx.ask('Need more input?')\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@ask_script hello"))
    waiting_run = fixture.runs.get_run(result.run_id)
    updated_session = fixture.sessions.get_session(session.session_id)

    assert result.success is False
    assert result.error == "Waiting for user input."
    assert waiting_run.status == RunStatus.WAITING_FOR_USER
    assert updated_session.waiting_run_id == result.run_id


def test_script_agent_can_call_llm_generate(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "llm_script",
        "async def run(ctx):\n"
        "    generated = await ctx.llm.generate(prompt=ctx.input.text)\n"
        "    await ctx.reply(generated.data)\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FakeLLMRuntime(response="generated"))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@llm_script hello"))

    assert result.success is True
    assert fixture.messages.list_messages(session.session_id)[-1].content == "generated"

