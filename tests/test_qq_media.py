"""QQ media ordering, acquisition, model requests and attachment ownership."""
import asyncio
from io import BytesIO
import json

from PIL import Image
import pytest

from ai_workbench.core.attachments import attachments_root, resolve_attachment_uri, save_attachment_from_upload
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.qq_media import QQMediaService, decode_image
from ai_workbench.core.qq_protocol import normalize
from ai_workbench.core.qq_segments import public_segments
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.db.qq_models import QQBatch, QQBinding, QQMedia
from tests.test_qqbot import qq_client, child, configure_execution, event, freeze, ingest, project
from tests.test_qq_reply_policy import execute_batch
from tests.tool_fixtures import completion, ok, tool_call


@pytest.fixture(autouse=True)
def isolated_attachments(tmp_path, monkeypatch):
    monkeypatch.setenv("COGITA_ATTACHMENTS_DIR", str(tmp_path / "attachments"))


def image_bytes(format="PNG", *, animated=False):
    output = BytesIO()
    image = Image.new("RGB", (12, 8), "red")
    options = {"save_all": True, "append_images": [Image.new("RGB", (12, 8), "blue")], "duration": 100, "loop": 0} if animated else {}
    image.save(output, format=format, **options)
    return output.getvalue()


def image_event(number=1, *, text="bot A", images=None):
    return {**event(number), "message": [{"type": "text", "data": {"text": text}},
        *(images or [{"type": "image", "data": {"url": "https://images.test/static"}},
                    {"type": "text", "data": {"text": " B "}},
                    {"type": "image", "data": {"url": "https://images.test/animated", "sub_type": 1}},
                    {"type": "text", "data": {"text": " C"}}])]}


def page(client, session):
    return ok(client.get(f"/api/qq/sessions/{session['session_id']}/messages"))["items"]


async def finish_pending(state):
    while state.qq.store.pending_media(limit=1) or state.qq.media.tasks:
        state.qq.media.tick()
        if state.qq.media.tasks:
            await asyncio.gather(*state.qq.media.tasks.values())


def prepare_images(monkeypatch):
    static, animated = image_bytes(), image_bytes("GIF", animated=True)
    async def fetch(url, policy, *, max_bytes):
        assert max_bytes == policy.max_response_bytes
        return (animated if url.endswith("animated") else static), url, "application/octet-stream"
    monkeypatch.setattr("ai_workbench.core.qq_media.fetch_bytes", fetch)
    return static, animated


def reply(upstream):
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "ack"})), completion(content="done")]


@pytest.mark.parametrize("format,animated", [("PNG", False), ("JPEG", False), ("WEBP", False),
    ("GIF", False), ("GIF", True), ("WEBP", True), ("PNG", True)])
def test_static_model_frames(format, animated):
    data = image_bytes(format, animated=animated)
    mime, suffix, width, height, frame = decode_image(data)
    assert (width, height) == (12, 8)
    assert suffix == (".jpg" if format == "JPEG" else "." + format.lower())
    assert (frame is not None) == (animated or format == "GIF")
    if frame:
        with Image.open(BytesIO(frame)) as image:
            assert image.format == "PNG" and not image.is_animated
            red, green, blue, _ = image.convert("RGBA").getpixel((0, 0))
            assert red > 240 and green < 10 and blue < 10


@pytest.mark.parametrize("cq", [False, True])
def test_protocol_positions_are_not_placeholder_searches(cq):
    message = "😀[图片][CQ:at,qq=42]A[CQ:image,url=https://images.test/a?x=1&#44;2]B[CQ:face,id=0][CQ:mface,emoji_id=abcd]"
    if not cq:
        message = [{"type": "text", "data": {"text": "😀[图片]"}}, {"type": "at", "data": {"qq": "42"}},
            {"type": "text", "data": {"text": "A"}}, {"type": "image", "data": {"url": "https://images.test/a?x=1,2"}},
            {"type": "text", "data": {"text": "B"}}, {"type": "face", "data": {"id": 0}},
            {"type": "mface", "data": {"emoji_id": "abcd"}}]
    values, keywords, media, _ = normalize({**event(), "message": message})
    refs = json.loads(values["references_json"])
    refs[0]["name"] = "Long member name"
    segments = public_segments(values["text"], json.dumps(refs), [QQMedia(id=i + 1, message_id=1, **item) for i, item in enumerate(media)])
    assert [part.type for part in segments] == ["text", "image", "text", "image", "image"]
    assert segments[0].text == "😀[图片]@Long member nameA"
    assert segments[2].text == "B"
    assert [part.kind for part in segments if part.type == "image"] == ["image", "face", "sticker"]
    assert json.loads(media[1]["source_json"])["face_id"] == "0"
    assert "images.test" not in keywords and "表情包" not in keywords


def test_image_setting_is_strict_and_the_only_model_switch(qq_client):
    client, state, _ = qq_client
    p, session, _ = configure_execution(client, state)
    assert p["image_input_enabled"] is False
    path = f"/api/projects/{p['id']}"
    for value in (None, 0, 1, "true", [], {}):
        assert client.patch(path, json={"image_input_enabled": value}).status_code == 422
        assert client.post("/api/projects", json={"kind": "qqbot", "name": "invalid", "bot_account": "98765",
            "websocket_url": "ws://localhost:3001", "image_input_enabled": value}).status_code == 422
    for enabled, attachment_policy in [(True, "none"), (False, "explicit")]:
        ok(client.patch(path, json={"image_input_enabled": enabled, "context_policy": {"include_attachments": attachment_policy}}))
        ok(client.patch(path, json={"name": "Renamed"}))
        assert ok(client.get(path))["image_input_enabled"] is enabled
        config = state.chat_service.resolve(state.sessions.get_session(session["session_id"]))
        assert config.context_policy.include_attachments == ("explicit" if enabled else "none")


def test_saved_images_join_only_current_model_requests(qq_client, monkeypatch, capsys):
    client, state, upstream = qq_client
    static, animated = prepare_images(monkeypatch)
    p, session, _ = configure_execution(client, state)
    ingest(client, state, p, image_event(), 1)
    assert [s["status"] for s in page(client, session)[0]["segments"] if s["type"] == "image"] == ["pending", "pending"]
    client.portal.call(finish_pending, state)
    row, = page(client, session)
    images = [s for s in row["segments"] if s["type"] == "image"]
    assert [s["status"] for s in images] == ["ready", "ready"]
    assert [s["type"] for s in row["segments"]] == ["text", "image", "text", "image", "text"]
    assert "images.test" not in json.dumps(row) and "source_json" not in row
    assert client.get('/api/attachments/' + images[1]["attachment"]["id"]).content == animated
    media = state.qq.store.message_media([row["id"]])[row["id"]]
    assert media[0].attachment.id == media[0].model_attachment.id
    assert media[1].attachment.id != media[1].model_attachment.id
    reply(upstream)
    first = freeze(state, session, 6)
    client.portal.call(state.qq.execute, first)
    assert state.qq.store.get(QQBatch, first.id).status == "done"
    assert isinstance(upstream.calls[0]["messages"][-1]["content"], str)
    assert "[图片]" in upstream.calls[0]["messages"][-1]["content"]
    assert state.runs.get_config_snapshot(first.run_id)["context_policy"]["include_attachments"] == "none"
    ok(client.patch(f"/api/projects/{p['id']}", json={"image_input_enabled": True}))
    upstream.calls.clear()
    reply(upstream)
    ingest(client, state, p, image_event(2), 10)
    client.portal.call(finish_pending, state)
    second = freeze(state, session, 15)
    client.portal.call(state.qq.execute, second)
    assert state.qq.store.get(QQBatch, second.id).status == "done"
    inputs = [m["content"] for m in upstream.calls[0]["messages"] if m["role"] == "user"]
    assert len(inputs) == 2
    assert isinstance(inputs[0], str) and "[图片]" in inputs[0] and "[表情包]" in inputs[0]
    for content in inputs[1:]:
        assert [s["type"] for s in content] == ["text", "image_url", "text", "image_url", "text"]
        assert content[0]["text"].endswith("bot A") and content[2]["text"] == " B " and content[4]["text"] == " C"
        assert content[3]["image_url"]["url"].startswith("data:image/png;base64,")
    run = ok(client.get(f"/api/runs/{second.run_id}"))
    step = next(s for s in run["steps"] if s.get("metadata", {}).get("context", {}).get("available"))
    detail = ok(client.get(f"/api/runs/{second.run_id}/steps/{step['step_id']}/context"))
    sources = [s for s in detail["sources"] if s["kind"] == "attachment"]
    assert [s["part_index"] for s in sources] == [1, 3]
    assert "data:image" not in json.dumps(detail)
    trimmed = build_qq_context(state.qq.store, state.messages, session["session_id"], "next", ContextPolicy(max_messages=2), None)
    assert not any(s.kind == "attachment" for s in trimmed.trace.sources)
    assert ok(client.post("/api/data/attachments/scan-orphans"))["orphan_count"] == 0
    assert client.delete('/api/attachments/' + images[0]["attachment"]["id"]).status_code == 409
    if hasattr(state.messages, "engine"):
        from scripts.cleanup_attachments import main
        orphan = save_attachment_from_upload("orphan.png", "image/png", static)
        orphan_path = resolve_attachment_uri(orphan["uri"])
        args = ["--database-url", state.database_url]
        assert main(args) == 0 and orphan_path.exists()
        assert "orphan count: 1" in capsys.readouterr().out
        assert main([*args, "--apply"]) == 0 and not orphan_path.exists()
        assert "deleted count: 1" in capsys.readouterr().out
        assert all(resolve_attachment_uri(m.attachment.uri).exists() for m in media)


def test_acquisition_is_bounded_nonblocking_and_restarts_pending_work(qq_client, monkeypatch):
    client, state, _ = qq_client
    p = project(client, keywords=["bot"])
    session = child(client, p)
    async def scenario():
        gates, started, active, peak = {}, [], 0, 0
        async def fetch(url, policy, *, max_bytes):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            started.append(url)
            gate = gates.setdefault(url, asyncio.Event())
            try:
                await gate.wait()
                return image_bytes(), url, "image/png"
            finally:
                active -= 1
        monkeypatch.setattr("ai_workbench.core.qq_media.fetch_bytes", fetch)
        data = image_event(images=[{"type": "image", "data": {"url": f"https://images.test/{n}"}} for n in range(6)])
        await state.qq.ingest(p["id"], data, now=1)
        await state.qq.ingest(p["id"], data, now=2)
        state.qq.media.tick()
        await asyncio.sleep(0)
        assert len(started) == 4 and peak == 4
        await asyncio.wait_for(state.qq.ingest(p["id"], event(2, "next message"), now=2), 1)
        for url in reversed(started):
            gates[url].set()
        await asyncio.gather(*state.qq.media.tasks.values())
        state.qq.media.tick()
        await asyncio.sleep(0)
        assert len(started) == 6
        await state.qq.media.close()
        assert len(state.qq.store.pending_media(limit=10)) == 2
        state.qq.media = QQMediaService(state, state.qq.store, state.qq.connections)
        for gate in gates.values():
            gate.set()
        await finish_pending(state)
        assert peak == 4
    client.portal.call(scenario)
    rows = page(client, session)
    assert len(rows) == 2
    assert [s["media_id"] for s in rows[1]["segments"] if s["type"] == "image"] == list(range(1, 7))
    assert all(s["status"] == "ready" for s in rows[1]["segments"] if s["type"] == "image")


@pytest.mark.parametrize("failure", ["corrupt", "oversize", "private", "remote_path", "unknown_face"])
def test_unavailable_media_stays_in_place_and_does_not_trigger(qq_client, monkeypatch, failure):
    client, state, _ = qq_client
    p = project(client, keywords=["图片", "表情包"])
    session = child(client, p)
    source = {"url": "https://images.test/bad"}
    kind = "image"
    if failure == "private":
        source = {"url": "http://127.0.0.1/private"}
    elif failure == "remote_path":
        source = {"file": "C:/private/server.png"}
    elif failure == "unknown_face":
        kind, source = "face", {"id": 999999}
    else:
        async def fetch(url, policy, *, max_bytes):
            if failure == "oversize":
                raise ToolExecutionError("NETWORK_RESPONSE_TOO_LARGE", "too large")
            return b"not an image", url, "image/png"
        monkeypatch.setattr("ai_workbench.core.qq_media.fetch_bytes", fetch)
    ingest(client, state, p, image_event(text="", images=[{"type": kind, "data": source}]), 1)
    client.portal.call(finish_pending, state)
    row, = page(client, session)
    assert state.qq.store.get(QQBinding, session["session_id"]).deadline is None
    segment, = row["segments"]
    assert segment["status"] == "failed" and segment["attachment"] is None
    assert segment["error_code"]
    if failure == "unknown_face":
        assert "999999" in segment["label"]


def test_get_image_fallback_and_system_face_zero(qq_client, monkeypatch):
    client, state, _ = qq_client
    p, session, connection = configure_execution(client, state)
    urls, calls = [], []
    async def fetch(url, policy, *, max_bytes):
        urls.append(url)
        if url.endswith("expired"):
            raise ToolExecutionError("NETWORK_HTTP_ERROR", "expired")
        return image_bytes(), url, "image/png"
    async def call(action, params):
        calls.append((action, params))
        return {"url": "https://images.test/resolved", "file": "C:/not-local.png"}
    monkeypatch.setattr("ai_workbench.core.qq_media.fetch_bytes", fetch)
    connection.call = call
    ingest(client, state, p, image_event(images=[{"type": "image", "data": {"url": "https://images.test/expired", "file": "remote-id"}},
        {"type": "face", "data": {"id": 0}}]), 1)
    client.portal.call(finish_pending, state)
    assert calls == [("get_image", {"file": "remote-id"})]
    assert "https://images.test/resolved" in urls and any(url.endswith("/s0.gif") for url in urls)
    assert all(s["status"] == "ready" for s in page(client, session)[0]["segments"] if s["type"] == "image")


@pytest.mark.parametrize("scope", ["message", "session", "project"])
def test_deleted_media_cannot_restore_or_overwrite_new_records(qq_client, monkeypatch, scope):
    client, state, _ = qq_client
    prepare_images(monkeypatch)
    p = project(client)
    session = child(client, p)
    ingest(client, state, p, image_event(), 1)
    row, = page(client, session)
    pending = state.qq.store.pending_media(limit=10)
    target = f"/api/qq/sessions/{session['session_id']}/messages/{row['id']}" if scope == "message" else f"/api/{scope}s/{session['session_id'] if scope == 'session' else p['id']}"
    assert client.delete(target).status_code == 200
    if scope == "project":
        p = project(client)
    if scope != "message":
        session = child(client, p)
    ingest(client, state, p, image_event(2), 2)
    new_ids = {m.id for m, _ in state.qq.store.pending_media(limit=10)}
    assert not new_ids.intersection({m.id for m, _ in pending})
    for media, project_id in pending:
        client.portal.call(state.qq.media.acquire, media, project_id)
    assert all(state.qq.store.get(QQMedia, key).status == "pending" for key in new_ids)
    assert not any(path.is_file() for path in attachments_root().rglob("*"))


def test_snapshot_keeps_only_referenced_static_frame_until_reply_deleted(qq_client, monkeypatch):
    client, state, upstream = qq_client
    prepare_images(monkeypatch)
    p, session, _ = configure_execution(client, state, image_input_enabled=True)
    ingest(client, state, p, image_event(), 1)
    client.portal.call(finish_pending, state)
    row, = page(client, session)
    media = state.qq.store.message_media([row["id"]])[row["id"]]
    paths = [resolve_attachment_uri(m.attachment.uri) for m in media]
    model_paths = [resolve_attachment_uri(m.model_attachment.uri) for m in media]
    reply(upstream)
    batch = freeze(state, session, 6)
    client.portal.call(state.qq.execute, batch)
    assert state.qq.store.get(QQBatch, batch.id).status == "done"
    assert client.delete(f"/api/qq/sessions/{session['session_id']}/messages/{row['id']}").status_code == 200
    assert not paths[1].exists() and all(path.exists() for path in model_paths)
    assert ok(client.post("/api/data/attachments/scan-orphans"))["orphan_count"] == 0
    assert client.delete(f"/api/runs/{batch.run_id}").status_code == 200
    assert not any(path.exists() for path in model_paths)


def test_pending_timeout_preserves_run_setting_and_captured_request(qq_client, monkeypatch):
    client, state, upstream = qq_client
    p, session, _ = configure_execution(client, state, image_input_enabled=True)
    ingest(client, state, p, image_event(images=[{"type": "image", "data": {"url": "https://images.test/slow"}}]), 1)
    batch = freeze(state, session, 6)
    reply(upstream)
    monkeypatch.setattr("ai_workbench.core.qq_media.MEDIA_WAIT_SECONDS", .05)
    async def scenario():
        release, started = asyncio.Event(), asyncio.Event()
        async def fetch(url, policy, *, max_bytes):
            started.set()
            await release.wait()
            return image_bytes(), url, "image/png"
        monkeypatch.setattr("ai_workbench.core.qq_media.fetch_bytes", fetch)
        task = asyncio.create_task(state.qq.execute(batch))
        await asyncio.wait_for(started.wait(), 1)
        state.project_service.update(p["id"], {"image_input_enabled": False})
        await asyncio.wait_for(task, 5)
        assert state.qq.store.get(QQBatch, batch.id).status == "done"
        assert state.runs.get_config_snapshot(batch.run_id)["context_policy"]["include_attachments"] == "explicit"
        steps = [step for step in state.runs.list_steps(batch.run_id) if step.kind == "model"]
        snapshots = [state.runs.get_context_snapshot(step.step_id) for step in steps]
        assert all(any(exclusion.reason == "qq_image_unavailable" for exclusion in snapshot.exclusions) for snapshot in snapshots)
        assert all(snapshot.attachment_ids == [] for snapshot in snapshots)
        release.set()
        await finish_pending(state)
        assert [state.runs.get_context_snapshot(step.step_id) for step in steps] == snapshots
    client.portal.call(scenario)
    assert isinstance(upstream.calls[0]["messages"][-1]["content"], str)
    upstream.calls.clear()
    reply(upstream)
    execute_batch(client, state, p, session, 2)
    assert all(isinstance(m["content"], str) for m in upstream.calls[0]["messages"])
    ok(client.patch(f"/api/projects/{p['id']}", json={"image_input_enabled": True}))
    upstream.calls.clear()
    reply(upstream)
    execute_batch(client, state, p, session, 3)
    assert all(isinstance(m["content"], str) for m in upstream.calls[0]["messages"])
