import asyncio
from threading import Event as ThreadingEvent
from pathlib import Path

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.attachments import save_attachment_from_upload
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.router import Router
from ai_workbench.core.runner import ActiveRunRegistry, AgentRunner, CommandRunner, _extract_llm_result, _friendly_llm_error, _normalize_stream_chunk
from ai_workbench.core.runtime import WorkbenchRuntime
from ai_workbench.core.schema.llm_profile import LLMProfileSchema, ProviderProfileSchema
from ai_workbench.core.schema.run import RunStatus, RunStepStatus
from ai_workbench.core.stores import AgentConfigStore, LLMProfileStore, MessageStore, ProviderProfileStore, RunStore, SessionStore


ROOT = Path(__file__).resolve().parents[1]
PNG_DATA_URL = "data:image/png;base64,aGVsbG8="
JPEG_DATA_URL = "data:image/jpeg;base64,aGVsbG8="


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


class FakeStreamingLLMRuntime(FakeLLMRuntime):
    def __init__(self, chunks=None, fail: bool = False) -> None:
        super().__init__(response="nonstream", fail=fail)
        self.chunks = chunks or ["hel", "lo"]
        self.stream_started = asyncio.Event()
        self.release_next = asyncio.Event()

    async def chat_stream(self, messages, model_config=None):
        self.calls.append({"messages": messages, "model_config": model_config or {}, "stream": True})
        self.stream_started.set()
        if self.fail:
            raise RuntimeError("stream failed")
        for chunk in self.chunks:
            if chunk == "__WAIT__":
                await self.release_next.wait()
                continue
            yield chunk


class RawLLMRuntime(FakeLLMRuntime):
    def __init__(self, payload) -> None:
        super().__init__(response="")
        self.payload = payload

    def chat_raw(self, messages, model_config=None, stream=False):
        self.calls.append({"messages": messages, "model_config": model_config or {}, "stream": stream})
        return self.payload


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
        self.llm_profiles = LLMProfileStore()
        self.provider_profiles = ProviderProfileStore()
        self.agent_configs = AgentConfigStore()
        self.llm = llm or FakeLLMRuntime()
        self.router = Router(agent_registry=agents, command_registry=commands)
        self.command_runner = CommandRunner(
            command_registry=commands,
            runtime_registry=runtimes,
            run_store=self.runs,
            message_store=self.messages,
            event_bus=self.events,
            capability_registry=capabilities,
        )
        self.agent_runner = AgentRunner(
            agent_registry=agents,
            run_store=self.runs,
            message_store=self.messages,
            event_bus=self.events,
            llm_runtime=self.llm,
            session_store=self.sessions,
            runtime_registry=runtimes,
            capability_registry=capabilities,
            llm_profile_store=self.llm_profiles,
            provider_profile_store=self.provider_profiles,
            agent_config_store=self.agent_configs,
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


def test_prompt_agent_success_creates_default_run_steps() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@chat hello"))
    steps = fixture.runs.list_steps(result.run_id)

    assert [step.label for step in steps] == [
        "Resolving agent",
        "Building context",
        "Resolving model",
        "Calling LLM",
        "Saving response",
        "Cleanup",
    ]
    assert [step.status.value for step in steps] == ["completed"] * 6


def test_run_lifecycle_steps_write_timestamps_and_emit_updates() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()
    run_record = fixture.runs.create_run(kind="agent", target_id="chat", session_id=session.session_id)
    lifecycle = fixture.agent_runner.run_lifecycle

    started = lifecycle.start_step(run_record.run_id, "Resolving agent")
    completed = lifecycle.complete_step(started.step_id)
    failed = lifecycle.start_step(run_record.run_id, "Calling LLM", parent_step_id=started.step_id)
    failed = lifecycle.fail_step(failed.step_id, error_message="Provider unreachable")
    skipped = fixture.runs.create_step(run_record.run_id, "Cleanup", status=RunStepStatus.PENDING)
    skipped = lifecycle.skip_step(skipped.step_id, message="Skipped after failure")

    events = fixture.events.list_events()
    assert started.started_at is not None
    assert completed.finished_at is not None
    assert failed.finished_at is not None
    assert skipped.finished_at is not None
    assert [event.type for event in events].count("run_step_created") == 2
    assert [event.type for event in events].count("run_step_updated") == 3
    assert failed.parent_step_id == started.step_id
    assert next(event for event in events if event.payload.get("step", {}).get("label") == "Calling LLM").payload["step"]["parent_step_id"] == started.step_id
    assert all(event.run_id == run_record.run_id for event in events)


def test_run_status_update_emits_run_update_event() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()
    run_record = fixture.runs.create_run(kind="agent", target_id="chat", session_id=session.session_id)

    fixture.agent_runner.run_lifecycle.start_run(run_record.run_id, stage="running")

    events = fixture.events.list_events()
    assert events[-1].type == "run_updated"
    assert events[-1].run_id == run_record.run_id
    assert events[-1].payload["run"]["status"] == "RUNNING"


def test_prompt_agent_emits_early_placeholder_bound_to_run_id() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@chat hello"))
    events = fixture.events.list_events()
    placeholder = next(event for event in events if event.type == "message_started")

    assert placeholder.run_id == result.run_id
    assert placeholder.payload["message_id"] == f"draft-{result.run_id}"
    assert placeholder.payload["agent_id"] == "chat"
    assert events.index(placeholder) < next(index for index, event in enumerate(events) if event.type == "run_step_created")


def test_prompt_agent_llm_failure_marks_calling_llm_step_failed() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(fail=True))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@chat hello"))
    steps = fixture.runs.list_steps(result.run_id)
    calling_llm = next(step for step in steps if step.label == "Calling LLM")

    assert result.success is False
    assert fixture.runs.get_run(result.run_id).status == RunStatus.FAILED
    assert calling_llm.status.value == "failed"
    assert calling_llm.error_message


def test_run_lifecycle_events_include_run_and_step_payloads() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    session = fixture.sessions.create_session()

    run(fixture.runtime.handle_input(session, "@chat hello"))

    step_event = next(event for event in fixture.events.list_events() if event.type == "run_step_created")
    run_event = next(event for event in fixture.events.list_events() if event.type == "run_updated")
    assert step_event.payload["step"]["label"] == "Resolving agent"
    assert "parent_step_id" in step_event.payload["step"]
    assert "run_id" in run_event.payload["run"]


def test_actual_model_metadata_from_nonstream_response() -> None:
    fixture = PromptRuntimeFixture(
        llm=RawLLMRuntime(
            {
                "content": "hello",
                "usage": {"total_tokens": 3},
                "raw": {"model": "actual-model", "system_fingerprint": "fp-1"},
            }
        )
    )
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@chat hello"))
    message = [item for item in fixture.messages.list_messages(session.session_id) if item.role == "assistant"][0]

    assert result.success is True
    assert message.metadata["llm"]["actual_model_id"] == "actual-model"
    assert message.metadata["llm"]["system_fingerprint"] == "fp-1"
    assert message.metadata["llm"]["actual_model_missing"] is False


def test_actual_model_metadata_from_streaming_chunk_and_mismatch() -> None:
    fixture = PromptRuntimeFixture(
        llm=FakeStreamingLLMRuntime(
            chunks=[
                {"model": "actual-stream-model", "choices": [{"delta": {"content": "he"}}]},
                {"choices": [{"delta": {"content": "llo"}}], "usage": {"total_tokens": 4}},
            ]
        )
    )
    profile = add_profile(fixture, supports_streaming=True)
    session = fixture.sessions.create_session()
    session = fixture.sessions.set_llm_profile(session.session_id, profile.id)

    result = run(fixture.runtime.handle_input(session, "@chat hello"))
    message = [item for item in fixture.messages.list_messages(session.session_id) if item.role == "assistant"][0]

    assert result.success is True
    assert message.metadata["llm"]["actual_model_id"] == "actual-stream-model"
    assert message.metadata["llm"]["requested_model_id"] == "fake-model"
    assert message.metadata["llm"]["model_mismatch"] is True


def test_streaming_actual_model_falls_back_to_requested_when_missing() -> None:
    fixture = PromptRuntimeFixture(llm=FakeStreamingLLMRuntime(chunks=[{"choices": [{"delta": {"content": "hello"}}]}]))
    profile = add_profile(fixture, supports_streaming=True)
    session = fixture.sessions.create_session()
    session = fixture.sessions.set_llm_profile(session.session_id, profile.id)

    run(fixture.runtime.handle_input(session, "@chat hello"))
    message = [item for item in fixture.messages.list_messages(session.session_id) if item.role == "assistant"][0]

    assert message.metadata["llm"]["actual_model_id"] == "fake-model"
    assert message.metadata["llm"]["actual_model_missing"] is True


def test_prompt_agent_failure_marks_run_failed() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(fail=True))
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@chat hello"))
    prompt_run = fixture.runs.get_run(result.run_id)

    assert result.success is False
    assert result.error == "LLM failed"
    assert prompt_run.status == RunStatus.FAILED
    assert prompt_run.error == "LLM failed"


def test_after_run_lifecycle_attempts_unload(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_workbench.core.runner.unload_model_for_profile", lambda **kwargs: calls.append(kwargs) or {"ok": True, "provider": "lm_studio", "provider_profile_id": kwargs["provider_profile_id"], "model_id": kwargs["model_id"], "unloaded": [], "errors": []})
    llm = FakeLLMRuntime(response="hello")
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=False, with_provider=True)
    session = fixture.sessions.create_session()
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@translate 你好"))

    assert result.success is True
    assert len(calls) == 1


def test_default_never_lifecycle_does_not_unload_provider(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_workbench.core.runner.unload_model_for_profile", lambda **kwargs: calls.append(kwargs) or {"ok": True, "unloaded": [], "errors": []})
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    profile = add_profile(fixture, supports_streaming=False, with_provider=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert calls == []
    assert "llm_unload" not in fixture.runs.get_run(result.run_id).metadata


def test_manifest_after_run_lifecycle_unloads_resolved_provider_model(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_workbench.core.runner.unload_model_for_profile", lambda **kwargs: calls.append(kwargs) or {"ok": True, "provider": "lm_studio", "provider_profile_id": kwargs["provider_profile_id"], "model_id": kwargs["model_id"], "unloaded": [{"instance_id": "i1", "model_id": kwargs["model_id"]}], "errors": []})
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    profile = add_profile(fixture, supports_streaming=False, with_provider=True)
    session = fixture.sessions.create_session()
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@translate hola"))
    metadata = fixture.runs.get_run(result.run_id).metadata

    assert result.success is True
    assert calls[0]["provider_profile_id"] == profile.provider_profile_id
    assert calls[0]["model_profile_id"] == profile.id
    assert calls[0]["model_id"] == "fake-model"
    assert metadata["llm_unload"]["policy"] == "after_run"
    assert metadata["llm_unload"]["ok"] is True
    assert metadata["llm_unload"]["unloaded_count"] == 1


def test_agent_config_after_run_override_wins_over_manifest_never(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_workbench.core.runner.unload_model_for_profile", lambda **kwargs: calls.append(kwargs) or {"ok": True, "provider": "lm_studio", "provider_profile_id": kwargs["provider_profile_id"], "model_id": kwargs["model_id"], "unloaded": [], "errors": []})
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    profile = add_profile(fixture, supports_streaming=False, with_provider=True)
    fixture.agent_configs.set_config("chat", runtime={"model_lifecycle": {"load": "on_demand", "unload": "after_run", "unload_failure": "warn"}})
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert len(calls) == 1


def test_agent_config_never_override_wins_over_manifest_after_run(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_workbench.core.runner.unload_model_for_profile", lambda **kwargs: calls.append(kwargs) or {"ok": True, "unloaded": [], "errors": []})
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    profile = add_profile(fixture, supports_streaming=False, with_provider=True)
    fixture.agent_configs.set_config("translate", runtime={"model_lifecycle": {"load": "on_demand", "unload": "never", "unload_failure": "warn"}})
    session = fixture.sessions.create_session()
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "@translate hola"))

    assert result.success is True
    assert calls == []


def test_streaming_after_run_uses_resolved_override_lifecycle(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_workbench.core.runner.unload_model_for_profile", lambda **kwargs: calls.append(kwargs) or {"ok": True, "provider": "lm_studio", "provider_profile_id": kwargs["provider_profile_id"], "model_id": kwargs["model_id"], "unloaded": [], "errors": []})
    fixture = PromptRuntimeFixture(llm=FakeStreamingLLMRuntime(chunks=["stream"]))
    profile = add_profile(fixture, supports_streaming=True, with_provider=True)
    fixture.agent_configs.set_config("chat", runtime={"model_lifecycle": {"load": "on_demand", "unload": "after_run", "unload_failure": "warn"}})
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert len(calls) == 1


def test_llm_config_failure_does_not_attempt_after_run_unload(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_workbench.core.runner.unload_model_for_profile", lambda **kwargs: calls.append(kwargs) or {"ok": True, "unloaded": [], "errors": []})
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    fixture.agent_configs.set_config("chat", runtime={"llm_profile_id": "missing", "model_lifecycle": {"load": "on_demand", "unload": "after_run", "unload_failure": "warn"}})
    session = fixture.sessions.create_session(default_agent_id="chat")

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is False
    assert result.error_code == "LLM_PROFILE_NOT_FOUND"
    assert calls == []


def test_after_run_unload_unsupported_does_not_fail_successful_run(monkeypatch) -> None:
    def unsupported(**kwargs):
        return {
            "ok": False,
            "code": "MODEL_UNLOAD_UNSUPPORTED",
            "provider": "openai_compatible",
            "provider_profile_id": kwargs["provider_profile_id"],
            "model_id": kwargs["model_id"],
            "unloaded": [],
            "errors": [{"code": "MODEL_UNLOAD_UNSUPPORTED", "message": "unsupported"}],
        }

    monkeypatch.setattr("ai_workbench.core.runner.unload_model_for_profile", unsupported)
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response="hello"))
    profile = add_profile(fixture, supports_streaming=False, with_provider=True, provider_kind="openai_compatible")
    fixture.agent_configs.set_config("chat", runtime={"model_lifecycle": {"load": "on_demand", "unload": "after_run", "unload_failure": "warn"}})
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))
    prompt_run = fixture.runs.get_run(result.run_id)

    assert result.success is True
    assert prompt_run.status == RunStatus.DONE
    assert prompt_run.metadata["llm_unload"]["ok"] is False
    assert prompt_run.metadata["llm_unload"]["code"] == "MODEL_UNLOAD_UNSUPPORTED"


def test_after_run_refcount_skips_until_last_active_use(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_workbench.core.runner.unload_model_for_profile", lambda **kwargs: calls.append(kwargs) or {"ok": True, "provider": "lm_studio", "provider_profile_id": kwargs["provider_profile_id"], "model_id": kwargs["model_id"], "unloaded": [], "errors": []})
    fixture = PromptRuntimeFixture()
    profile = add_profile(fixture, supports_streaming=False, with_provider=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    llm_config = fixture.agent_runner._resolve_llm_model_config(fixture.agent_runner.agent_registry.get("chat"), fixture.agent_runner.agent_registry.get("chat").actions[0], session.session_id)
    lifecycle = fixture.agent_runner.agent_registry.get("chat").model_lifecycle.model_copy(update={"unload": "after_run"})
    first = fixture.agent_runner._begin_llm_use(llm_config)
    second = fixture.agent_runner._begin_llm_use(llm_config)
    run1 = fixture.runs.create_run(kind="agent", target_id="chat", session_id=session.session_id)
    run2 = fixture.runs.create_run(kind="agent", target_id="chat", session_id=session.session_id)

    fixture.agent_runner._finish_llm_use_and_apply_lifecycle(lifecycle, llm_config, first, run1.run_id, session.session_id)
    fixture.agent_runner._finish_llm_use_and_apply_lifecycle(lifecycle, llm_config, second, run2.run_id, session.session_id)

    assert calls == [{"provider_profile_store": fixture.provider_profiles, "llm_profile_store": fixture.llm_profiles, "provider_profile_id": profile.provider_profile_id, "model_profile_id": profile.id, "model_id": "fake-model", "reason": "after_run"}]
    assert fixture.runs.get_run(run1.run_id).metadata["llm_unload"]["skipped"] is True
    assert fixture.runs.get_run(run2.run_id).metadata["llm_unload"]["skipped"] is False


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
    assert prompt_run.metadata["warnings"] == ["Provider profile is required for unload."]
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


def add_profile(
    fixture: PromptRuntimeFixture,
    supports_streaming: bool = True,
    supports_reasoning: bool = False,
    supports_vision: bool = False,
    with_provider: bool = False,
    provider_kind: str = "lm_studio",
) -> LLMProfileSchema:
    provider_profile_id = None
    provider = provider_kind
    base_url = "http://localhost:1234/v1"
    if with_provider:
        provider_record = ProviderProfileSchema(
            id=f"provider-{provider_kind}-{supports_streaming}-{supports_reasoning}-{supports_vision}",
            name="Provider",
            provider=provider_kind,
            base_url=base_url,
        )
        fixture.provider_profiles.create(provider_record)
        provider_profile_id = provider_record.id
    profile = LLMProfileSchema(
        id=f"profile-{supports_streaming}-{supports_reasoning}-{supports_vision}",
        alias=f"profile_{supports_streaming}_{supports_reasoning}_{supports_vision}",
        name="Streaming profile" if supports_streaming else "Non-streaming profile",
        provider_profile_id=provider_profile_id,
        provider=provider,
        base_url="http://localhost:1234/v1",
        model_id="fake-model",
        supports_streaming=supports_streaming,
        supports_reasoning=supports_reasoning,
        supports_vision=supports_vision,
    )
    fixture.llm_profiles.create(profile)
    return profile


def image_attachment(name: str = "image.png", data_url: str = PNG_DATA_URL, mime_type: str = "image/png") -> dict:
    return {
        "id": name,
        "type": "image",
        "mime_type": mime_type,
        "name": name,
        "size": 5,
        "data_url": data_url,
    }


def test_nonstream_llm_result_parses_reasoning_content_separately() -> None:
    raw = {
        "choices": [
            {
                "message": {
                    "content": "final answer",
                    "reasoning_content": "private thought",
                }
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }

    result = _extract_llm_result(raw)

    assert result.content == "final answer"
    assert result.reasoning_content == "private thought"
    assert "private thought" not in result.content
    assert result.usage == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}


def test_nonstream_empty_reasoning_content_is_ignored() -> None:
    raw = {"choices": [{"message": {"content": "final answer", "reasoning_content": ""}}]}

    result = _extract_llm_result(raw)

    assert result.content == "final answer"
    assert result.reasoning_content is None


def test_streaming_openai_chunk_parses_reasoning_delta_separately() -> None:
    chunk = _normalize_stream_chunk({"choices": [{"delta": {"content": "answer", "reasoning_content": "thought"}}]})

    assert chunk.content_delta == "answer"
    assert chunk.reasoning_delta == "thought"


def test_prompt_agent_uses_streaming_when_profile_supports_streaming() -> None:
    llm = FakeStreamingLLMRuntime(chunks=["he", "llo", {"usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}])
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))
    messages = fixture.messages.list_messages(session.session_id)
    events = fixture.events.list_events()

    assert result.success is True
    assert result.data == "hello"
    assert llm.calls[0]["stream"] is True
    assert messages[-1].content == "hello"
    assert messages[-1].metadata["llm_resolution"]["profile_id"] == profile.id
    assert messages[-1].metadata["llm_metrics"]["usage_source"] == "provider"
    assert messages[-1].metadata["llm_metrics"]["completion_tokens"] == 2
    assert messages[-1].metadata["llm_metrics"]["time_to_first_token_ms"] is not None
    assert [event.payload.get("delta") for event in events if event.type == "message_delta"] == ["he", "llo"]
    assert "message_completed" in [event.type for event in events]


def test_prompt_agent_uses_non_streaming_when_profile_does_not_support_streaming() -> None:
    llm = FakeLLMRuntime(response="complete")
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=False)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))

    assert result.success is True
    assert llm.calls[0]["stream"] is False
    message = fixture.messages.list_messages(session.session_id)[-1]
    assert message.content == "complete"
    assert message.metadata["llm_metrics"]["streamed"] is False
    assert message.metadata["llm_metrics"]["usage_source"] == "estimated"


def test_vision_profile_sends_text_and_single_image_as_content_parts() -> None:
    llm = FakeLLMRuntime(response="vision reply")
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=False, supports_vision=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "what is this?", attachments=[image_attachment()]))
    sent = llm.calls[0]["messages"][-1]
    run_metadata = fixture.runs.get_run(result.run_id).metadata
    assistant = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert sent["role"] == "user"
    assert sent["content"] == [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": PNG_DATA_URL}},
    ]
    assert run_metadata["vision_input"] == {"supported": True, "images_attached": 1, "images_sent": 1, "images_ignored": 0}
    assert assistant.metadata["vision_input"] == run_metadata["vision_input"]


def test_vision_profile_sends_multiple_images() -> None:
    llm = FakeLLMRuntime(response="vision reply")
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=False, supports_vision=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    run(
        fixture.runtime.handle_input(
            session,
            "compare these",
            attachments=[
                image_attachment("one.png", PNG_DATA_URL, "image/png"),
                image_attachment("two.jpg", JPEG_DATA_URL, "image/jpeg"),
            ],
        )
    )
    content = llm.calls[0]["messages"][-1]["content"]

    assert content[0] == {"type": "text", "text": "compare these"}
    assert [part["image_url"]["url"] for part in content[1:]] == [PNG_DATA_URL, JPEG_DATA_URL]


def test_vision_profile_uses_default_text_for_image_only_message() -> None:
    llm = FakeLLMRuntime(response="vision reply")
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=False, supports_vision=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    run(fixture.runtime.handle_input(session, "", attachments=[image_attachment()]))
    content = llm.calls[0]["messages"][-1]["content"]

    assert content == [
        {"type": "text", "text": "Please analyze the attached image."},
        {"type": "image_url", "image_url": {"url": PNG_DATA_URL}},
    ]


def test_non_vision_profile_does_not_send_data_url_and_adds_placeholder() -> None:
    llm = FakeLLMRuntime(response="text reply")
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=False, supports_vision=False)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "what is this?", attachments=[image_attachment()]))
    sent = llm.calls[0]["messages"][-1]
    assistant = fixture.messages.list_messages(session.session_id)[-1]
    user = fixture.messages.list_messages(session.session_id)[0]

    assert result.success is True
    assert sent["content"] == "what is this?\n\nUser attached 1 image, but the selected model does not support vision."
    assert PNG_DATA_URL not in sent["content"]
    assert assistant.metadata["vision_input"] == {"supported": False, "images_attached": 1, "images_sent": 0, "images_ignored": 1}
    assert user.metadata["attachments"][0]["data_url"] == PNG_DATA_URL


def test_prompt_agent_adds_current_text_file_attachment_to_llm_context(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    llm = FakeLLMRuntime(response="text reply")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat")
    stored = save_attachment_from_upload("Cal.md", "text/markdown", b"# Calendar\n\n- Monday: planning\n")

    result = run(fixture.runtime.handle_input(session, "summarize", attachments=[stored]))
    sent = llm.calls[0]["messages"][-1]["content"]
    user = fixture.messages.list_messages(session.session_id)[0]
    run_metadata = fixture.runs.get_run(result.run_id).metadata

    assert result.success is True
    assert sent.startswith("summarize\n\nUser attached file: Cal.md")
    assert "MIME: text/markdown" in sent
    assert "Size: 31 B" in sent
    assert "Truncated: false" in sent
    assert "```markdown\n# Calendar\n\n- Monday: planning\n" in sent
    assert run_metadata["file_context"]["files_attached"] == 1
    assert run_metadata["file_context"]["files_sent"] == 1
    assert run_metadata["file_context"]["files_ignored"] == 0
    assert user.metadata["attachments"][0]["type"] == "file"
    assert "Calendar" not in str(run_metadata)


def test_prompt_agent_uses_file_context_when_message_has_no_text(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    llm = FakeLLMRuntime(response="text reply")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat")
    stored = save_attachment_from_upload("notes.txt", "text/plain", b"only file body")

    result = run(fixture.runtime.handle_input(session, "", attachments=[stored]))
    sent = llm.calls[0]["messages"][-1]["content"]

    assert result.success is True
    assert sent.startswith("User attached 1 text file.\n\nUser attached file: notes.txt")
    assert "only file body" in sent


def test_prompt_agent_truncates_large_text_file_attachment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    llm = FakeLLMRuntime(response="text reply")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat")
    stored = save_attachment_from_upload("large.log", "text/plain", b"a" * (220 * 1024))

    result = run(fixture.runtime.handle_input(session, "summarize", attachments=[stored]))
    sent = llm.calls[0]["messages"][-1]["content"]
    run_metadata = fixture.runs.get_run(result.run_id).metadata

    assert result.success is True
    assert "Truncated: true" in sent
    assert run_metadata["file_context"]["files_sent"] == 1
    assert run_metadata["file_context"]["total_chars"] == 200 * 1024
    assert len(sent) < 210 * 1024


def test_prompt_agent_ignores_binary_file_attachment() -> None:
    llm = FakeLLMRuntime(response="text reply")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat")
    binary = {
        "id": "binary",
        "type": "file",
        "mime_type": "application/octet-stream",
        "name": "data.bin",
        "size": 4,
        "uri": "local://attachments/00000000-0000-0000-0000-000000000000.bin",
    }

    result = run(fixture.runtime.handle_input(session, "summarize", attachments=[binary]))
    sent = llm.calls[0]["messages"][-1]["content"]
    run_metadata = fixture.runs.get_run(result.run_id).metadata

    assert result.success is True
    assert sent == "summarize\n\nUser attached 1 file that is not readable as text."
    assert run_metadata["file_context"]["files_attached"] == 1
    assert run_metadata["file_context"]["files_sent"] == 0
    assert run_metadata["file_context"]["files_ignored"] == 1


def test_context_does_not_inject_historical_image_data_urls() -> None:
    llm = FakeLLMRuntime(response="next")
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=False, supports_vision=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)
    fixture.messages.add_message(
        session_id=session.session_id,
        role="user",
        content="old image",
        metadata={"attachments": [image_attachment()]},
    )

    run(fixture.runtime.handle_input(session, "new text"))
    sent = llm.calls[0]["messages"]

    assert {"role": "user", "content": "old image"} in sent
    assert all(PNG_DATA_URL not in str(message["content"]) for message in sent)


def test_streaming_prompt_agent_uses_vision_messages() -> None:
    llm = FakeStreamingLLMRuntime(chunks=["vision"])
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=True, supports_vision=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "describe", attachments=[image_attachment()]))
    content = llm.calls[0]["messages"][-1]["content"]

    assert result.success is True
    assert llm.calls[0]["stream"] is True
    assert content[1] == {"type": "image_url", "image_url": {"url": PNG_DATA_URL}}


def test_nonstream_prompt_agent_saves_reasoning_metadata() -> None:
    llm = FakeLLMRuntime(
        response={
            "choices": [
                {
                    "message": {
                        "content": "visible answer",
                        "reasoning_content": "hidden chain",
                    }
                }
            ]
        }
    )
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=False, supports_reasoning=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert message.content == "visible answer"
    assert message.metadata["reasoning_content"] == "hidden chain"
    assert message.metadata["reasoning"] == {"expected": True, "received": True, "content": "hidden chain"}


def test_nonstream_prompt_agent_without_reasoning_does_not_write_empty_thought() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(response={"choices": [{"message": {"content": "visible answer"}}]}))
    profile = add_profile(fixture, supports_streaming=False, supports_reasoning=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert message.content == "visible answer"
    assert "reasoning_content" not in message.metadata
    assert message.metadata["reasoning"] == {"expected": True, "received": False, "content": None}


def test_reasoning_content_does_not_enter_next_context() -> None:
    llm = FakeLLMRuntime(response="next")
    fixture = PromptRuntimeFixture(llm=llm)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.messages.add_message(session_id=session.session_id, role="user", content="old user")
    fixture.messages.add_message(
        session_id=session.session_id,
        role="assistant",
        content="old answer",
        agent_id="chat",
        metadata={"reasoning_content": "do not send this thought"},
    )

    run(fixture.runtime.handle_input(session, "new user"))
    sent = llm.calls[0]["messages"]

    assert {"role": "assistant", "content": "old answer"} in sent
    assert all("do not send this thought" not in message["content"] for message in sent)


def test_retry_regenerates_reasoning_metadata() -> None:
    llm = FakeLLMRuntime(
        response={
            "choices": [
                {
                    "message": {
                        "content": "retry answer",
                        "reasoning_content": "retry thought",
                    }
                }
            ]
        }
    )
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=False, supports_reasoning=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    first = run(fixture.runtime.handle_input(session, "hello"))
    source_user_message = fixture.messages.list_messages(session.session_id)[0]
    first_message = fixture.messages.list_messages(session.session_id)[-1]
    retry = run(fixture.runtime.retry_assistant_message(session, first_message, source_user_message))
    retry_message = fixture.messages.list_messages(session.session_id)[-1]

    assert first.success is True
    assert retry.success is True
    assert retry_message.metadata["reasoning_content"] == "retry thought"


def test_edit_rerun_regenerates_reasoning_metadata() -> None:
    llm = FakeLLMRuntime(
        response={
            "choices": [
                {
                    "message": {
                        "content": "edited answer",
                        "reasoning_content": "edited thought",
                    }
                }
            ]
        }
    )
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=False, supports_reasoning=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    first = run(fixture.runtime.handle_input(session, "hello"))
    user_message = fixture.messages.list_messages(session.session_id)[0]
    updated_user = fixture.messages.update_message(user_message.model_copy(update={"content": "edited hello"}))
    rerun = run(fixture.runtime.rerun_user_message(session, updated_user))
    rerun_message = fixture.messages.list_messages(session.session_id)[-1]

    assert first.success is True
    assert rerun.success is True
    assert rerun_message.content == "edited answer"
    assert rerun_message.metadata["reasoning_content"] == "edited thought"


def test_streaming_without_provider_usage_estimates_completion_tokens() -> None:
    llm = FakeStreamingLLMRuntime(chunks=["abcd", "efgh"])
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert message.metadata["llm_metrics"]["usage_source"] == "estimated"
    assert message.metadata["llm_metrics"]["estimated_completion_tokens"] == 2


def test_streaming_reasoning_delta_accumulates_to_final_metadata() -> None:
    llm = FakeStreamingLLMRuntime(
        chunks=[
            {"reasoning_delta": "think "},
            {"delta": "visible "},
            {"choices": [{"delta": {"reasoning_content": "more"}}]},
            {"choices": [{"delta": {"content": "answer"}}]},
        ]
    )
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=True, supports_reasoning=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))
    message = fixture.messages.list_messages(session.session_id)[-1]
    events = fixture.events.list_events()

    assert result.success is True
    assert message.content == "visible answer"
    assert message.metadata["reasoning_content"] == "think more"
    assert message.metadata["reasoning"] == {"expected": True, "received": True, "content": "think more"}
    assert [event.payload.get("delta") for event in events if event.type == "message_delta"] == ["", "visible ", "", "answer"]
    assert [event.payload.get("reasoning_delta") for event in events if event.type == "message_delta"] == ["think ", None, "more", None]


def test_streaming_failure_marks_run_failed() -> None:
    llm = FakeStreamingLLMRuntime(fail=True)
    fixture = PromptRuntimeFixture(llm=llm)
    profile = add_profile(fixture, supports_streaming=True)
    session = fixture.sessions.create_session(default_agent_id="chat")
    fixture.sessions.set_llm_profile(session.session_id, profile.id)
    session = fixture.sessions.get_session(session.session_id)

    result = run(fixture.runtime.handle_input(session, "hello"))
    prompt_run = fixture.runs.get_run(result.run_id)

    assert result.success is False
    assert result.error_code == "RUN_FAILED"
    assert prompt_run.status == RunStatus.FAILED


def test_friendly_error_mapping_for_provider_unreachable() -> None:
    fixture = PromptRuntimeFixture(llm=FakeLLMRuntime(fail=True))
    fixture.llm.response = ""
    fixture.llm.fail = False

    def fail_connect(messages, model_config=None, stream=False):
        raise RuntimeError("connection refused")

    fixture.llm.chat = fail_connect
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "@chat hello"))
    prompt_run = fixture.runs.get_run(result.run_id)

    assert result.success is False
    assert result.error_code == "PROVIDER_UNREACHABLE"
    assert prompt_run.metadata["error"]["code"] == "PROVIDER_UNREACHABLE"


def test_friendly_error_mapping_for_model_not_available_and_mismatch() -> None:
    not_available = _friendly_llm_error(RuntimeError("model not available"))
    mismatch = _friendly_llm_error(RuntimeError("different model"))

    assert not_available["code"] == "MODEL_NOT_AVAILABLE"
    assert "requested model is not available" in not_available["message"]
    assert mismatch["code"] == "MODEL_MISMATCH"


def test_cancel_streaming_run_persists_partial_message() -> None:
    async def scenario():
        llm = FakeStreamingLLMRuntime(chunks=["part", "__WAIT__", " never"])
        fixture = PromptRuntimeFixture(llm=llm)
        profile = add_profile(fixture, supports_streaming=True)
        session = fixture.sessions.create_session(default_agent_id="chat")
        fixture.sessions.set_llm_profile(session.session_id, profile.id)
        session = fixture.sessions.get_session(session.session_id)
        task = asyncio.create_task(fixture.runtime.handle_input(session, "hello"))
        await llm.stream_started.wait()
        run_id = fixture.runs.list_runs(session.session_id)[0].run_id
        for _ in range(20):
            if any(event.type == "message_delta" for event in fixture.events.list_events()):
                break
            await asyncio.sleep(0)
        assert fixture.agent_runner.active_runs.cancel(run_id) is True
        result = await task
        return fixture, result, run_id, session.session_id

    fixture, result, run_id, session_id = run(scenario())
    prompt_run = fixture.runs.get_run(run_id)
    messages = fixture.messages.list_messages(session_id)

    assert result.success is False
    assert prompt_run.status == RunStatus.CANCELLED
    assert messages[-1].content == "part"
    assert messages[-1].metadata["interrupted"] is True
    assert "run_cancelled" in [event.type for event in fixture.events.list_events()]


def test_active_run_registry_cancel_all_cancels_and_unregisters_tasks() -> None:
    async def scenario():
        registry = ActiveRunRegistry()
        cancelled = asyncio.Event()

        async def wait_forever():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(wait_forever())
        registry.register("run-1", task)
        await asyncio.sleep(0)

        await registry.cancel_all()

        assert cancelled.is_set()
        assert task.cancelled()
        assert registry.cancel("run-1") is False

    run(scenario())


def test_cancel_nonstreaming_run_marks_run_cancelled() -> None:
    class BlockingLLMRuntime(FakeLLMRuntime):
        def __init__(self) -> None:
            super().__init__(response="late reply")
            self.started = ThreadingEvent()
            self.release = ThreadingEvent()

        def chat(self, messages, model_config=None, stream=False):
            self.started.set()
            self.release.wait(timeout=1)
            return super().chat(messages, model_config=model_config, stream=stream)

    async def scenario():
        llm = BlockingLLMRuntime()
        fixture = PromptRuntimeFixture(llm=llm)
        session = fixture.sessions.create_session(default_agent_id="chat")
        task = asyncio.create_task(fixture.runtime.handle_input(session, "hello"))
        for _ in range(50):
            if llm.started.is_set() and fixture.runs.list_runs(session.session_id):
                break
            await asyncio.sleep(0.01)
        run_id = fixture.runs.list_runs(session.session_id)[0].run_id

        assert fixture.agent_runner.active_runs.cancel(run_id) is True
        result = await task
        llm.release.set()

        return fixture, result, run_id

    fixture, result, run_id = run(scenario())
    prompt_run = fixture.runs.get_run(run_id)

    assert result.success is False
    assert prompt_run.status == RunStatus.CANCELLED
    assert "run_cancelled" in [event.type for event in fixture.events.list_events()]


def test_cancel_streaming_run_persists_reasoning_only_partial_message() -> None:
    async def scenario():
        llm = FakeStreamingLLMRuntime(chunks=[{"reasoning_delta": "partial thought"}, "__WAIT__", " never"])
        fixture = PromptRuntimeFixture(llm=llm)
        profile = add_profile(fixture, supports_streaming=True, supports_reasoning=True)
        session = fixture.sessions.create_session(default_agent_id="chat")
        fixture.sessions.set_llm_profile(session.session_id, profile.id)
        session = fixture.sessions.get_session(session.session_id)
        task = asyncio.create_task(fixture.runtime.handle_input(session, "hello"))
        await llm.stream_started.wait()
        run_id = fixture.runs.list_runs(session.session_id)[0].run_id
        for _ in range(20):
            if any(event.payload.get("reasoning_delta") for event in fixture.events.list_events() if event.type == "message_delta"):
                break
            await asyncio.sleep(0)
        assert fixture.agent_runner.active_runs.cancel(run_id) is True
        result = await task
        return fixture, result, run_id, session.session_id

    fixture, result, run_id, session_id = run(scenario())
    prompt_run = fixture.runs.get_run(run_id)
    messages = fixture.messages.list_messages(session_id)

    assert result.success is False
    assert prompt_run.status == RunStatus.CANCELLED
    assert messages[-1].content == ""
    assert messages[-1].metadata["reasoning_content"] == "partial thought"
    assert messages[-1].metadata["interrupted"] is True
