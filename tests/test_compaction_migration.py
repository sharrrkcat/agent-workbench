import json

from sqlalchemy import text
from sqlmodel import Session

from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from ai_workbench.db.models import SessionRecord, ProjectRecord, RunRecord, RunStepRecord, MessageRecord


def test_compaction_migration_resets_only_owned_conversation_state(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.QQ_COMMANDS_REVISION)
    old_policy = {'max_messages': 7, 'max_chars': 300, 'include_attachments': 'none'}
    config = json.dumps({'context_policy': old_policy, 'system_prompt': 'KEEP PROMPT', 'model_profile_id': 'keep-model'})
    with Session(engine) as db:
        for kind in ('workspace', 'timeline', 'qqbot'):
            db.add(ProjectRecord(id=kind, kind=kind, name=kind, configuration_json=config))
        db.commit()
        for kind in ('ordinary', 'workspace', 'qqbot'):
            db.add(SessionRecord(session_id=kind, kind=kind, project_id=None if kind == 'ordinary' else kind,
                configuration_json=config, title='test'))
            db.add(RunRecord(run_id=kind, session_id=kind, kind='chat', persona_id='p', status='DONE', config_snapshot_json=config))
            db.add(RunStepRecord(step_id=kind, run_id=kind, kind='model', status='completed'))
            db.add(MessageRecord(message_id=kind, session_id=kind, role='user'))
        db.commit()
    files = [tmp_path / 'data' / name / 'keep.bin' for name in ('models', 'attachments', 'runtimes')]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b'unchanged')
    migrations.upgrade(engine, migrations.CONTEXT_COMPACTION_REVISION)
    migrations.upgrade(engine, migrations.CONTEXT_COMPACTION_REVISION)
    with Session(engine) as db:
        for model, key in ((SessionRecord, 'session_id'), (RunRecord, 'run_id'), (RunStepRecord, 'step_id'), (MessageRecord, 'message_id')):
            assert list(db.execute(text(f'SELECT {key} FROM {model.__tablename__}')).scalars()) == ['qqbot']
        workspace = json.loads(db.get(ProjectRecord, 'workspace').configuration_json)
        assert workspace['system_prompt'] == 'KEEP PROMPT' and workspace['model_profile_id'] == 'keep-model'
        assert workspace['context_policy']['compaction']['enabled'] is True
        assert 'max_messages' not in workspace['context_policy']
        for kind in ('timeline', 'qqbot'):
            assert db.get(ProjectRecord, kind).configuration_json == config
        assert db.execute(text('SELECT count(*) FROM context_checkpoints')).scalar_one() == 0
    assert all(path.read_bytes() == b'unchanged' for path in files)
