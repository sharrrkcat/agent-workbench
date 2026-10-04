"""Local QQ transcript fixtures for browser workflows; no external connection."""

from types import SimpleNamespace
from typing import Literal
import time


def install_qq_fixture(app):
    state = app.state.runtime_state
    state.qq.start = lambda: None

    async def execute(session, batch):
        project = state.projects.get(session.project_id)
        receipt = 9000
        async def send(action, params):
            nonlocal receipt
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
    async def reply(session_id: str, mode: Literal["limit", "missing"]):
        session = state.sessions.get_session(session_id)
        project = state.projects.get(session.project_id)
        now = time.time()
        await state.qq.ingest(project.id, {
            "post_type": "message", "self_id": project.bot_account, "message_type": "group",
            "group_id": session.target_id, "user_id": "9999", "message_id": time.time_ns(), "time": int(now),
            "sender": {"nickname": "QQ participant"},
            "message": [{"type": "text", "data": {"text": f"qq-{mode}-fixture bot"}}],
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
                            {"type": "image", "data": {}}],
            }, now=number / 100)
        batch = state.qq.store.freeze(session_id, project.batch_message_limit, 10)

        return await execute(session, batch)
