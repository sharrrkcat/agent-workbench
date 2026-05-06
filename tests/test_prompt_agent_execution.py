import asyncio
from pathlib import Path

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.router import Router
from ai_workbench.core.runner import AgentRunner, CommandRunner, _extract_llm_result, _normalize_stream_chunk
from ai_workbench.core.runtime import WorkbenchRuntime
from ai_workbench.core.schema.llm_profile import LLMProfileSchema
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.stores import LLMProfileStore, MessageStore, RunStore, SessionStore


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


def add_profile(
    fixture: PromptRuntimeFixture,
    supports_streaming: bool = True,
    supports_reasoning: bool = False,
    supports_vision: bool = False,
) -> LLMProfileSchema:
    profile = LLMProfileSchema(
        id=f"profile-{supports_streaming}-{supports_reasoning}-{supports_vision}",
        alias=f"profile_{supports_streaming}_{supports_reasoning}_{supports_vision}",
        name="Streaming profile" if supports_streaming else "Non-streaming profile",
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
    assert prompt_run.status == RunStatus.FAILED
    assert "run_failed" in [event.type for event in fixture.events.list_events()]


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
