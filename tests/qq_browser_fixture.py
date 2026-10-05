"""Local QQ transcript fixtures for browser workflows; no external connection."""

from types import SimpleNamespace
from typing import Literal
from io import BytesIO
import time

from PIL import Image
from fastapi import Body
from ai_workbench.core.qq_media import QQMediaService
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.db.qq_models import QQMessage


def install_qq_fixture(app):
    state = app.state.runtime_state
    state.qq.start = lambda: None

    async def complete_media(session_id, *, include_old):
        service = QQMediaService(state, state.qq.store, {})
        async def download(media, project_id, settings):
            if media.source.file == "fixture:failed":
                raise ToolExecutionError("QQ_IMAGE_UNAVAILABLE", "Fixture unavailable")
            data = BytesIO()
            animated = media.source.file == "fixture:animated"
            image = Image.new("RGB", (640, 480), "#4e8db0")
            if animated:
                image.save(data, "GIF", save_all=True, append_images=[Image.new("RGB", image.size, "#be7656")], duration=300, loop=0)
            else:
                image.save(data, "PNG")
            return data.getvalue()
        service.download = download
        for row in state.qq.store.page(QQMessage, session_id, limit=100)["items"]:
            for media in state.qq.store.message_media([row["id"]])[row["id"]]:
                if media.status == "pending" and (include_old or media.source.file != "fixture:old"):
                    await service.acquire(media, state.sessions.get_session(session_id).project_id)

    @app.post("/__test__/qq/{session_id}/media/complete")
    async def media_complete(session_id: str):
        await complete_media(session_id, include_old=True)
        return {"ok": True}

    @app.post("/__test__/qq/{session_id}/media/description")
    async def media_description(session_id: str, description: str = Body(embed=True)):
        rows = state.qq.store.page(QQMessage, session_id, limit=100)["items"]
        assets = {media.asset_id for items in state.qq.store.message_media([row["id"] for row in rows]).values()
            for media in items if media.asset_id is not None and media.kind != "face"}
        for asset_id in assets:
            state.qq.store.update_description(asset_id, description)
        return {"ok": True}

    @app.post("/__test__/qq/{session_id}/media")
    async def media_records(session_id: str):
        session = state.sessions.get_session(session_id)
        project = state.projects.get(session.project_id)
        def text(value):
            return {"type": "text", "data": {"text": value}}
        def image(file, **values):
            return {"type": "image", "data": {"file": file, **values}}
        contents = {
            1: [text("Older "), image("fixture:old"), text(" end")],
            57: [text("Before "), image("fixture:image"), text(" between "), image("fixture:animated", sub_type=1), text(" after")],
            58: [image("fixture:animated", sub_type=1)],
            59: [text("Face "), {"type": "face", "data": {"id": 0}}, text(" end")],
            60: [text("Failed "), image("fixture:failed"), text(" end")],
        }
        for number in range(1, 61):
            await state.qq.ingest(project.id, {"post_type": "message", "self_id": project.bot_account,
                "message_type": "group", "group_id": session.target_id, "user_id": "9999",
                "message_id": number, "time": 1700000000 + number, "sender": {"nickname": "QQ participant"},
                "message": contents.get(number, [text(f"Record {number} bot")])}, now=number / 100)
        state.qq.store.freeze(session_id, 3, 10)
        await complete_media(session_id, include_old=False)
        return {"ids": {row["external_id"]: row["id"] for row in state.qq.store.page(QQMessage, session_id, limit=100)["items"]}}

    async def execute(session, batch):
        project = state.projects.get(session.project_id)
        receipt = 9000
        async def send(action, params):
            nonlocal receipt
            if action == "get_group_member_info":
                return {"user_id": params["user_id"], "card": "QQ bot" if str(params["user_id"]) == project.bot_account else "Mentioned member"}
            receipt += 1
            return {"message_id": receipt}
        state.projects.save(project.model_copy(update={"connection_enabled": True}))
        state.qq.connections[project.id] = SimpleNamespace(ready=True, call=send)
        try:
            await state.qq.execute(batch)
        finally:
            state.projects.save(project)
            state.qq.connections.pop(project.id)
        return {"batch_id": batch.id, "run_id": batch.run_id}

    @app.post("/__test__/qq/{session_id}/reply/{mode}")
    async def reply(session_id: str, mode: Literal["limit", "missing", "skip"]):
        session = state.sessions.get_session(session_id)
        project = state.projects.get(session.project_id)
        now = time.time()
        await state.qq.ingest(project.id, {
            "post_type": "message", "self_id": project.bot_account, "message_type": "group",
            "group_id": session.target_id, "user_id": "9999", "message_id": time.time_ns(), "time": int(now),
            "sender": {"nickname": "QQ participant"},
            "message": [{"type": "text", "data": {"text": f"qq-{mode}-fixture" + ("" if mode == "skip" else " bot")}}],
        }, now=now)
        return await execute(session, state.qq.store.freeze(session_id, project.batch_message_limit, now + 5))

    @app.post("/__test__/qq/{session_id}")
    async def populate(session_id: str):
        session = state.sessions.get_session(session_id)
        project = state.projects.get(session.project_id)
        for number in range(1, 66):
            await state.qq.ingest(project.id, {
                "post_type": "message", "self_id": project.bot_account,
                "message_type": "group" if session.target_kind == "group" else "private",
                "group_id": session.target_id, "user_id": session.target_id if session.target_kind == "friend" else "9999",
                "message_id": number, "time": 1700000000 + number,
                "sender": {"nickname": "QQ participant"},
                "message": [{"type": "text", "data": {"text": f"Record {number}" if number < 65 else "qq-fixture bot"}},
                            *([{"type": "at", "data": {"qq": project.bot_account}},
                               {"type": "at", "data": {"qq": "8888"}}] if number == 65 else []),
                            {"type": "image", "data": {}}],
            }, now=number / 100)
        batch = state.qq.store.freeze(session_id, project.batch_message_limit, 10)

        return await execute(session, batch)
