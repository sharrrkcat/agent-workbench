"""Only QQ test history is discarded when introducing shared media."""
from sqlalchemy import inspect, text

from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine


def test_media_assets_migration_resets_only_qq_history(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'assets.db'}")
    migrations.upgrade(engine, migrations.IMAGE_GENERATION_REVISION)
    files = [tmp_path / path for path in ("models/model.bin", "attachments/picture.png", "runtimes/worker.exe")]
    for path in files:
        path.parent.mkdir()
        path.write_bytes(b"preserved")
    with engine.begin() as db:
        db.execute(text("INSERT INTO projects (id, kind, name, configuration_json, created_at, updated_at) "
            "VALUES ('p', 'qqbot', 'QQ', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        for sid, kind, pid in (("qq", "qqbot", "p"), ("ordinary", "ordinary", None)):
            db.execute(text("INSERT INTO sessionrecord (session_id, kind, project_id, configuration_json, created_at, updated_at, title, waiting_run_id, title_generation_state, title_generation_metadata_json) "
                "VALUES (:sid, :kind, :pid, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'keep title', :sid, 'manual', '{}')"), dict(sid=sid, kind=kind, pid=pid))
            db.execute(text("INSERT INTO messagerecord (message_id, session_id, role, content_version, parts_json, metadata_json, created_at) "
                "VALUES (:sid, :sid, 'user', 2, '[]', '{}', CURRENT_TIMESTAMP)"), dict(sid=sid))
            db.execute(text("INSERT INTO runrecord (run_id, session_id, kind, persona_id, status, config_snapshot_json, harness_state_json, metadata_json, "
                "current_step, stage, progress_message, cancel_requested, created_at, updated_at) "
                "VALUES (:sid, :sid, 'chat', 'test', 'DONE', '{}', '{}', '{}', '', '', '', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), dict(sid=sid))
            db.execute(text('INSERT INTO runsteprecord (step_id, run_id, kind, label, status, message, "order", metadata_json, created_at, updated_at, context_snapshot_json) '
                "VALUES (:sid, :sid, 'model', '', 'COMPLETED', '', 0, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '{}')"), dict(sid=sid))
            db.execute(text("INSERT INTO runeventrecord (event_id, run_id, session_id, type, message, payload_json, created_at) "
                "VALUES (:sid, :sid, :sid, 'test', '', '{}', CURRENT_TIMESTAMP)"), dict(sid=sid))
        db.execute(text("INSERT INTO qq_bindings (session_id, project_id, target_kind, target_id, paused, pause_reason, deadline, window_kind) "
            "VALUES ('qq', 'p', 'group', '123', 1, 'manual', 99, 'followup')"))
        db.execute(text("INSERT INTO qq_messages (id, session_id, external_id, sender_id, sender_name, timestamp, text, references_json, disposition) "
            "VALUES (1, 'qq', '1', '2', 'sender', 'now', 'old', '[]', 'pending')"))
        db.execute(text("INSERT INTO qq_media (message_id, segment_index, text_start, text_end, kind, source_json, status, attachment_json) "
            "VALUES (1, 0, 0, 4, 'image', '{}', 'ready', '{}')"))
        db.execute(text("INSERT INTO qq_participants (session_id, sender_id, keyword_message_id, expires_at) VALUES ('qq', '2', 1, 99)"))
        db.execute(text("INSERT INTO qq_batches (session_id, project_id, status, text, created_at) VALUES ('qq', 'p', 'queued', 'old', 1)"))
        db.execute(text("INSERT INTO qq_deliveries (session_id, run_id, tool_call_id, text, status, created_at, echoed) "
            "VALUES ('qq', 'qq', 'call', 'old', 'sent', 1, 0)"))
    migrations.upgrade(engine)
    assert "qq_media_assets" in inspect(engine).get_table_names()
    columns = {column["name"] for column in inspect(engine).get_columns("qq_media")}
    assert "asset_id" in columns and not columns.intersection({"attachment_json", "model_attachment_json"})
    with engine.begin() as db:
        for table in ("qq_messages", "qq_media", "qq_media_assets", "qq_participants", "qq_batches", "qq_deliveries"):
            assert db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
        for table in ("messagerecord", "runrecord", "runeventrecord"):
            assert db.execute(text(f"SELECT session_id FROM {table}")).scalars().all() == ["ordinary"]
        assert db.execute(text("SELECT run_id FROM runsteprecord")).scalars().all() == ["ordinary"]
        assert db.execute(text("SELECT title, waiting_run_id FROM sessionrecord WHERE session_id = 'qq'")).one() == ("keep title", None)
        assert db.execute(text("SELECT paused, pause_reason, deadline FROM qq_bindings")).one() == (1, "manual", None)
        assert db.execute(text("SELECT COUNT(*) FROM projects WHERE id = 'p'")).scalar_one() == 1
        db.execute(text("INSERT INTO qq_messages (session_id, external_id, sender_id, sender_name, timestamp, text, references_json, disposition) "
            "VALUES ('qq', '2', '2', 'sender', 'now', 'new', '[]', 'pending')"))
    migrations.upgrade(engine)
    with engine.connect() as db:
        assert db.execute(text("SELECT text FROM qq_messages")).scalar_one() == "new"
    assert all(path.read_bytes() == b"preserved" for path in files)
