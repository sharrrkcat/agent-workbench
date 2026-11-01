from sqlalchemy import text
from sqlmodel import Session

from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import ContextCheckpointRecord, MessageRecord, RunRecord, SessionRecord
from ai_workbench.db.stores import SqlRunStore
from ai_workbench.core.schema.run import RunStatus


def test_manual_migration_preserves_rows_and_files_and_recovers_runs(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'app.db'}")
    migrations.upgrade(engine, migrations.CONTEXT_COMPACTION_REVISION)
    paths = [tmp_path / name / 'keep.bin' for name in ('models', 'attachments', 'runtimes')]
    for path in paths:
        path.parent.mkdir()
        path.write_bytes(b'unchanged')
    with Session(engine) as db:
        db.add(SessionRecord(session_id='session', kind='ordinary', title='Kept', configuration_json='{}'))
        db.add(RunRecord(run_id='answer', session_id='session', persona_id='persona', kind='chat', status='DONE',
                         config_snapshot_json='{"preserved":true}'))
        db.add(MessageRecord(message_id='input', session_id='session', role='user', parts_json='[]'))
        db.add(ContextCheckpointRecord(session_id='session', checkpoint_json='{"summary":"saved"}'))
        db.commit()
        before = {table: db.execute(text(f'SELECT * FROM {table}')).all()
                  for table in ('sessionrecord', 'runrecord', 'messagerecord', 'context_checkpoints')}
    migrations.upgrade(engine)
    with Session(engine) as db:
        for table, rows in before.items():
            assert db.execute(text(f'SELECT * FROM {table}')).all() == rows
    store = SqlRunStore(engine)
    run = store.create_run('compaction', 'persona', 'session')
    step = store.create_step(run.run_id, 'compaction')
    store.update_status(run.run_id, RunStatus.RUNNING)
    assert store.interrupt_unfinished_runs() == [run.run_id]
    assert store.get_run(run.run_id).status == 'INTERRUPTED'
    assert store.get_step(step.step_id).status == 'failed'
    assert all(path.read_bytes() == b'unchanged' for path in paths)
