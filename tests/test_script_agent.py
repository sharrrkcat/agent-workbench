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
from ai_workbench.core.schema.message import ImageGalleryPayload, ImagePayload, RichContentPayload
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


def test_script_agent_with_dataclass_and_future_annotations_loads(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "dataclass_script",
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n\n"
        "@dataclass\n"
        "class Payload:\n"
        "    text: str\n\n"
        "async def run(ctx):\n"
        "    payload: Payload = Payload(ctx.input.text)\n"
        "    await ctx.reply_text(payload.text)\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@dataclass_script hello"))

    assert result.success is True
    assert fixture.messages.list_messages(session.session_id)[-1].content == "hello"


def test_ctx_llm_text_returns_string(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "llm_text_script",
        "async def run(ctx):\n"
        "    text = await ctx.llm.text(system='You are terse.', user=ctx.input.text)\n"
        "    await ctx.reply_text(text)\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FakeLLMRuntime(response="text reply"))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@llm_text_script hello"))

    assert result.success is True
    assert fixture.messages.list_messages(session.session_id)[-1].content == "text reply"
    assert fixture.llm.calls[0]["messages"] == [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "hello"},
    ]


def test_ctx_llm_json_returns_dict(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "llm_json_script",
        "async def run(ctx):\n"
        "    data = await ctx.llm.json(system='Return JSON.', user=ctx.input.text)\n"
        "    await ctx.reply_json(data)\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FakeLLMRuntime(response='{\"ok\": true, \"value\": 7}'))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@llm_json_script hello"))

    assert result.success is True
    message = fixture.messages.list_messages(session.session_id)[-1]
    assert message.content == {"ok": True, "value": 7}
    assert message.output_type == "json"


def test_ctx_llm_json_extracts_fenced_json(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "llm_fenced_json_script",
        "async def run(ctx):\n"
        "    data = await ctx.llm.json(system='Return JSON.', user=ctx.input.text)\n"
        "    await ctx.reply_json(data)\n",
    )
    fixture = ScriptRuntimeFixture(
        agents=registry,
        llm=FakeLLMRuntime(response='```json\n{\"answer\": \"yes\"}\n```'),
    )
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@llm_fenced_json_script hello"))

    assert result.success is True
    assert fixture.messages.list_messages(session.session_id)[-1].content == {"answer": "yes"}


def test_ctx_llm_json_invalid_json_fails_clearly(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "llm_bad_json_script",
        "async def run(ctx):\n"
        "    await ctx.llm.json(system='Return JSON.', user=ctx.input.text)\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FakeLLMRuntime(response="not json"))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@llm_bad_json_script hello"))

    assert result.success is False
    assert "LLM response did not contain valid JSON" in result.error


def test_ctx_llm_generate_accepts_system_and_user(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "llm_generate_system_script",
        "async def run(ctx):\n"
        "    generated = await ctx.llm.generate(system='System prompt.', user=ctx.input.text)\n"
        "    await ctx.reply_text(generated.data)\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FakeLLMRuntime(response="generated system"))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@llm_generate_system_script hello"))

    assert result.success is True
    assert fixture.messages.list_messages(session.session_id)[-1].content == "generated system"


def test_reply_helpers_write_expected_output_types(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "reply_helpers_script",
        "async def run(ctx):\n"
        "    await ctx.reply_text('plain')\n"
        "    await ctx.reply_markdown('**bold**')\n"
        "    await ctx.reply_json({'ok': True})\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@reply_helpers_script hello"))
    messages = fixture.messages.list_messages(session.session_id)

    assert result.success is True
    assert [(message.content, message.output_type) for message in messages[-3:]] == [
        ("plain", "text"),
        ("**bold**", "markdown"),
        ({"ok": True}, "json"),
    ]


def test_image_output_schema_accepts_supported_payloads() -> None:
    image = ImagePayload.model_validate({"url": "https://example.test/image.png", "alt": "Example"})
    gallery = ImageGalleryPayload.model_validate({"images": [image.model_dump()]})
    rich = RichContentPayload.model_validate(
        {
            "blocks": [
                {"type": "markdown", "text": "**hello**"},
                {"type": "image", "url": "https://example.test/inline.png", "caption": "Inline"},
                {"type": "text", "text": "done"},
            ]
        }
    )

    assert image.url == "https://example.test/image.png"
    assert gallery.images[0].alt == "Example"
    assert [block.type for block in rich.blocks] == ["markdown", "image", "text"]


def test_image_reply_helpers_write_expected_output_types(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "image_reply_script",
        "async def run(ctx):\n"
        "    await ctx.reply_image('https://example.test/single.png', alt='Single', title='One', caption='Caption')\n"
        "    await ctx.reply_images([\n"
        "        {'url': 'https://example.test/a.png', 'alt': 'A'},\n"
        "        {'url': 'https://example.test/b.png', 'caption': 'B caption'},\n"
        "    ])\n"
        "    await ctx.reply_blocks([\n"
        "        {'type': 'markdown', 'text': '**bold**'},\n"
        "        {'type': 'image', 'url': 'https://example.test/inline.png', 'alt': 'Inline'},\n"
        "        {'type': 'text', 'text': 'plain'},\n"
        "    ])\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@image_reply_script hello"))
    messages = fixture.messages.list_messages(session.session_id)

    assert result.success is True
    assert [message.output_type for message in messages[-3:]] == ["image", "image_gallery", "rich_content"]
    assert messages[-3].content == {
        "url": "https://example.test/single.png",
        "alt": "Single",
        "title": "One",
        "caption": "Caption",
    }
    assert messages[-2].content == {
        "images": [
            {"url": "https://example.test/a.png", "alt": "A"},
            {"url": "https://example.test/b.png", "caption": "B caption"},
        ]
    }
    assert messages[-1].content == {
        "blocks": [
            {"type": "markdown", "text": "**bold**"},
            {"type": "image", "url": "https://example.test/inline.png", "alt": "Inline"},
            {"type": "text", "text": "plain"},
        ]
    }


def test_reply_accepts_type_and_output_type_compatibility(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "reply_compat_script",
        "async def run(ctx):\n"
        "    await ctx.reply('type markdown', type='markdown')\n"
        "    await ctx.reply('output markdown', output_type='markdown')\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@reply_compat_script hello"))
    messages = fixture.messages.list_messages(session.session_id)

    assert result.success is True
    assert [message.output_type for message in messages[-2:]] == ["markdown", "markdown"]
