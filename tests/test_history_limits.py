import json

from sqlalchemy import text
import pytest
from sqlmodel import Session as DbSession

from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.stores import MessageStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import MessageRecord, ProjectRecord, RunRecord, SessionRecord


@pytest.mark.parametrize("enabled", [True, False])
def test_projection_uses_selected_eligible_history_and_keeps_current(enabled):
    store = MessageStore()
    for index in range(25):
        store.add_message("s", "user" if index % 2 == 0 else "assistant", f"history-{index}")
    selected = store.list_messages("s")[-5:]
    selected.append(store.add_message("s", "assistant", "EXCLUDED", metadata={"incomplete": True}))
    current = store.add_message("s", "user", "current")
    result = ContextBuilder(store).build("s", "current", ContextPolicy(history_enabled=enabled),
        current_message_id=current.message_id, history=selected)
    assert [m["content"] for m in result.messages] == ([f"history-{i}" for i in range(20, 25)] if enabled else []) + ["current"]


def test_history_disabled_never_consumes_history_iterator():
    def unreadable():
        pytest.fail("History disabled must not read history")
        yield
    result = ContextBuilder(MessageStore()).build("s", "large current" * 1000,
        ContextPolicy(history_enabled=False), history=unreadable())
    assert len(result.messages) == 1 and result.messages[0]["content"] == "large current" * 1000


@pytest.mark.parametrize("mode", ["session", "recent_messages", "current_message", "selected_message", "none"])
def test_migration_removes_only_retired_fields_without_mapping_modes(tmp_path, mode):
    engine = get_engine(f"sqlite:///{tmp_path / 'history.db'}")
    migrations.upgrade(engine, migrations.MODEL_REQUEST_OPTIONS_REVISION)
    policy = {"mode": mode, "max_messages": None, "max_chars": 200, "include_attachments": "none"}
    expected_policy = {key: value for key, value in policy.items() if key != "mode"}
    config = {"context_policy": policy, "model_profile_id": "model", "reasoning": False}
    expected_config = {**config, "context_policy": expected_policy}
    metadata = {"input_message_id": "message", "context_source_message_id": "source", "configuration": config}
    continuation = {"base_messages": [{"role": "user", "content": "saved input"}], "awaiting_approval": "call"}
    files = [tmp_path / "data" / folder / "keep.bin" for folder in ("models", "attachments", "runtimes")]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"keep")
    with DbSession(engine) as db:
        for kind in ("workspace", "timeline"):
            db.add(ProjectRecord(id=kind, kind=kind, name=kind, configuration_json=json.dumps(config)))
        db.commit()
        for session_id, kind, project_id, title, waiting, configuration in (
            ("ordinary", "ordinary", None, "Saved title", "run", config),
            ("workspace", "workspace", "workspace", "", None, {"overrides": config}),
            ("inherited", "workspace", "workspace", "", None, {"overrides": {}}),
        ):
            db.execute(text("INSERT INTO sessionrecord (session_id, kind, project_id, title, waiting_run_id, "
                "configuration_json, title_generation_state, title_generation_metadata_json, created_at, updated_at) "
                "VALUES (:id, :kind, :project, :title, :waiting, :config, 'pending', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                {"id": session_id, "kind": kind, "project": project_id, "title": title,
                 "waiting": waiting, "config": json.dumps(configuration)})
        db.add(RunRecord(run_id="run", session_id="ordinary", persona_id="persona", kind="chat", status="WAITING_FOR_USER",
                         config_snapshot_json=json.dumps(config), metadata_json=json.dumps(metadata),
                         harness_state_json=json.dumps(continuation)))
        db.add(MessageRecord(message_id="message", session_id="ordinary", role="user", parts_json='[]'))
        db.commit()
    migrations.upgrade(engine, migrations.QQ_COMMANDS_REVISION)
    with DbSession(engine) as db:
        for kind in ("workspace", "timeline"):
            assert json.loads(db.get(ProjectRecord, kind).configuration_json) == expected_config
        ordinary = db.get(SessionRecord, "ordinary")
        assert json.loads(ordinary.configuration_json) == expected_config
        assert ordinary.title == "Saved title" and ordinary.waiting_run_id == "run"
        assert json.loads(db.get(SessionRecord, "workspace").configuration_json) == {"overrides": expected_config}
        assert json.loads(db.get(SessionRecord, "inherited").configuration_json) == {"overrides": {}}
        run = db.get(RunRecord, "run")
        assert json.loads(run.config_snapshot_json) == expected_config
        assert json.loads(run.metadata_json) == {"input_message_id": "message", "configuration": expected_config}
        assert json.loads(run.harness_state_json) == continuation
        assert run.status == "WAITING_FOR_USER" and db.get(MessageRecord, "message") is not None
        ordinary.configuration_json = json.dumps({**expected_config, "context_policy": {"max_messages": 0}})
        db.add(ordinary)
        db.commit()
    migrations.upgrade(engine, migrations.QQ_COMMANDS_REVISION)
    assert migrations.current_revision(engine) == migrations.QQ_COMMANDS_REVISION
    with DbSession(engine) as db:
        assert json.loads(db.get(SessionRecord, "ordinary").configuration_json)["context_policy"] == {"max_messages": 0}
    assert all(path.read_bytes() == b"keep" for path in files)
