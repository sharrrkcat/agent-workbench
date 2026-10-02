import json

import pytest
from sqlmodel import Session as DbSession

from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.stores import MessageStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import MessageRecord, ProjectRecord, RunRecord, SessionRecord


@pytest.mark.parametrize("limit,start", [(None, 0), (0, 25), (1, 24), (20, 5), (10000, 0)])
def test_history_limits_keep_newest_eligible_messages_and_current_input(limit, start):
    store = MessageStore()
    for index in range(25):
        store.add_message("s", "user" if index % 2 == 0 else "assistant", f"history-{index}")
    store.add_message("other", "user", "OTHER_SESSION")
    for flag in ("streaming", "incomplete", "event_type"):
        store.add_message("s", "assistant", "EXCLUDED", metadata={flag: True})
    current = store.add_message("s", "user", "current")
    result = ContextBuilder(store).build("s", "current", ContextPolicy(max_messages=limit),
                                         current_message_id=current.message_id)
    assert result.messages == [
        *[{"role": "user" if i % 2 == 0 else "assistant", "content": f"history-{i}"} for i in range(start, 25)],
        {"role": "user", "content": "current"},
    ]
    assert not result.warnings
    if limit is None:
        assert ContextBuilder(store).build("s", "current", current_message_id=current.message_id) == result


@pytest.mark.parametrize("budget,expected", [(None, ["old", "longer", "new"]), (9, ["new"]), (15, ["longer", "new"]), (2, [])])
def test_character_budget_preserves_whole_recent_messages_and_current_input(budget, expected):
    store = MessageStore()
    for text in ("old", "longer", "new"):
        store.add_message("s", "user", text)
    result = ContextBuilder(store).build("s", "input!", ContextPolicy(max_chars=budget))
    assert [message["content"] for message in result.messages] == [*expected, "input!"]
    assert bool(result.warnings) == (budget == 2)


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
        db.add(SessionRecord(session_id="ordinary", kind="ordinary", title="Saved title", waiting_run_id="run",
                             configuration_json=json.dumps(config)))
        db.add(SessionRecord(session_id="workspace", kind="workspace", project_id="workspace",
                             configuration_json=json.dumps({"overrides": config})))
        db.add(SessionRecord(session_id="inherited", kind="workspace", project_id="workspace",
                             configuration_json='{"overrides": {}}'))
        db.add(RunRecord(run_id="run", session_id="ordinary", persona_id="persona", kind="chat", status="WAITING_FOR_USER",
                         config_snapshot_json=json.dumps(config), metadata_json=json.dumps(metadata),
                         harness_state_json=json.dumps(continuation)))
        db.add(MessageRecord(message_id="message", session_id="ordinary", role="user", parts_json='[]'))
        db.commit()
    migrations.upgrade(engine)
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
    migrations.upgrade(engine)
    assert migrations.current_revision(engine) == migrations.HISTORY_LIMITS_REVISION
    with DbSession(engine) as db:
        assert json.loads(db.get(SessionRecord, "ordinary").configuration_json)["context_policy"] == {"max_messages": 0}
    assert all(path.read_bytes() == b"keep" for path in files)
