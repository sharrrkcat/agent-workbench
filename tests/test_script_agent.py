import asyncio
import base64
from pathlib import Path

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.attachments import resolve_attachment_uri, save_attachment_from_upload
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.router import Router
from ai_workbench.core.runner import AgentRunner, CommandRunner
from ai_workbench.core.runtime import WorkbenchRuntime
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.llm_profile import LLMProfileSchema, ProviderProfileSchema
from ai_workbench.core.schema.message import ImageGalleryPayload, ImagePayload, RichContentPayload
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.settings import AppSettingsStore
from ai_workbench.core.knowledge_store import EmbeddingModelProfile, KnowledgeBase, MemoryKnowledgeStore
from ai_workbench.core.storage_maintenance import scan_orphan_attachments
from ai_workbench.core.stores import AgentConfigStore, LLMProfileStore, MessageStore, ProviderProfileStore, RunEventStore, RunStore, SessionStore
from tests.test_prompt_agent_execution import FakeLLMRuntime, FakeStreamingLLMRuntime, run


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
        self.llm_profiles = LLMProfileStore()
        self.provider_profiles = ProviderProfileStore()
        self.agent_configs = AgentConfigStore()
        self.knowledge = MemoryKnowledgeStore()
        self.knowledge.engine = object()
        self.app_settings = AppSettingsStore()
        self.app_settings.patch({"auto_generate_session_titles": False})
        self.llm = llm or FakeLLMRuntime(response="llm reply")
        self.router = Router(agent_registry=self.agents, command_registry=commands)
        self.command_runner = CommandRunner(
            command_registry=commands,
            runtime_registry=self.runtimes,
            run_store=self.runs,
            message_store=self.messages,
            event_bus=self.events,
            capability_registry=capabilities,
        )
        self.agent_runner = AgentRunner(
            agent_registry=self.agents,
            run_store=self.runs,
            message_store=self.messages,
            event_bus=self.events,
            llm_runtime=self.llm,
            session_store=self.sessions,
            runtime_registry=self.runtimes,
            capability_registry=capabilities,
            llm_profile_store=self.llm_profiles,
            provider_profile_store=self.provider_profiles,
            agent_config_store=self.agent_configs,
            app_settings_store=self.app_settings,
            knowledge_store=self.knowledge,
            knowledge_model_backend=object(),
        )
        self.runtime = WorkbenchRuntime(
            router=self.router,
            command_runner=self.command_runner,
            agent_runner=self.agent_runner,
        )


def script_agent_schema(agent_id: str, entry: str, unload: str = "manual", capabilities: list[str] | None = None) -> AgentSchema:
    return AgentSchema.model_validate(
        {
            "id": agent_id,
            "name": agent_id,
            "type": "script",
            "entry": entry,
            "capabilities": capabilities or [],
            "actions": [{"id": "default"}],
            "context_policy": {"mode": "current_message"},
            "model_lifecycle": {"load": "on_demand", "unload": unload, "unload_failure": "warn"},
        }
    )


def write_script_agent(tmp_path: Path, agent_id: str, code: str, entry: str = "agent.py", unload: str = "manual", capabilities: list[str] | None = None) -> AgentRegistry:
    agent_dir = tmp_path / agent_id
    agent_dir.mkdir()
    (agent_dir / entry).write_text(code, encoding="utf-8")
    registry = AgentRegistry()
    registry.register(script_agent_schema(agent_id, entry, unload=unload, capabilities=capabilities), agent_dir=agent_dir)
    return registry


def configure_llm_profile(fixture: ScriptRuntimeFixture, supports_streaming: bool = True):
    provider = fixture.provider_profiles.create(
        ProviderProfileSchema(id="provider", name="Studio", provider="lm_studio", base_url="http://studio/v1")
    )
    profile = fixture.llm_profiles.create(
        LLMProfileSchema(
            id="profile",
            alias="p",
            name="P",
            provider_profile_id=provider.id,
            model_id="model-a",
            supports_streaming=supports_streaming,
        )
    )
    session = fixture.sessions.create_session(title="Lifecycle lab test")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    return fixture.sessions.get_session(session.session_id)


def bind_script_test_kb(fixture: ScriptRuntimeFixture, session_id: str):
    profile = fixture.knowledge.create_embedding_profile(
        EmbeddingModelProfile(name="Test Embeddings", alias="test", model_path="embeddings/test")
    )
    kb = fixture.knowledge.create_knowledge_base(KnowledgeBase(name="Script KB", embedding_model_profile_id=profile.id))
    fixture.knowledge.replace_session_bindings(session_id, [kb.id])
    return kb


def test_script_agent_manifest_loads() -> None:
    agents = AgentRegistry()
    agents.load_from_directory(ROOT / "agents")

    agent = agents.get("echo_script")

    assert agent.type == "script"
    assert agent.entry == "agent.py"


def test_script_lifecycle_lab_manifest_loads() -> None:
    agents = AgentRegistry()
    agents.load_from_directory(ROOT / "agents")

    agent = agents.get("script_lifecycle_lab")

    assert agent.type == "script"
    assert agent.entry == "agent.py"
    assert "llm" in agent.capabilities
    assert {action.id for action in agent.actions} == {"default", "steps", "hidden_json", "public_stream"}


def test_script_agent_with_llm_defaults_to_no_knowledge(monkeypatch, tmp_path: Path) -> None:
    agents = write_script_agent(
        tmp_path,
        "script_llm_no_kb",
        "async def run(ctx):\n    return await ctx.llm.text(system='sys', user=ctx.input.text)\n",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=agents, llm=FakeLLMRuntime(response="script reply"))
    session = configure_llm_profile(fixture)
    bind_script_test_kb(fixture, session.session_id)

    def fail_search(**kwargs):
        raise AssertionError("search should not be called")

    monkeypatch.setattr("ai_workbench.core.knowledge_context.search_knowledge", fail_search)

    result = run(fixture.runtime.handle_input(session, "@script_llm_no_kb hello"))
    metadata = fixture.runs.get_run(result.run_id).metadata

    assert result.success is True
    assert "Retrieved Knowledge" not in fixture.llm.calls[0]["messages"][0]["content"]
    assert metadata["knowledge_context"]["reason"] == "agent_disabled"


def test_script_agent_override_enabled_injects_knowledge_for_text_json_and_stream(monkeypatch, tmp_path: Path) -> None:
    agents = write_script_agent(
        tmp_path,
        "script_llm_kb",
        "\n".join(
            [
                "async def run(ctx):",
                "    if ctx.input.text == 'json':",
                "        data = await ctx.llm.json(system='sys', user='json')",
                "        return data.get('value', '')",
                "    if ctx.input.text == 'stream':",
                "        text = ''",
                "        async for chunk in ctx.llm.stream(system='sys', user='stream'):",
                "            text += chunk.text",
                "        return text",
                "    return await ctx.llm.text(system='sys', user=ctx.input.text)",
            ]
        ),
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=agents, llm=FakeLLMRuntime(response='{"value":"ok"}'))
    fixture.agent_configs.set_config("script_llm_kb", runtime={"knowledge_context_mode": "enabled"})
    session = configure_llm_profile(fixture, supports_streaming=False)
    kb = bind_script_test_kb(fixture, session.session_id)

    def fake_search(**kwargs):
        return {
            "query": kwargs["query"],
            "results": [
                {
                    "rank": 1,
                    "chunk_id": "chunk-1",
                    "knowledge_base_id": kb.id,
                    "source_id": "source-1",
                    "title": "Script Spec",
                    "heading_path": "",
                    "content": "Script knowledge.",
                    "truncated": False,
                    "rrf_score": 1.0,
                }
            ],
            "debug": {"warnings": []},
        }

    monkeypatch.setattr("ai_workbench.core.knowledge_context.search_knowledge", fake_search)

    run(fixture.runtime.handle_input(session, "@script_llm_kb hello"))
    run(fixture.runtime.handle_input(session, "@script_llm_kb json"))
    run(fixture.runtime.handle_input(session, "@script_llm_kb stream"))

    assert len(fixture.llm.calls) == 3
    assert all("Script knowledge." in call["messages"][0]["content"] for call in fixture.llm.calls)
    assert all(fixture.runs.get_run(run_item.run_id).metadata.get("knowledge_context", {}).get("injected") is not False for run_item in fixture.runs.list_runs(session.session_id))


def test_script_agent_empty_and_silent_query_skip_knowledge(monkeypatch, tmp_path: Path) -> None:
    agents = write_script_agent(
        tmp_path,
        "script_llm_empty_kb",
        "async def run(ctx):\n    return await ctx.llm.text(system='sys', user='hello')\n",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=agents, llm=FakeLLMRuntime(response="ok"))
    fixture.agent_configs.set_config("script_llm_empty_kb", runtime={"knowledge_context_mode": "enabled"})
    session = configure_llm_profile(fixture)
    bind_script_test_kb(fixture, session.session_id)

    def fail_search(**kwargs):
        raise AssertionError("search should not be called")

    monkeypatch.setattr("ai_workbench.core.knowledge_context.search_knowledge", fail_search)

    result = run(
        fixture.agent_runner.run(
            "script_llm_empty_kb",
            "default",
            "",
            session.session_id,
            create_user_message=False,
            is_silent_submission=True,
        )
    )

    assert result.success is True
    assert fixture.runs.get_run(result.run_id).metadata["knowledge_context"]["reason"] == "empty_query"


def test_script_lifecycle_lab_steps_completes_without_llm(monkeypatch) -> None:
    async def fast_sleep(seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    fixture = ScriptRuntimeFixture(llm=FakeLLMRuntime(response="should not be called"))
    session = fixture.sessions.create_session(title="Lifecycle lab LLM test")

    result = run(fixture.runtime.handle_input(session, "@script_lifecycle_lab:steps inspect lifecycle"))
    messages = fixture.messages.list_messages(session.session_id)
    steps = fixture.runs.list_steps(result.run_id)

    assert result.success is True
    assert fixture.llm.calls == []
    assert messages[-1].output_type == "markdown"
    assert messages[-1].content == (
        "# Step Test Complete\n\n"
        "- Input: inspect lifecycle\n"
        "- Steps: 4\n"
        "- Simulated work: about 6.5 seconds"
    )
    assert len([message for message in messages if message.role == "assistant" and message.run_id == result.run_id]) == 1
    lab_steps = [step for step in steps if step.label in {"Prepare input", "Simulate data read", "Simulate processing", "Render final report"}]
    assert [step.label for step in lab_steps] == [
        "Prepare input",
        "Simulate data read",
        "Simulate processing",
        "Render final report",
    ]
    assert [step.status.value for step in lab_steps] == ["completed"] * 4
    assert [step.message for step in lab_steps] == [
        "Capturing user input.",
        "Pretending to read local data.",
        "Processing the input.",
        "Building final markdown.",
    ]
    running_step = next(step for step in steps if step.label == "Running script")
    assert {step.parent_step_id for step in lab_steps} == {running_step.step_id}


def test_script_lifecycle_lab_hidden_json_uses_internal_stream_without_public_delta() -> None:
    fixture = ScriptRuntimeFixture(
        llm=FakeStreamingLLMRuntime(
            chunks=[
                "```json\n",
                '{"title":"Lifecycle Lab","summary":"A script runtime test.",',
                '"features":["Steps","Internal stream"],"risks":["Bad JSON"],"next_steps":["Run strict checks"]}',
                "\n```",
            ]
        )
    )
    session = configure_llm_profile(fixture, supports_streaming=True)

    result = run(fixture.runtime.handle_input(session, "@script_lifecycle_lab:hidden_json test brief"))
    message = fixture.messages.list_messages(session.session_id)[-1]
    events = fixture.events.list_events()

    assert result.success is True
    assert fixture.llm.calls[0]["stream"] is True
    assert [event.type for event in events].count("message_delta") == 0
    assert message.output_type == "markdown"
    assert message.content == (
        "# Lifecycle Lab\n\n"
        "## Summary\nA script runtime test.\n\n"
        "## Features\n- Steps\n- Internal stream\n\n"
        "## Risks\n- Bad JSON\n\n"
        "## Next steps\n- Run strict checks"
    )
    assert "```json" not in message.content
    assert '"features"' not in message.content
    running_step = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Running script")
    custom_steps = [step for step in fixture.runs.list_steps(result.run_id) if step.label in {"Build extraction prompt", "LLM extracts structured JSON", "Parse JSON", "Normalize fields", "Render final markdown"}]
    assert custom_steps
    assert {step.parent_step_id for step in custom_steps} == {running_step.step_id}


def test_script_lifecycle_lab_hidden_json_parse_error_returns_friendly_markdown() -> None:
    fixture = ScriptRuntimeFixture(llm=FakeStreamingLLMRuntime(chunks=["not json"]))
    session = configure_llm_profile(fixture, supports_streaming=True)

    result = run(fixture.runtime.handle_input(session, "@script_lifecycle_lab:hidden_json test brief"))
    message = fixture.messages.list_messages(session.session_id)[-1]
    parse_step = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Parse JSON")

    assert result.success is True
    assert parse_step.status.value == "failed"
    assert message.output_type == "markdown"
    assert message.content == (
        "# JSON extraction failed\n\n"
        "The model response could not be parsed as JSON."
    )


def test_script_lifecycle_lab_public_stream_writes_public_deltas_without_duplicate_message() -> None:
    chunks = ["First paragraph.\n\n", "Second paragraph.", "\n\nThird paragraph."]
    fixture = ScriptRuntimeFixture(llm=FakeStreamingLLMRuntime(chunks=chunks))
    session = configure_llm_profile(fixture, supports_streaming=True)

    result = run(fixture.runtime.handle_input(session, "@script_lifecycle_lab:public_stream lifecycle streaming"))
    messages = fixture.messages.list_messages(session.session_id)
    message = messages[-1]
    events = fixture.events.list_events()
    stream_step = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Stream response to chat")

    assert result.success is True
    assert fixture.llm.calls[0]["stream"] is True
    assert [event.type for event in events].count("message_delta") == len(chunks)
    assert [event.type for event in events].count("message_updated") == 0
    assert [event.payload.get("delta") for event in events if event.type == "message_delta"] == chunks
    assert [event.payload.get("seq") for event in events if event.type == "message_delta"] == [1, 2, 3]
    assert {event.message_id for event in events if event.type == "message_delta"} == {message.message_id}
    completed = [event for event in events if event.type == "message_completed"]
    assert len(completed) == 1
    assert completed[0].payload["seq"] == 4
    assert completed[0].message_id == message.message_id
    assert message.output_type == "markdown"
    assert message.content == "".join(chunks)
    assert stream_step.status.value == "completed"
    running_step = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Running script")
    assert stream_step.parent_step_id == running_step.step_id
    assert next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Prepare streaming response").parent_step_id == running_step.step_id
    assert next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Finalize").parent_step_id == running_step.step_id
    assert len([item for item in messages if item.role == "assistant" and item.run_id == result.run_id]) == 1


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

    assert messages[-1].role == "assistant"
    assert messages[-1].content == "aGVsbG8="
    assert messages[-1].agent_id == "echo_script"
    assert messages[-1].action_id == "default"
    assert messages[-1].run_id == result.run_id
    assert messages[-1].speaker_type == "agent"
    assert messages[-1].speaker_id == "echo_script"
    assert messages[-1].speaker_name == "Echo Script Agent"
    assert messages[-1].origin == "agent_reply"


def test_script_agent_step_emits_run_step_event() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session()

    run(fixture.runtime.handle_input(session, "@echo_script hello"))

    step_events = [event for event in fixture.events.list_events() if event.type == "run_step_created"]
    assert [event.payload["step"]["label"] for event in step_events] == [
        "Resolving agent",
        "Starting script",
        "Running script",
        "encoding",
        "Saving response",
        "Cleanup",
    ]
    running_step = next(event.payload["step"] for event in step_events if event.payload["step"]["label"] == "Running script")
    encoding_step = next(event.payload["step"] for event in step_events if event.payload["step"]["label"] == "encoding")
    saving_step = next(event.payload["step"] for event in step_events if event.payload["step"]["label"] == "Saving response")
    cleanup_step = next(event.payload["step"] for event in step_events if event.payload["step"]["label"] == "Cleanup")
    assert encoding_step["parent_step_id"] == running_step["step_id"]
    assert saving_step["parent_step_id"] is None
    assert cleanup_step["parent_step_id"] is None


def test_script_agent_emits_placeholder_before_steps_and_binds_run_id() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@echo_script hello"))
    events = fixture.events.list_events()
    started = next(event for event in events if event.type == "message_started")
    first_step_index = next(index for index, event in enumerate(events) if event.type == "run_step_created")
    started_index = events.index(started)
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert started_index < first_step_index
    assert started.run_id == result.run_id
    assert started.message_id == message.message_id
    assert message.run_id == result.run_id
    assert fixture.runs.get_run(result.run_id).metadata["message_id"] == message.message_id


def test_script_agent_failure_reuses_placeholder_and_preserves_steps(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "bad_script",
        "async def run(ctx):\n"
        "    async with ctx.step('before fail'):\n"
        "        raise RuntimeError('script exploded')\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@bad_script hello"))
    messages = fixture.messages.list_messages(session.session_id)
    steps = fixture.runs.list_steps(result.run_id)

    assert result.success is False
    assert len([message for message in messages if message.run_id == result.run_id]) == 1
    assert messages[-1].output_type == "error"
    running_step = next(step for step in steps if step.label == "Running script")
    before_fail = next(step for step in steps if step.label == "before fail")
    assert before_fail.parent_step_id == running_step.step_id
    assert before_fail.status.value == "failed"
    assert any(event.type == "run_step_updated" for event in fixture.events.list_events())


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


def test_script_agent_success_creates_default_run_steps() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@echo_script hello"))
    steps = fixture.runs.list_steps(result.run_id)

    assert "Starting script" in [step.label for step in steps]
    assert "Running script" in [step.label for step in steps]
    assert "Saving response" in [step.label for step in steps]
    running_step = next(step for step in steps if step.label == "Running script")
    encoding_step = next(step for step in steps if step.label == "encoding")
    saving_step = next(step for step in steps if step.label == "Saving response")
    cleanup_step = next(step for step in steps if step.label == "Cleanup")
    assert encoding_step.parent_step_id == running_step.step_id
    assert saving_step.parent_step_id is None
    assert cleanup_step.parent_step_id is None


def test_script_agent_exception_marks_running_script_step_failed(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "bad_script",
        "async def run(ctx):\n    raise RuntimeError('script exploded')\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@bad_script hello"))
    running = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Running script")

    assert running.status.value == "failed"
    assert running.error_message == "script exploded"


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


def test_script_agent_without_llm_does_not_after_run_unload(tmp_path: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_workbench.core.script.unload_model_for_profile", lambda **kwargs: calls.append(kwargs) or {"ok": True, "unloaded": [], "errors": []})
    registry = write_script_agent(
        tmp_path,
        "no_llm_after_run",
        "async def run(ctx):\n"
        "    await ctx.reply_text(ctx.input.text)\n",
        unload="after_run",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@no_llm_after_run hello"))

    assert result.success is True
    assert calls == []
    assert "llm_unload" not in fixture.runs.get_run(result.run_id).metadata


def test_script_agent_after_run_unloads_when_llm_used(tmp_path: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_workbench.core.script.unload_model_for_profile", lambda **kwargs: calls.append(kwargs) or {"ok": True, "provider": "lm_studio", "provider_profile_id": kwargs["provider_profile_id"], "model_id": kwargs["model_id"], "unloaded": [], "errors": []})
    refresh_calls = []
    monkeypatch.setattr(
        "ai_workbench.core.script.refresh_provider_status_for_profile",
        lambda provider_profile_store, llm_profile_store, provider_profile_id: refresh_calls.append(provider_profile_id)
        or {"provider_profile_id": provider_profile_id, "reachable": True, "status": "MODEL_NOT_LOADED", "models": []},
    )
    registry = write_script_agent(
        tmp_path,
        "llm_after_run_script",
        "async def run(ctx):\n"
        "    generated = await ctx.llm.generate(prompt=ctx.input.text)\n"
        "    await ctx.reply_text(generated.data)\n",
        unload="after_run",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FakeLLMRuntime(response="generated"))
    provider = fixture.provider_profiles.create(ProviderProfileSchema(id="provider", name="Studio", provider="lm_studio", base_url="http://studio/v1"))
    profile = fixture.llm_profiles.create(LLMProfileSchema(id="profile", alias="p", name="P", provider_profile_id=provider.id, model_id="model-a"))
    session = fixture.sessions.create_session()
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@llm_after_run_script hello"))
    cleanup_step = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Cleanup")
    metadata = fixture.runs.get_run(result.run_id).metadata

    assert result.success is True
    assert calls[0]["provider_profile_id"] == provider.id
    assert calls[0]["model_profile_id"] == profile.id
    assert calls[0]["model_id"] == "model-a"
    assert metadata["llm"]["model_profile_name"] == "P"
    assert metadata["llm"]["requested_model_id"] == "model-a"
    assert metadata["llm"]["actual_model_id"] == "model-a"
    assert metadata["llm_unload"]["ok"] is True
    assert metadata["llm_unload"]["status_refresh_ok"] is True
    assert cleanup_step.message == "Unloaded local LLM: P"
    assert refresh_calls == [provider.id]
    event = next(event for event in fixture.events.list_events() if event.type == "llm_provider_status_updated")
    assert event.payload["provider"]["provider_profile_id"] == provider.id


def test_ctx_llm_unload_model_refreshes_provider_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ai_workbench.core.script.unload_model_for_profile",
        lambda **kwargs: {
            "ok": True,
            "provider": "lm_studio",
            "provider_profile_id": kwargs["provider_profile_id"],
            "model_id": kwargs["model_id"],
            "unloaded": [],
            "errors": [],
        },
    )
    refresh_calls = []
    monkeypatch.setattr(
        "ai_workbench.core.script.refresh_provider_status_for_profile",
        lambda provider_profile_store, llm_profile_store, provider_profile_id: refresh_calls.append(provider_profile_id)
        or {"provider_profile_id": provider_profile_id, "reachable": True, "status": "MODEL_NOT_LOADED", "models": []},
    )
    registry = write_script_agent(
        tmp_path,
        "manual_unload_script",
        "async def run(ctx):\n"
        "    result = await ctx.llm.unload_model()\n"
        "    await ctx.reply_json(result.data)\n",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    provider = fixture.provider_profiles.create(ProviderProfileSchema(id="provider", name="Studio", provider="lm_studio", base_url="http://studio/v1"))
    profile = fixture.llm_profiles.create(LLMProfileSchema(id="profile", alias="p", name="P", provider_profile_id=provider.id, model_id="model-a"))
    session = fixture.sessions.create_session()
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@manual_unload_script hello"))
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert message.content["status_refresh"]["ok"] is True
    assert fixture.runs.get_run(result.run_id).metadata["llm_unload"]["ok"] is True
    unload_step = next(step for step in fixture.runs.list_steps(result.run_id) if step.label == "Unload model")
    assert unload_step.message == "Unloaded local LLM: P"
    assert refresh_calls == [provider.id]
    event = next(event for event in fixture.events.list_events() if event.type == "llm_provider_status_updated")
    assert event.payload["provider"]["provider_profile_id"] == provider.id


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


def test_ctx_llm_stream_can_be_consumed_without_public_delta(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "llm_stream_internal_script",
        "async def run(ctx):\n"
        "    parts = []\n"
        "    async for chunk in ctx.llm.stream(system='System.', user=ctx.input.text):\n"
        "        parts.append(chunk.text)\n"
        "    await ctx.reply_text(''.join(parts).upper())\n",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FakeStreamingLLMRuntime(chunks=["hel", "lo"]))
    provider = fixture.provider_profiles.create(ProviderProfileSchema(id="provider", name="Studio", provider="lm_studio", base_url="http://studio/v1"))
    profile = fixture.llm_profiles.create(LLMProfileSchema(id="profile", alias="p", name="P", provider_profile_id=provider.id, model_id="model-a", supports_streaming=True))
    session = fixture.sessions.create_session()
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@llm_stream_internal_script hello"))

    assert result.success is True
    assert fixture.messages.list_messages(session.session_id)[-1].content == "HELLO"
    assert [event.type for event in fixture.events.list_events()].count("message_delta") == 0
    assert fixture.llm.calls[0]["stream"] is True


def test_ctx_output_write_delta_updates_script_placeholder(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "output_delta_script",
        "async def run(ctx):\n"
        "    await ctx.output.write_delta('hel')\n"
        "    await ctx.output.write_delta('lo')\n"
        "    await ctx.output.finish()\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@output_delta_script hello"))
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert message.run_id == result.run_id
    assert message.content == "hello"
    events = fixture.events.list_events()
    assert [event.type for event in events].count("message_delta") == 2
    assert [event.type for event in events].count("message_updated") == 0
    assert [event.payload.get("seq") for event in events if event.type == "message_delta"] == [1, 2]
    assert {event.message_id for event in events if event.type == "message_delta"} == {message.message_id}
    assert [event.payload.get("seq") for event in events if event.type == "message_completed"] == [3]


def test_ctx_llm_stream_to_output_writes_public_deltas(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "llm_stream_output_script",
        "async def run(ctx):\n"
        "    await ctx.llm.stream_to_output(system='System.', user=ctx.input.text, output_type='markdown')\n",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FakeStreamingLLMRuntime(chunks=["hel", "lo"]))
    provider = fixture.provider_profiles.create(ProviderProfileSchema(id="provider", name="Studio", provider="lm_studio", base_url="http://studio/v1"))
    profile = fixture.llm_profiles.create(LLMProfileSchema(id="profile", alias="p", name="P", provider_profile_id=provider.id, model_id="model-a", supports_streaming=True))
    session = fixture.sessions.create_session()
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@llm_stream_output_script hello"))
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert message.content == "hello"
    assert message.output_type == "markdown"
    events = fixture.events.list_events()
    assert [event.type for event in events].count("message_delta") == 2
    assert [event.type for event in events].count("message_updated") == 0
    assert [event.payload.get("seq") for event in events if event.type == "message_delta"] == [1, 2]
    assert {event.message_id for event in events if event.type == "message_delta"} == {message.message_id}
    assert [event.payload.get("seq") for event in events if event.type == "message_completed"] == [3]


def test_ctx_llm_stream_to_output_deltas_are_not_persisted_by_default(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "llm_stream_output_script",
        "async def run(ctx):\n"
        "    await ctx.llm.stream_to_output(system='System.', user=ctx.input.text, output_type='markdown')\n",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FakeStreamingLLMRuntime(chunks=["hel", "lo"]))
    fixture.events.run_event_store = RunEventStore()
    fixture.events.app_settings_store = AppSettingsStore()
    provider = fixture.provider_profiles.create(ProviderProfileSchema(id="provider", name="Studio", provider="lm_studio", base_url="http://studio/v1"))
    profile = fixture.llm_profiles.create(LLMProfileSchema(id="profile", alias="p", name="P", provider_profile_id=provider.id, model_id="model-a", supports_streaming=True))
    session = fixture.sessions.create_session()
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@llm_stream_output_script hello"))
    message = fixture.messages.list_messages(session.session_id)[-1]
    emitted = [event.type for event in fixture.events.list_events() if event.run_id == result.run_id]
    persisted = fixture.events.run_event_store.list_events(result.run_id)

    assert result.success is True
    assert message.content == "hello"
    assert "message_delta" in emitted
    assert "message_completed" in emitted
    assert "message_delta" not in [event.type for event in persisted]
    assert "message_completed" in [event.type for event in persisted]


def test_ctx_llm_stream_to_output_failure_completes_partial_message(tmp_path: Path) -> None:
    class FailsAfterChunk(FakeStreamingLLMRuntime):
        async def chat_stream(self, messages, model_config=None):
            self.calls.append({"messages": messages, "model_config": model_config or {}, "stream": True})
            yield "partial "
            yield "answer"
            raise RuntimeError("stream broke")

    registry = write_script_agent(
        tmp_path,
        "llm_stream_output_failure_script",
        "async def run(ctx):\n"
        "    await ctx.llm.stream_to_output(system='System.', user=ctx.input.text, output_type='markdown')\n",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FailsAfterChunk())
    provider = fixture.provider_profiles.create(ProviderProfileSchema(id="provider", name="Studio", provider="lm_studio", base_url="http://studio/v1"))
    profile = fixture.llm_profiles.create(LLMProfileSchema(id="profile", alias="p", name="P", provider_profile_id=provider.id, model_id="model-a", supports_streaming=True))
    session = fixture.sessions.create_session()
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@llm_stream_output_failure_script hello"))
    message = fixture.messages.list_messages(session.session_id)[-1]
    events = fixture.events.list_events()

    assert result.success is False
    assert fixture.runs.get_run(result.run_id).status == RunStatus.FAILED
    assert message.content == "partial answer"
    assert message.output_type == "markdown"
    assert message.metadata["success"] is False
    assert [event.payload.get("seq") for event in events if event.type == "message_delta"] == [1, 2]
    assert [event.payload.get("seq") for event in events if event.type == "message_completed"] == [3]
    assert [event.type for event in events].count("message_updated") == 0


def test_ctx_llm_stream_falls_back_to_single_chunk_when_profile_streaming_disabled(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "llm_stream_fallback_script",
        "async def run(ctx):\n"
        "    parts = []\n"
        "    async for chunk in ctx.llm.stream(system='System.', user=ctx.input.text):\n"
        "        parts.append(chunk.text)\n"
        "    await ctx.reply_text('|'.join(parts))\n",
        capabilities=["llm"],
    )
    fixture = ScriptRuntimeFixture(agents=registry, llm=FakeLLMRuntime(response="single"))
    provider = fixture.provider_profiles.create(ProviderProfileSchema(id="provider", name="Studio", provider="lm_studio", base_url="http://studio/v1"))
    profile = fixture.llm_profiles.create(LLMProfileSchema(id="profile", alias="p", name="P", provider_profile_id=provider.id, model_id="model-a", supports_streaming=False))
    session = fixture.sessions.create_session()
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@llm_stream_fallback_script hello"))

    assert result.success is True
    assert fixture.messages.list_messages(session.session_id)[-1].content == "single"
    assert fixture.llm.calls[0]["stream"] is False


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


def test_script_agent_sees_and_reads_input_attachments(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    stored = save_attachment_from_upload("config.yaml", "application/yaml", b"id: chat\n  enabled: true\n")
    registry = write_script_agent(
        tmp_path,
        "attachment_reader",
        "async def run(ctx):\n"
        "    assert len(ctx.input.attachments) == 1\n"
        "    payload = ctx.read_attachment_text(ctx.input.attachments[0])\n"
        "    await ctx.reply_file_content(**payload)\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@attachment_reader", attachments=[stored]))
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert message.output_type == "file_content"
    assert message.content["filename"] == "config.yaml"
    assert message.content["content"] == "id: chat\n  enabled: true\n"


def test_script_agent_save_attachment_bytes_writes_under_attachment_dir(monkeypatch, tmp_path: Path) -> None:
    attachments_dir = tmp_path / "attachments"
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(attachments_dir))
    registry = write_script_agent(
        tmp_path,
        "generated_attachment_writer",
        "async def run(ctx):\n"
        "    attachment = await ctx.save_attachment_bytes(\n"
        "        b'generated text',\n"
        "        filename='../unsafe report.txt',\n"
        "        mime_type='text/plain',\n"
        "        kind='file',\n"
        "        metadata={'source': 'test'},\n"
        "    )\n"
        "    await ctx.reply_json(attachment)\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@generated_attachment_writer create"))
    message = fixture.messages.list_messages(session.session_id)[-1]
    attachment = message.content
    path = resolve_attachment_uri(attachment["uri"])

    assert result.success is True
    assert path.is_file()
    assert path.read_bytes() == b"generated text"
    assert path.resolve().is_relative_to(attachments_dir.resolve())
    assert attachment["type"] == "file"
    assert attachment["mime_type"] == "text/plain"
    assert attachment["name"] == "unsafe_report.txt"
    assert attachment["size"] == len(b"generated text")
    assert attachment["uri"].startswith("local://attachments/")
    assert attachment["url"].startswith("/api/attachments/")
    assert attachment["metadata"] == {"source": "test"}
    assert fixture.runs.get_run(result.run_id).metadata["generated_attachments"][0]["id"] == attachment["id"]


def test_script_agent_save_attachment_base64_supports_data_url_and_image_gallery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    data_url = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")
    registry = write_script_agent(
        tmp_path,
        "generated_image_writer",
        "async def run(ctx):\n"
        f"    attachment = await ctx.save_attachment_base64({data_url!r}, filename='result.png', mime_type='image/png', kind='image')\n"
        "    await ctx.reply_images([{'url': attachment['url'], 'alt': attachment['name']}])\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@generated_image_writer create"))
    message = fixture.messages.list_messages(session.session_id)[-1]
    attachment = message.metadata["attachments"][0]

    assert result.success is True
    assert message.output_type == "image_gallery"
    assert message.content == {"images": [{"url": attachment["url"], "alt": "result.png"}]}
    assert attachment["type"] == "image"
    assert attachment["mime_type"] == "image/png"
    assert resolve_attachment_uri(attachment["uri"]).read_bytes() == b"\x89PNG\r\n\x1a\nfake"


def test_script_agent_save_attachment_base64_rejects_invalid_data(tmp_path: Path) -> None:
    registry = write_script_agent(
        tmp_path,
        "bad_generated_attachment",
        "async def run(ctx):\n"
        "    await ctx.save_attachment_base64('not-base64', filename='bad.png', mime_type='image/png', kind='image')\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@bad_generated_attachment create"))

    assert result.success is False
    assert "base64 is invalid" in result.error


def test_generated_attachment_is_linked_for_cleanup(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    registry = write_script_agent(
        tmp_path,
        "linked_generated_attachment",
        "async def run(ctx):\n"
        "    attachment = await ctx.save_attachment_bytes(b'hello', filename='hello.txt', mime_type='text/plain')\n"
        "    await ctx.reply_image(attachment['url'], alt='not really image')\n",
    )
    fixture = ScriptRuntimeFixture(agents=registry)
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@linked_generated_attachment create"))
    message = fixture.messages.list_messages(session.session_id)[-1]
    attachment = message.metadata["attachments"][0]
    path = resolve_attachment_uri(attachment["uri"])

    assert result.success is True
    assert path.exists()
    assert scan_orphan_attachments(fixture.messages)["orphan_count"] == 0


def test_echo_attachments_agent_echoes_text_image_and_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    fixture = ScriptRuntimeFixture(llm=FakeLLMRuntime(response="should not be called"))
    session = fixture.sessions.create_session(title="Echo attachment test")
    image = {
        "id": "client-image",
        "type": "image",
        "mime_type": "image/png",
        "name": "cat.png",
        "size": 5,
        "data_url": "data:image/png;base64,aGVsbG8=",
    }
    file_attachment = save_attachment_from_upload("tool.py", "text/x-python", b"def main():\n    return 'ok'\n")

    result = run(fixture.runtime.handle_input(session, "@echo_attachments hello", attachments=[image, file_attachment]))
    messages = fixture.messages.list_messages(session.session_id)

    assert result.success is True
    assert [message.output_type for message in messages[-3:]] == ["text", "image", "file_content"]
    assert messages[-3].content == "hello"
    assert messages[-2].content["url"] == image["data_url"]
    assert messages[-2].content["title"] == "cat.png"
    assert messages[-1].content["filename"] == "tool.py"
    assert messages[-1].content["language"] == "python"
    assert messages[-1].content["content"] == "def main():\n    return 'ok'\n"
    assert fixture.llm.calls == []


def test_script_agent_action_text_route_stores_raw_input_but_passes_args() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@render_test:text hello"))
    messages = fixture.messages.list_messages(session.session_id)

    assert result.success is True
    assert messages[0].role == "user"
    assert messages[0].content == "@render_test:text hello"
    assert messages[0].metadata["invocation"]["raw_text"] == "@render_test:text hello"
    assert messages[0].metadata["invocation"]["args"] == "hello"
    assert messages[-1].role == "assistant"
    assert messages[-1].content == "hello"


def test_current_agent_action_shortcut_stores_raw_input_and_route_metadata() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session(default_agent_id="render_test")

    result = run(fixture.runtime.handle_input(session, ":text hello"))
    messages = fixture.messages.list_messages(session.session_id)
    run_record = fixture.runs.get_run(result.run_id)

    assert result.success is True
    assert messages[0].role == "user"
    assert messages[0].content == ":text hello"
    assert messages[0].metadata["invocation"]["route_kind"] == "current_agent_action_shortcut"
    assert messages[0].metadata["invocation"]["resolved_agent_id"] == "render_test"
    assert messages[0].metadata["invocation"]["resolved_action_id"] == "text"
    assert messages[0].metadata["invocation"]["args"] == "hello"
    assert run_record.target_id == "render_test"
    assert run_record.action_id == "text"
    assert run_record.metadata["route_kind"] == "current_agent_action_shortcut"
    assert run_record.metadata["resolved_agent_id"] == "render_test"
    assert run_record.metadata["resolved_action_id"] == "text"
    assert messages[-1].content == "hello"
    assert {message.role for message in messages} <= {"user", "assistant"}


def test_current_agent_action_shortcut_unknown_action_does_not_fallback_to_default() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, ":form"))

    assert result.success is False
    assert "Current agent \"Chat Agent\" has no action \"form\"." in result.error
    assert fixture.runs.list_runs(session.session_id) == []
    assert fixture.messages.list_messages(session.session_id) == []


def test_render_test_image_action_returns_three_non_llm_messages() -> None:
    fixture = ScriptRuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@render_test:image 1"))
    messages = fixture.messages.list_messages(session.session_id)

    assert result.success is True
    assert [message.output_type for message in messages[1:]] == ["image", "rich_content", "image_gallery"]
    assert all("llm_resolution" not in message.metadata for message in messages[1:])


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
