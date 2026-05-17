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
from ai_workbench.core.message_parts import make_file_part
from ai_workbench.core.schema.capability import CapabilitySchema
from ai_workbench.core.schema.run import RunStatus, RunStepStatus
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore


ROOT = Path(__file__).resolve().parents[1]
SVG_DATA_URL = (
    "data:image/svg+xml;base64,"
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMjAiIGhlaWdodD0iNjAiPjx0ZXh0IHg9IjgiIHk9IjM1Ij5vazwvdGV4dD48L3N2Zz4="
)


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
            capability_registry=capabilities,
        )
        self.runtime = WorkbenchRuntime(router=self.router, command_runner=self.command_runner)


class RuntimeWithResult:
    def __init__(self, result) -> None:
        self.result = result

    def make(self, text: str):
        return self.result


def command_fixture_from_manifest(manifest: dict, runtime) -> RuntimeFixture:
    fixture = RuntimeFixture.__new__(RuntimeFixture)
    agents = AgentRegistry()
    agents.load_from_directory(ROOT / "agents")
    capabilities = CapabilityRegistry()
    capability = CapabilitySchema.model_validate(manifest)
    capabilities.register(capability)
    commands = CommandRegistry.from_capability_registry(capabilities)
    runtimes = CapabilityRuntimeRegistry()
    runtimes.register(capability.id, runtime)
    fixture.sessions = SessionStore()
    fixture.messages = MessageStore()
    fixture.runs = RunStore()
    fixture.events = EventBus()
    fixture.router = Router(agent_registry=agents, command_registry=commands)
    fixture.command_runner = CommandRunner(
        command_registry=commands,
        runtime_registry=runtimes,
        run_store=fixture.runs,
        message_store=fixture.messages,
        event_bus=fixture.events,
        capability_registry=capabilities,
    )
    fixture.runtime = WorkbenchRuntime(router=fixture.router, command_runner=fixture.command_runner)
    return fixture


def run(coro):
    return asyncio.run(coro)


def test_base64_encode_executes_end_to_end() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/encode base64 hello"))

    assert result.success is True
    assert result.data[0]["type"] == "file"
    assert result.data[0]["content"] == "aGVsbG8="
    assert not hasattr(result, "output_type")
    assert fixture.runs.get_run(result.run_id).status == RunStatus.DONE


def test_base64_decode_executes_end_to_end() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/decode base64 aGVsbG8="))

    assert result.success is True
    assert result.data[0]["type"] == "file"
    assert result.data[0]["content"] == "hello"
    assert not hasattr(result, "output_type")
    assert fixture.runs.get_run(result.run_id).status == RunStatus.DONE


def test_base64_image_command_returns_image_output() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, f"/decode base64 {SVG_DATA_URL}"))
    messages = fixture.messages.list_messages(session.session_id)

    assert result.success is True
    assert not hasattr(result, "output_type")
    assert result.data[0]["url"].startswith("/api/attachments/")
    assert set(result.data[0]) == {"type", "attachment_id", "url", "alt", "title", "caption"}
    assert messages[-1].role == "assistant"
    assert messages[-1].command_name == "/decode"
    assert messages[-1].parts[0]["type"] == "image"
    assert messages[-1].parts[0]["url"] == result.data[0]["url"]
    assert messages[-1].metadata["kind"] == "command_result"
    assert messages[-1].metadata["producer"] == "capability"


def test_raw_base64_image_returns_image_output() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, f"/decode base64 {SVG_DATA_URL.split(',', 1)[1]}"))
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert not hasattr(result, "output_type")
    assert message.parts[0]["type"] == "image"


def test_image_base64_without_attachment_fails() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()
    user = fixture.messages.add_message(
        session_id=session.session_id,
        role="user",
        content="/encode base64",
        metadata={"attachments": []},
    )

    result = run(fixture.command_runner.run("/encode", "base64", session.session_id, input_message_id=user.message_id))

    assert result.success is False
    assert result.error == "Usage: /encode base64 <text>"


def test_image_base64_returns_first_attachment_data() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()
    user = fixture.messages.add_message(
        session_id=session.session_id,
        role="user",
        content="/encode base64",
        metadata={"attachments": [sample_attachment("one.svg", SVG_DATA_URL)]},
    )

    result = run(fixture.command_runner.run("/encode", "base64", session.session_id, input_message_id=user.message_id))

    assert result.success is True
    assert not hasattr(result, "output_type")
    assert result.data[0]["filename"] == "image-data-url.txt"
    assert result.data[0]["content"] == SVG_DATA_URL


def test_image_base64_rejects_multiple_attachments() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()
    second = SVG_DATA_URL.replace("b2s", "b2s")
    user = fixture.messages.add_message(
        session_id=session.session_id,
        role="user",
        content="/encode base64",
        metadata={"attachments": [sample_attachment("one.svg", SVG_DATA_URL), sample_attachment("two.svg", second)]},
    )

    result = run(fixture.command_runner.run("/encode", "base64", session.session_id, input_message_id=user.message_id))

    assert result.success is False
    assert result.error == "Multiple image attachments found. Attach exactly one image for /encode base64."


def test_base64_decode_invalid_input_returns_failed_result_and_run() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/decode base64 invalid!!!"))
    failed_run = fixture.runs.get_run(result.run_id)

    assert result.success is False
    assert result.error == "Invalid Base64 input."
    assert failed_run.status == RunStatus.FAILED
    assert failed_run.error == "Invalid Base64 input."


def test_base64url_encode_decodes_url_safe_text() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    encoded = run(fixture.runtime.handle_input(session, "/encode base64url hello?"))
    unpadded = run(fixture.runtime.handle_input(session, "/decode base64url aGVsbG8"))
    padded = run(fixture.runtime.handle_input(session, "/decode base64url aGVsbG8="))

    assert encoded.success is True
    assert encoded.data[0]["type"] == "file"
    assert encoded.data[0]["filename"] == "base64url.txt"
    assert encoded.data[0]["content"] == "aGVsbG8_"
    assert unpadded.success is True
    assert unpadded.data[0]["content"] == "hello"
    assert padded.success is True
    assert padded.data[0]["content"] == "hello"


def test_base64url_decode_rejects_non_url_safe_characters() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/decode base64url aGVsbG8/"))

    assert result.success is False
    assert "Invalid Base64URL input" in result.error


def test_url_codec_uses_component_percent_encoding() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    encoded = run(fixture.runtime.handle_input(session, "/encode url 你好 world"))
    decoded = run(fixture.runtime.handle_input(session, "/decode url %E4%BD%A0%E5%A5%BD%20world"))
    plus = run(fixture.runtime.handle_input(session, "/decode url a+b"))

    assert encoded.success is True
    assert encoded.data[0]["filename"] == "url-encoded.txt"
    assert encoded.data[0]["content"] == "%E4%BD%A0%E5%A5%BD%20world"
    assert decoded.success is True
    assert decoded.data[0]["filename"] == "url-decoded.txt"
    assert decoded.data[0]["content"] == "你好 world"
    assert plus.success is True
    assert plus.data[0]["content"] == "a+b"


def test_url_decode_rejects_invalid_percent_escape() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    bad_hex = run(fixture.runtime.handle_input(session, "/decode url %ZZ"))
    incomplete = run(fixture.runtime.handle_input(session, "/decode url %A"))

    assert bad_hex.success is False
    assert "Invalid URL percent escape" in bad_hex.error
    assert incomplete.success is False
    assert "Invalid URL percent escape" in incomplete.error


def test_unicode_codec_escapes_text_and_roundtrips_emoji() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    encoded = run(fixture.runtime.handle_input(session, "/encode unicode 你好"))
    decoded = run(fixture.runtime.handle_input(session, r"/decode unicode \u4f60\u597d"))
    emoji_encoded = run(fixture.runtime.handle_input(session, "/encode unicode hi 😀"))
    emoji_decoded = run(fixture.runtime.handle_input(session, r"/decode unicode hi \ud83d\ude00"))

    assert encoded.success is True
    assert encoded.data[0]["filename"] == "unicode-escaped.txt"
    assert encoded.data[0]["content"] == r"\u4f60\u597d"
    assert decoded.success is True
    assert decoded.data[0]["filename"] == "unicode-decoded.txt"
    assert decoded.data[0]["content"] == "你好"
    assert emoji_encoded.success is True
    assert emoji_encoded.data[0]["content"] == r"hi \ud83d\ude00"
    assert emoji_decoded.success is True
    assert emoji_decoded.data[0]["content"] == "hi 😀"


def test_unicode_decode_rejects_invalid_escape_without_eval_behavior() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    invalid = run(fixture.runtime.handle_input(session, r"/decode unicode \u12ZZ"))
    unknown = run(fixture.runtime.handle_input(session, r"/decode unicode __import__('os')\q"))

    assert invalid.success is False
    assert "Invalid Unicode escape" in invalid.error
    assert unknown.success is False
    assert "Invalid Unicode escape" in unknown.error


def test_hex_codec_encodes_and_decodes_utf8_text() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    encoded = run(fixture.runtime.handle_input(session, "/encode hex 你好"))
    compact = run(fixture.runtime.handle_input(session, "/decode hex e4bda0e5a5bd"))
    spaced = run(fixture.runtime.handle_input(session, "/decode hex e4 bd a0 e5 a5 bd"))

    assert encoded.success is True
    assert encoded.data[0]["filename"] == "hex.txt"
    assert encoded.data[0]["content"] == "e4bda0e5a5bd"
    assert compact.success is True
    assert compact.data[0]["content"] == "你好"
    assert spaced.success is True
    assert spaced.data[0]["content"] == "你好"


def test_hex_decode_rejects_odd_length_and_invalid_characters() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    odd = run(fixture.runtime.handle_input(session, "/decode hex abc"))
    invalid = run(fixture.runtime.handle_input(session, "/decode hex e4zz"))

    assert odd.success is False
    assert "even number of digits" in odd.error
    assert invalid.success is False
    assert "Invalid hex input" in invalid.error


def test_codec_usage_and_unsupported_errors_list_supported_codecs() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    encode_usage = run(fixture.runtime.handle_input(session, "/encode"))
    decode_usage = run(fixture.runtime.handle_input(session, "/decode"))
    encode_unknown = run(fixture.runtime.handle_input(session, "/encode unknown test"))
    decode_unknown = run(fixture.runtime.handle_input(session, "/decode unknown test"))

    for result in [encode_usage, decode_usage, encode_unknown, decode_unknown]:
        assert result.success is False
        assert "base64, base64url, url, unicode, hex" in result.error
    assert "Unsupported codec: unknown" in encode_unknown.error
    assert "Unsupported codec: unknown" in decode_unknown.error


def test_successful_command_creates_done_run() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/encode base64 hello"))
    runs = fixture.runs.list_runs(session.session_id)

    assert len(runs) == 1
    assert runs[0].run_id == result.run_id
    assert runs[0].target_id == "/encode"
    assert runs[0].status == RunStatus.DONE


def test_failed_command_creates_failed_run() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/decode base64 invalid!!!"))
    runs = fixture.runs.list_runs(session.session_id)

    assert len(runs) == 1
    assert runs[0].run_id == result.run_id
    assert runs[0].target_id == "/decode"
    assert runs[0].status == RunStatus.FAILED


def test_successful_command_writes_message_store() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/encode base64 hello"))
    messages = fixture.messages.list_messages(session.session_id)

    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].command_name == "/encode"
    assert messages[0].run_id == result.run_id
    assert messages[0].parts[0]["content"] == "aGVsbG8="
    assert messages[0].metadata["output_part_type"] == "parts"
    assert messages[0].metadata["kind"] == "command_result"
    assert messages[0].metadata["producer"] == "capability"
    assert messages[0].metadata["command"] == "/encode"


def test_declared_image_output_validation_failure_fails_run() -> None:
    fixture = command_fixture_from_manifest(
        {
            "id": "bad_image",
            "name": "Bad Image",
            "methods": [{"id": "make", "output": {"part_type": "image"}}],
            "commands": [{"name": "/bad-image", "method": "make"}],
        },
        runtime=RuntimeWithResult({"url": ""}),
    )
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/bad-image ignored"))
    failed_run = fixture.runs.get_run(result.run_id)
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is False
    assert failed_run.status == RunStatus.FAILED
    assert message.parts[0]["type"] == "error"
    assert message.metadata["success"] is False


def test_dict_command_without_image_shape_falls_back_to_json_output() -> None:
    fixture = command_fixture_from_manifest(
        {
            "id": "dict_result",
            "name": "Dict Result",
            "methods": [{"id": "make"}],
            "commands": [{"name": "/dict-result", "method": "make"}],
        },
        runtime=RuntimeWithResult({"ok": True, "items": [1, 2]}),
    )
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/dict-result ignored"))
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert not hasattr(result, "output_type")
    assert message.parts == [{"id": "part_1", "type": "json", "data": {"ok": True, "items": [1, 2]}}]


def test_file_part_schema_accepts_expected_shape() -> None:
    payload = make_file_part(
        "id: chat\nname: Chat Agent\n",
        filename="agent.yaml",
        language="yaml",
        mime_type="text/yaml",
        size=1234,
        truncated=False,
    )

    assert payload["content"] == "id: chat\nname: Chat Agent\n"
    assert payload["truncated"] is False


def test_declared_file_output_is_preserved_and_validated() -> None:
    data = {
        "filename": "tool.py",
        "language": "python",
        "mime_type": "text/x-python",
        "content": "def main():\n    return 'ok'\n",
        "size": 27,
        "truncated": False,
    }
    fixture = command_fixture_from_manifest(
        {
            "id": "file_result",
            "name": "File Result",
            "methods": [{"id": "make", "output": {"part_type": "file", "mode": "inline_text"}}],
            "commands": [{"name": "/file-result", "method": "make"}],
        },
        runtime=RuntimeWithResult(data),
    )
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/file-result ignored"))
    message = fixture.messages.list_messages(session.session_id)[-1]

    assert result.success is True
    assert not hasattr(result, "output_type")
    assert message.parts[0]["type"] == "file"
    assert message.parts[0]["content"] == data["content"]


def test_read_file_command_returns_file_part_for_source_yaml_env_and_markdown(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_FILE_ALLOWED_DIRS", str(ROOT))
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    py_result = run(fixture.runtime.handle_input(session, "/read-file agents/script_lifecycle_lab/agent.py"))
    yaml_result = run(fixture.runtime.handle_input(session, "/read-file agents/chat/agent.yaml"))
    env_result = run(fixture.runtime.handle_input(session, "/read-file .env.example"))
    md_result = run(fixture.runtime.handle_input(session, "/read-file README.md"))
    messages = fixture.messages.list_messages(session.session_id)

    assert not hasattr(py_result, "output_type")
    assert py_result.data[0]["type"] == "file"
    assert py_result.data[0]["language"] == "python"
    assert "\n    " in py_result.data[0]["content"]
    assert not hasattr(yaml_result, "output_type")
    assert yaml_result.data[0]["language"] == "yaml"
    assert not hasattr(env_result, "output_type")
    assert env_result.data[0]["language"] == "dotenv"
    assert not hasattr(md_result, "output_type")
    assert md_result.data[0]["language"] == "markdown"
    assert messages[-1].parts[0]["type"] == "file"


def test_success_event_bus_records_started_and_done() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/encode base64 hello"))
    events = fixture.events.list_events()

    assert "run_started" in [event.type for event in events]
    assert "run_completed" in [event.type for event in events]
    assert "run_done" in [event.type for event in events]
    assert "message_done" in [event.type for event in events]
    assert events[0].run_id == result.run_id
    assert all(event.run_id == result.run_id for event in events if event.run_id)


def test_failure_event_bus_records_started_and_failed() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/decode base64 invalid!!!"))
    events = fixture.events.list_events()

    assert "run_started" in [event.type for event in events]
    assert "run_failed" in [event.type for event in events]
    assert "message_done" in [event.type for event in events]
    assert events[0].run_id == result.run_id
    failed_event = next(event for event in events if event.type == "run_failed")
    assert failed_event.run_id == result.run_id
    assert failed_event.payload["error"] == "Invalid Base64 input."


def test_command_uses_current_args_not_session_history() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()
    fixture.messages.add_message(
        session_id=session.session_id,
        role="user",
        content="this previous message should not be encoded",
    )

    result = run(fixture.runtime.handle_input(session, "/encode base64 hello"))

    assert result.data[0]["content"] == "aGVsbG8="


def test_command_parser_preserves_multiline_args() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/encode base64 hello\n\nworld"))
    run_record = fixture.runs.get_run(result.run_id)

    assert result.success is True
    assert result.data[0]["content"] == "aGVsbG8KCndvcmxk"
    assert run_record.metadata["args"] == "base64 hello\n\nworld"


def test_failed_command_persists_capability_error_message_and_steps() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/pet new"))
    message = fixture.messages.list_messages(session.session_id)[-1]
    steps = fixture.runs.list_steps(result.run_id)

    assert result.success is False
    assert message.role == "assistant"
    assert message.speaker_type == "capability"
    assert message.speaker_id == "pet"
    assert message.origin == "command_result"
    assert message.parts[0]["type"] == "error"
    assert message.metadata["kind"] == "command_result"
    assert message.metadata["success"] is False
    assert [step.label for step in steps] == ["Resolving command", "Running command"]
    assert steps[-1].status == RunStepStatus.FAILED


def test_unknown_command_returns_structured_error_without_run() -> None:
    fixture = RuntimeFixture()
    session = fixture.sessions.create_session()

    result = run(fixture.runtime.handle_input(session, "/missing hello"))

    assert result.success is False
    assert result.run_id == ""
    assert result.error == "Unknown command: /missing"
    assert fixture.runs.list_runs(session.session_id) == []


def sample_attachment(name: str, data_url: str) -> dict:
    return {
        "id": name,
        "type": "image",
        "mime_type": "image/svg+xml",
        "name": name,
        "size": 120,
        "data_url": data_url,
    }
