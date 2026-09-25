import asyncio
import base64
from contextlib import asynccontextmanager
from io import BytesIO
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
import pytest

from ai_workbench.api.main import create_app
from ai_workbench.core.attachments import resolve_attachment_uri, save_attachment_from_upload
from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.harness.schema import HarnessState
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.images import prepare_local_images, resolve_context_images
from ai_workbench.core.models.inventory import inventory
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes.schema import model_path
from ai_workbench.core.models.resolution import configure_profile, require_directory
from ai_workbench.core.models.inspection import inspect_local_directory
from ai_workbench.workers.model_catalog import DirectoryInformation
from ai_workbench.core.models.schema import ChatRequest, ModelProfile
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.stores import MessageStore
from ai_workbench.workers.transformers_server import build_app
from tests.model_fixtures import configure_model, write_local_model, resolve_local_profile
from tests.tool_fixtures import ToolOpenAI, completion, ok, tool_call


def image_bytes(format_="PNG", color="red", size=(16, 12), **kwargs):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=format_, **kwargs)
    return output.getvalue()


def part(data=None, mime="image/png", **options):
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64," + base64.b64encode(data if data is not None else image_bytes()).decode(), **options}}


def request(*parts, **options):
    return ChatRequest(model="local", messages=[{"role": "user", "content": list(parts)}], **options)


def profile(engine="llama-server", **options):
    value = ModelProfile(name="Local", alias="local", kind="llm", model_ref="llms/a",
        capabilities={"vision": True, "streaming": True}, source={"type": "local", "execution_options":
            {"device": "cpu", **options}})
    # Image preprocessing tests start after the directory-resolution boundary.
    value._directory = DirectoryInformation(kind='llm', model_ref='llms/a', engine=engine,
        main_model_ref='llms/a/model.gguf', mmproj_ref='llms/a/mmproj-F16.gguf', model_files=['llms/a/model.gguf'])
    return configure_profile(value)


def manager(root):
    return ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=SimpleNamespace(root=root))


@pytest.mark.parametrize("format_,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_local_input_normalizes_static_formats_without_modifying_the_request(format_, mime):
    original = request(part(image_bytes(format_), mime))
    prepared = prepare_local_images(profile(), original)
    assert original.messages[0].content[0].image_url.url.startswith(f"data:{mime};base64,")
    image = Image.open(BytesIO(base64.b64decode(prepared.messages[0].content[0].image_url.url.split(",")[1])))
    assert image.format == "PNG" and image.mode == "RGB" and image.size == (16, 12)
    assert image.getpixel((5, 5))[0] > 240


def test_image_orientation_and_transparency():
    output = BytesIO()
    image = Image.new("RGBA", (8, 12), (255, 0, 0, 0))
    exif = Image.Exif()
    exif[274] = 6
    image.save(output, format="PNG", exif=exif)
    prepared = prepare_local_images(profile(), request(part(output.getvalue())))
    normalized = Image.open(BytesIO(base64.b64decode(prepared.messages[0].content[0].image_url.url.split(",")[1])))
    assert normalized.size == (12, 8) and normalized.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("data,mime", [(b"corrupt", "image/png"), (image_bytes(), "image/jpeg"), (b"<svg/>", "image/svg+xml")])
def test_invalid_images_fail_explicitly(data, mime):
    with pytest.raises(ModelError) as error:
        prepare_local_images(profile(), request(part(data, mime)))
    assert error.value.code == "INVALID_IMAGE"


@pytest.mark.parametrize("format_,mime", [("PNG", "image/png"), ("WEBP", "image/webp")])
def test_animated_images_are_rejected(format_, mime):
    output = BytesIO()
    Image.new("RGB", (16, 16), "red").save(output, format=format_, save_all=True,
        append_images=[Image.new("RGB", (16, 16), "blue")], duration=100, loop=0)
    with pytest.raises(ModelError) as error:
        prepare_local_images(profile(), request(part(output.getvalue(), mime)))
    assert error.value.code == "INVALID_IMAGE"


def test_full_local_request_limit_includes_json_defaults_and_image_expansion(monkeypatch):
    from ai_workbench.core.models import images
    monkeypatch.setattr(images, "MAX_LOCAL_CHAT_BYTES", 4096)
    huge = request({"type": "text", "text": "界" * 2000})
    with pytest.raises(ModelError) as error:
        prepare_local_images(profile(), huge)
    assert error.value.status == 413
    # A compact lossy input expands beyond the wire budget as RGB PNG.
    output = BytesIO()
    Image.effect_noise((96, 96), 90).convert("RGB").save(output, format="JPEG", quality=1)
    compact = request(part(output.getvalue(), "image/jpeg"))
    assert len(compact.model_dump_json()) < 4096
    with pytest.raises(ModelError) as error:
        prepare_local_images(profile(), compact)
    assert error.value.code == "REQUEST_TOO_LARGE"
    defaults = profile().model_copy(update={"parameters": {"stop": ["x" * 5000]}})
    with pytest.raises(ModelError):
        prepare_local_images(defaults, request({"type": "text", "text": "small"}))


@pytest.mark.parametrize("reference", ["../mmproj.gguf", "D:/mmproj.gguf", "llms/../mmproj.gguf", "llms/projector.bin", ""])
def test_gguf_projector_cannot_be_supplied_as_an_execution_option(reference):
    with pytest.raises(ValidationError):
        profile(mmproj_ref=reference)


def test_projector_presence_identity_and_inventory(tmp_path):
    with pytest.raises(ValidationError):
        profile(mmproj_ref=None)
    assert profile("transformers").capabilities.vision
    directory = write_local_model(tmp_path, 'llms/a', 'llama-server')
    (directory / 'mmproj-F16.gguf').write_bytes(b'fixture')
    service = manager(tmp_path)
    original = profile()
    assert service.execution_key(original) == service.execution_key(profile())
    text_only = ModelProfile(**{**original.model_dump(), 'capabilities': {'vision': False}})
    assert service.execution_key(original) != service.execution_key(text_only)
    assert service.execution_key(original) != service.execution_key(profile(device="cuda"))
    (directory / 'mmproj-Q8.gguf').write_bytes(b'fixture')
    items = inventory(tmp_path, "llm")
    assert len(items) == 1
    assert items[0]['model_ref'] == 'llms/a'
    assert inspect_local_directory(tmp_path, 'llm', 'llms/a').diagnostics[0].code == 'ambiguous_projector'
    unresolved = resolve_local_profile(tmp_path, ModelProfile(**original.model_dump()))
    with pytest.raises(ModelError):
        require_directory(unresolved)
    with pytest.raises(ValueError):
        model_path(tmp_path, "../escape.gguf")


def test_local_manager_prepares_images_before_admission_off_the_event_loop(tmp_path, monkeypatch):
    import threading
    from ai_workbench.core.models import manager as manager_module
    service = manager(tmp_path)
    local = service.profiles.create(profile())
    on_loop = threading.get_ident()
    prepare = prepare_local_images
    admitted = []

    def checked_prepare(*args):
        assert threading.get_ident() != on_loop
        return prepare(*args)

    class Adapter:
        async def chat(self, _profile, value):
            admitted.append(value)
            return "accepted"

    @asynccontextmanager
    async def lease(_profile):
        yield Adapter()

    monkeypatch.setattr(manager_module, "prepare_local_images", checked_prepare)
    monkeypatch.setattr(service, "_lease", lease)
    assert asyncio.run(service.chat(local.id, request(part(image_bytes("JPEG"), "image/jpeg")))) == "accepted"
    assert admitted[0].messages[0].content[0].image_url.url.startswith("data:image/png;base64,")
    with pytest.raises(ModelError):
        asyncio.run(service.chat(local.id, request(part(b"corrupt"))))
    assert len(admitted) == 1


@pytest.mark.parametrize("mode,history_images", [("none", 0), ("current_message", 0), ("session", 1), ("recent_messages", 0), ("selected_message", 1)])
def test_context_selection_keeps_images_with_their_messages(mode, history_images):
    store = MessageStore()
    first = store.add_message("s", "user", "first", metadata={"attachments": [{"type": "image", "uri": "local://attachments/aaaa.png"}]})
    store.add_message("s", "assistant", "answer", speaker_name="Alice")
    current = store.add_message("s", "user", "", metadata={"attachments": [{"type": "image", "uri": "local://attachments/bbbb.png"}]})
    policy = ContextPolicy(mode=mode, **({"max_messages": 1} if mode == "recent_messages" else {}))
    built = ContextBuilder(store).build("s", "", policy, current_message_id=current.message_id, source_message_id=first.message_id)
    serialized = json.dumps(built.messages)
    assert serialized.count('"attachment_image"') == history_images + 1
    assert "bbbb.png" in serialized
    if history_images:
        assert serialized.index("aaaa.png") < serialized.index("bbbb.png")


def test_budgeting_and_attachment_switch_happen_before_reading_images(tmp_path, monkeypatch):
    monkeypatch.setenv("COGITA_ATTACHMENTS_DIR", str(tmp_path))
    saved = save_attachment_from_upload("picture.png", "image/png", image_bytes())
    store = MessageStore()
    first = store.add_message("s", "user", "", metadata={"attachments": [saved]})
    builder = ContextBuilder(store)
    selected = builder.build("s", "again", ContextPolicy(mode="selected_message", max_chars=200), source_message_id=first.message_id)
    resolved = asyncio.run(resolve_context_images(selected.messages, vision=True, max_image_bytes=10000))
    assert resolved[0]["content"][-1]["image_url"]["url"].startswith("data:image/png;base64,")
    path = resolve_attachment_uri(saved["uri"])
    path.unlink()
    # Neither a character-pruned image nor excluded attachments should be opened.
    for policy in (ContextPolicy(mode="session", max_chars=5), ContextPolicy(mode="session", include_attachments="none")):
        messages = builder.build("s", "again", policy).messages
        assert asyncio.run(resolve_context_images(messages, vision=False, max_image_bytes=10000)) == messages
    with pytest.raises(ModelError) as error:
        asyncio.run(resolve_context_images(selected.messages, vision=True, max_image_bytes=10000))
    assert error.value.code == "ATTACHMENT_NOT_FOUND"
    with pytest.raises(ModelError) as error:
        asyncio.run(resolve_context_images(selected.messages, vision=False, max_image_bytes=10000))
    assert error.value.code == "UNSUPPORTED_CAPABILITY"
    invalid = [{"role": "user", "content": [{"type": "attachment_image", "attachment_id": "../../secret.png"}]}]
    with pytest.raises(ModelError) as error:
        asyncio.run(resolve_context_images(invalid, vision=True, max_image_bytes=10000))
    assert error.value.code == "INVALID_IMAGE"


@pytest.mark.parametrize("stream", [False, True])
def test_external_local_errors_precede_loading_and_stream_headers(tmp_path, stream):
    app = create_app(root=tmp_path, use_memory=True)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        state = app.state.runtime_state
        local = state.model_profiles.create(profile().model_copy(update={"external_enabled": True}))
        state.model_settings.patch({"external_enabled": True, "external_api_key": "test-key", "max_request_mb": 1})
        headers = {"Authorization": "Bearer test-key"}
        for image, code, status in ((part(b"invalid"), "INVALID_IMAGE", 422),
                ({"type": "image_url", "image_url": {"url": "https://example.test/image.png"}}, "UNSUPPORTED_CAPABILITY", 422),
                (part(detail="high"), "UNSUPPORTED_CAPABILITY", 422)):
            response = client.post("/v1/chat/completions", headers=headers, json=request(image, stream=stream).model_dump(exclude_none=True))
            assert response.status_code == status and response.json()["error"]["code"] == code
            assert response.headers["content-type"].startswith("application/json")
        response = client.post("/v1/chat/completions", headers=headers, json={"model": local.alias,
            "messages": [{"role": "user", "content": "x" * (1024 * 1024)}], "stream": stream})
        assert response.status_code == 413
        assert state.model_manager._slots == {}


@pytest.mark.parametrize("memory", [True, False], ids=["memory", "sqlite"])
def test_images_survive_approval_history_retry_edit_and_cleanup(tmp_path, monkeypatch, memory):
    monkeypatch.setenv("COGITA_ATTACHMENTS_DIR", str(tmp_path / "data/attachments"))
    upstream = ToolOpenAI(completion(tool_call("read_file", {"path": "data/knowledge/note.txt"})), completion(content="seen"))
    note = tmp_path / "data/knowledge/note.txt"
    note.parent.mkdir(parents=True)
    note.write_text("fixture", encoding="utf-8")
    app = create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'test.db'}", adapter_factory=upstream.factory)
    with TestClient(app) as client:
        configure_model(client, capabilities={"vision": True, "tools": True, "streaming": True})
        ok(client.patch("/api/settings/general", json={"auto_generate_session_titles": False}))
        attachment = ok(client.post("/api/attachments", files={"file": ("picture.png", image_bytes(), "image/png")}))
        session = ok(client.post("/api/sessions", json={"harness_enabled": True, "tools_allowed": ["read_file"]}))
        state = app.state.runtime_state
        path = f"/api/sessions/{session['session_id']}/messages"
        pending = ok(client.post(path, json={"content": "", "attachments": [attachment]}))
        assert pending["run"]["status"] == "WAITING_FOR_USER"
        run_id = pending["run"]["run_id"]
        saved = state.runs.get_harness_state(run_id)
        assert "attachment_image" in json.dumps(saved) and "base64" not in json.dumps(saved)
        HarnessState.model_validate(saved)
        user = next(item for item in pending["messages"] if item["role"] == "user")
        assert user["parts"] == [] and user["metadata"]["attachments"][0]["uri"] == attachment["uri"]
        assert "base64" not in json.dumps(ok(client.get(path)))
        resumed = ok(client.post(f"/api/tools/approvals/{run_id}", json={"decision": "approve"}))
        assert resumed["run"]["status"] == "DONE" and state.runs.get_harness_state(run_id) == {}
        expected = part()["image_url"]["url"]
        assert expected in json.dumps(upstream.calls[-1])
        assert "base64" not in json.dumps(ok(client.get(f"/api/runs/{run_id}/events")))
        retried = ok(client.post(f"/api/runs/{run_id}/retry"))
        assert retried["success"] and expected in json.dumps(upstream.calls[-1])
        edited = ok(client.post(f"/api/messages/{user['message_id']}/edit", json={"content": "edited"}))
        assert edited["success"] and expected in json.dumps(upstream.calls[-1])
        assert "edited" in json.dumps(upstream.calls[-1])
        ok(client.post(path, json={"content": "follow up"}))
        assert expected in json.dumps(upstream.calls[-1])
        image_path = resolve_attachment_uri(attachment["uri"])
        ok(client.delete(f"/api/messages/{user['message_id']}"))
        assert not image_path.exists()


def test_provider_retains_remote_images_and_detail_options(tmp_path):
    upstream = ToolOpenAI()
    app = create_app(root=tmp_path, use_memory=True, adapter_factory=upstream.factory)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        configure_model(client, capabilities={"vision": True})
        ok(client.patch("/api/models/settings", json={"external_enabled": True, "external_api_key": "test-key"}))
        image = {"type": "image_url", "image_url": {"url": "https://example.test/image.webp", "detail": "high"}}
        response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-key"}, json=request(image).model_dump(exclude_none=True))
        assert response.status_code == 200
        assert upstream.calls[-1]["messages"][0]["content"] == [image]


def test_worker_rejects_images_when_processor_reports_text_only():
    class Engine:
        metadata = {"vision": False}

        def close(self):
            pass

        async def chat(self, *_):
            raise AssertionError("A text-only processor must never receive images")

    with TestClient(build_app(Engine(), "token")) as client:
        body = request(part()).model_dump(exclude_none=True)
        body["model"] = "managed"
        response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer token"}, json=body)
        assert response.status_code == 422 and response.json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"
