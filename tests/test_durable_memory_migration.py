"""Memory revision resets only disposable normal conversations."""

from sqlalchemy import text
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
