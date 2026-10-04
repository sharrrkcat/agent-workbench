"""Local QQ transcript fixtures for browser workflows; no external connection."""

from types import SimpleNamespace


def install_qq_fixture(app):
    state = app.state.runtime_state
    state.qq.start = lambda: None

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

        async def send(action, params):
            return {"message_id": 9001}

        state.projects.save(project.model_copy(update={"connection_enabled": True}))
        state.qq.connections[project.id] = SimpleNamespace(ready=True, call=send)
        try:
            await state.qq.execute(batch)
        finally:
            state.projects.save(project)
            state.qq.connections.pop(project.id)
        return {"batch_id": batch.id, "run_id": batch.run_id}
