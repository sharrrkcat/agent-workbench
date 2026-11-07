"""Memory revision resets only disposable normal conversations."""

from sqlalchemy import text
import json
from sqlalchemy import inspect
from sqlmodel import Session

from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from tests.migration_fixtures import insert_historical_row


def test_memory_revision_preserves_identities_qq_and_files(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'memory.db'}")
    migrations.upgrade(engine, '0052_characters_personas')
    with Session(engine) as db:
        for identifier, kind in [('normal', 'normal'), ('qq', 'qqbot')]:
            insert_historical_row(db, 'characters', id=identifier, kind=kind, name=identifier)
            insert_historical_row(db, 'sessionrecord', session_id=identifier, character_id=identifier, kind=kind)
            insert_historical_row(db, 'runrecord', run_id=identifier, session_id=identifier,
                character_id=identifier, persona_id=None if kind == 'qqbot' else 'person', kind='chat', status='DONE')
            insert_historical_row(db, 'messagerecord', message_id=identifier, session_id=identifier,
                run_id=identifier, role='user', speaker_id='person')
            insert_historical_row(db, 'context_checkpoints', session_id=identifier, checkpoint_json='{}')
            insert_historical_row(db, 'context_retrieval', session_id=identifier, state_json='{}')
        insert_historical_row(db, 'personas', id='person', name='Preserved', background='profile')
        insert_historical_row(db, 'qq_bindings', session_id='qq', character_id='qq', target_kind='group', target_id='123')
        insert_historical_row(db, 'appmetadatarecord', key='sentinel', value='preserved')
        db.commit()
    files = [tmp_path / 'data' / directory / 'keep.bin' for directory in ('models', 'attachments', 'runtimes')]
    for path in files:
        path.parent.mkdir(parents=True)
        path.write_bytes(b'preserve')
    timestamps = [path.stat().st_mtime_ns for path in files]
    migrations.upgrade(engine)
    migrations.upgrade(engine)
    with engine.connect() as db:
        for table in ('sessionrecord', 'messagerecord', 'runrecord', 'context_checkpoints', 'context_retrieval'):
            assert db.execute(text(f'SELECT session_id FROM {table}')).scalars().all() == ['qq']
        assert db.execute(text('SELECT character_id FROM qq_bindings')).scalar() == 'qq'
        assert set(db.execute(text('SELECT id FROM characters')).scalars()) == {'normal', 'qq'}
        assert db.execute(text("SELECT background FROM personas WHERE id='person'")).scalar() == 'profile'
        assert db.execute(text("SELECT value FROM appmetadatarecord WHERE key='sentinel'")).scalar() == 'preserved'
        assert db.execute(text('SELECT bound_persona_id, memory_isolation, memory_version FROM sessionrecord')).one() == (None, 'shared', 0)
        assert db.execute(text('SELECT count(*) FROM durable_memories')).scalar() == 0
    assert [path.read_bytes() for path in files] == [b'preserve'] * 3
    assert [path.stat().st_mtime_ns for path in files] == timestamps
    engine.dispose()


def test_memory_controls_revision_removes_old_fields_and_review_records(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'controls.db'}")
    migrations.upgrade(engine, '0053_durable_memory')
    with Session(engine) as db:
        insert_historical_row(db, 'characters', id='owner', kind='normal', name='Preserved',
            configuration_json=json.dumps({'memory_enabled': False, 'memory_learning': 'automatic', 'temperature': 0.3}))
        insert_historical_row(db, 'sessionrecord', session_id='session', character_id='owner', kind='normal',
            configuration_json=json.dumps({'overrides': {'memory_learning': 'manual', 'memory_enabled': True}}))
        insert_historical_row(db, 'runrecord', run_id='run', session_id='session', character_id='owner',
            kind='chat', status='DONE', config_snapshot_json=json.dumps({'memory_enabled': True,
                'memory_learning': 'manual', 'sources': {'memory_learning': 'session', 'memory': 'character'}}))
        insert_historical_row(db, 'context_checkpoints', session_id='session', checkpoint_json='{}')
        insert_historical_row(db, 'context_retrieval', session_id='session', state_json='{}')
        for identifier, status in [('active', 'active'), ('review', 'needs_review'), ('deleted', 'deleted')]:
            record = {'id': identifier, 'status': status, 'summary': identifier, 'body': 'Preserve active body'}
            insert_historical_row(db, 'durable_memories', id=identifier, revision=1, pool='character',
                character_id='owner', persona_id='user', session_id='session', status=status, managed_by='model',
                pinned=False, observed_at='2026-01-01', record_json=json.dumps(record))
            insert_historical_row(db, 'durable_memory_terms', memory_id=identifier, term=identifier, weight=1)
            insert_historical_row(db, 'durable_memory_dependencies', memory_id=identifier, session_id='session')
            insert_historical_row(db, 'durable_memory_evidence', memory_id=identifier, message_id='message')
        db.commit()
    migrations.upgrade(engine)
    migrations.upgrade(engine)
    with engine.connect() as db:
        owner = json.loads(db.execute(text('SELECT configuration_json FROM characters')).scalar_one())
        assert owner == {'memory_enabled': False, 'temperature': 0.3}
        session = json.loads(db.execute(text('SELECT configuration_json FROM sessionrecord')).scalar_one())
        assert session == {'overrides': {'memory_enabled': True}}
        config = json.loads(db.execute(text('SELECT config_snapshot_json FROM runrecord')).scalar_one())
        assert config == {'memory_enabled': True, 'sources': {'memory': 'character'}}
        assert db.execute(text('SELECT memory_version FROM sessionrecord')).scalar_one() == 1
        for table in ['context_checkpoints', 'context_retrieval']:
            assert db.execute(text(f'SELECT count(*) FROM {table}')).scalar_one() == 0
        for table, key in [('durable_memories', 'id'), ('durable_memory_terms', 'memory_id'), ('durable_memory_dependencies', 'memory_id')]:
            assert set(db.execute(text(f'SELECT {key} FROM {table}')).scalars()) == {'active', 'deleted'}
        assert 'Preserve active body' in db.execute(text("SELECT record_json FROM durable_memories WHERE id='active'")).scalar_one()
    assert 'durable_memory_evidence' not in inspect(engine).get_table_names()
    constraint = next(c for c in inspect(engine).get_check_constraints('durable_memories') if c['name'] == 'ck_memory_status')
    assert 'needs_review' not in constraint['sqltext']
    engine.dispose()
