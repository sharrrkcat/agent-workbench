from tests.migration_fixtures import insert_historical_row, historical_row
import json

from sqlalchemy import text
from sqlmodel import Session

from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import SessionRecord, MessageRecord, RunRecord, ContextCheckpointRecord
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery
from ai_workbench.core.schema.context_policy import ContextPolicy


def test_qq_policy_reset_preserves_configuration_records_and_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'qq.db'}")
    migrations.upgrade(engine, migrations.MANUAL_COMPACTION_REVISION)
    files = [tmp_path / folder / "keep" for folder in ("models", "attachments", "runtimes")]
    for path in files:
        path.parent.mkdir()
        path.write_bytes(b"unchanged")
    with Session(engine) as db:
        old = {"context_policy": {"max_messages": 7, "max_chars": 2345, "include_attachments": "explicit"},
            "bot_account": "12345", "image_input_enabled": True, "access_token": "unchanged-test-token"}
        for kind in ("qqbot", "workspace", "timeline"):
            insert_historical_row(db, "projects", id=kind, kind=kind, name=kind, configuration_json=json.dumps(old))
            if kind != "timeline":
                insert_historical_row(db, "sessionrecord", session_id=kind, kind=kind, project_id=kind, configuration_json="{}")
        db.add(MessageRecord(message_id="input", session_id="qqbot", role="user", parts_json="[]"))
        insert_historical_row(db, "runrecord", run_id="answer", session_id="qqbot", persona_id="", kind="chat", status="DONE")
        db.add(ContextCheckpointRecord(session_id="workspace", checkpoint_json='{"summary":"keep"}'))
        insert_historical_row(db, "qq_bindings", session_id="qqbot", project_id="qqbot", target_kind="group", target_id="789")
        insert_historical_row(db, "qq_batches", id=1, session_id="qqbot", project_id="qqbot", status="done", text="input", created_at=1,
            input_message_id="input", run_id="answer")
        db.add(QQMessage(session_id="qqbot", external_id="1", sender_id="2", sender_name="Name",
            text="input", timestamp="2026-11-01T00:00:00+00:00", disposition="batched", batch_id=1))
        db.add(QQDelivery(session_id="qqbot", run_id="answer", tool_call_id="send", text="sent", status="sent", created_at=1))
        db.commit()
        tables = ("sessionrecord", "messagerecord", "runrecord", "context_checkpoints", "qq_bindings", "qq_messages", "qq_batches", "qq_deliveries")
        saved = {table: db.execute(text(f"SELECT * FROM {table}")).all() for table in tables}
        others = {kind: historical_row(db, "projects", "id", kind)["configuration_json"] for kind in ("workspace", "timeline")}
    migrations.upgrade(engine, migrations.QQ_CONTEXT_COMPACTION_REVISION)
    with Session(engine) as db:
        value = json.loads(historical_row(db, "projects", "id", "qqbot")["configuration_json"])
        assert ContextPolicy.model_validate(value["context_policy"]) == ContextPolicy(include_attachments="none")
        assert {key: value[key] for key in old if key != "context_policy"} == {key: old[key] for key in old if key != "context_policy"}
        assert all(historical_row(db, "projects", "id", kind)["configuration_json"] == raw for kind, raw in others.items())
        for table, rows in saved.items():
            assert db.execute(text(f"SELECT * FROM {table}")).all() == rows
    assert all(path.read_bytes() == b"unchanged" for path in files)
