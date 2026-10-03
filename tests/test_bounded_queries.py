import json
from array import array

import pytest
from sqlalchemy import event
from sqlmodel import Session as DbSession

from ai_workbench.core.attachments import referenced_attachment_filenames
from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.vector_store import search_vectors, embedding_score
from ai_workbench.db.models import KnowledgeSourceRecord, KnowledgeChunkRecord, KnowledgeEmbeddingRecord
from tests.test_bounded_history import history_stores


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}, "[]", "{}", "0", [0], {"x": 0}, True, 1])
def test_context_sql_matches_python_eligibility(history_stores, value):
    state = history_stores
    sid = state.sessions.create_session().session_id
    state.messages.add_message(sid, "user", "history", metadata={"event_type": value})
    built = ContextBuilder(state.messages).build(sid, "current", ContextPolicy(max_messages=1))
    assert len(built.messages) == (1 if value else 2)


def test_attachment_reference_queries_cover_parts_gallery_and_metadata(history_stores, monkeypatch):
    state = history_stores
    sid = state.sessions.create_session().session_id
    names = {"aa.png", "bb.txt", "cc.png", "dd.wav", "ee.mp4", "ff.png", "ab.txt", "cd.txt"}
    message = state.messages.add_message(sid, "user", parts=[
        {"type": "image", "attachment_id": "aa.png"},
        {"type": "file", "mode": "attachment_ref", "attachment_id": "bb.txt"},
        {"type": "image", "url": "/api/attachments/cc.png"},
        {"type": "audio", "source": "attachment", "attachment_id": "dd.wav", "url": "local://attachments/dd.wav", "mime_type": "audio/wav"},
        {"type": "video", "source": "attachment", "attachment_id": "ee.mp4", "url": "local://attachments/ee.mp4", "mime_type": "video/mp4"},
        {"type": "media_group", "items": [{"attachment_id": "ff.png"}]},
        {"type": "json", "data": {"uri": "local://attachments/abcdef.txt"}},
    ], metadata={"attachments": [{"id": "ab.txt", "uri": "local://attachments/cd.txt"}]})
    monkeypatch.setattr(state.messages, "list_all_messages", lambda: pytest.fail("Loaded all messages"))
    assert referenced_attachment_filenames(state.messages, names | {"abcdef.txt"}) == names
    assert set(state.messages.attachment_filenames(message_ids={message.message_id})) == names


def test_sql_vector_top_k_matches_full_reference_without_loading_all_text(history_stores):
    state = history_stores
    if not state.engine:
        pytest.skip("SQL streaming query")
    rows, vectors = [], {}
    with DbSession(state.engine) as db:
        db.add(KnowledgeSourceRecord(id="source", knowledge_base_id="base", source_type="text", content_hash="x", status="indexed"))
        for index in range(600):
            chunk_id = f"c-{index:04}"
            vector = [float(index % 7), 1.0]
            vectors[chunk_id] = vector
            db.add(KnowledgeChunkRecord(id=chunk_id, knowledge_base_id="base", source_id="source", chunk_index=index,
                content="text-" + str(index) + "x" * 4096, char_start=0, char_end=4096, content_hash="x"))
            db.add(KnowledgeEmbeddingRecord(id=f"e-{index}", knowledge_base_id="base", source_id="source", chunk_id=chunk_id,
                embedding_model_profile_id="embed", embedding_model_id_snapshot="embed", embedding_dimension=2,
                vector_blob=array("f", vector).tobytes()))
        db.commit()
    def capture(_conn, _cursor, statement, _params, *_):
        rows.append(statement)
    event.listen(state.engine, "before_cursor_execute", capture)
    try:
        for similarity in ("dot", "cosine"):
            result, warnings = search_vectors(engine=state.engine, query_vector=[1.0, 1.0],
                embedding_model_profile_id="embed", knowledge_base_ids=["base"], top_k=11, similarity=similarity)
            expected = sorted(vectors, key=lambda id: (-embedding_score([1.0, 1.0], vectors[id], similarity), id))[:11]
            assert [item.chunk_id for item in result] == expected
            assert warnings == []
    finally:
        event.remove(state.engine, "before_cursor_execute", capture)
    scanning = [statement for statement in rows if "vector_blob" in statement]
    assert scanning and all("c.content" not in statement for statement in scanning)


def test_history_migration_preserves_configuration_and_files(tmp_path):
    from ai_workbench.db import migrations
    from ai_workbench.db.database import get_engine
    engine = get_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migrations.upgrade(engine, migrations.CONTEXT_BUDGET_REVISION)
    configuration = json.dumps({"context_policy": {"max_messages": None, "max_chars": None}})
    with engine.begin() as connection:
        connection.exec_driver_sql("""INSERT INTO sessionrecord (session_id, kind, title, configuration_json,
            title_generation_state, title_generation_metadata_json, created_at, updated_at)
            VALUES ('s', 'ordinary', '', ?, 'pending', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""", (configuration,))
    attachment = tmp_path / "attachment.txt"
    attachment.write_text("retained")
    migrations.upgrade(engine)
    migrations.upgrade(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT configuration_json, history_version FROM sessionrecord").one() == (configuration, 0)
    assert attachment.read_text() == "retained"
