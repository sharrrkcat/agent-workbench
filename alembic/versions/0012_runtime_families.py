"""Discard excluded runtime/model configurations without converting records or files."""
from alembic import op
import sqlalchemy as sa

revision = "0012_runtime_families"
down_revision = "0011_tts"
branch_labels = None
depends_on = None


def with_ids(connection, statement, ids):
    return connection.execute(sa.text(statement).bindparams(sa.bindparam("ids", expanding=True)), {"ids": ids})


def upgrade():
    connection = op.get_bind()
    removed = list(connection.execute(sa.text("""SELECT id FROM model_profiles WHERE
        runtime_variant IN ('torch-cpu', 'torch-cu128', 'vulkan', 'onnx-gpu')
        OR (kind = 'image_embedding' AND json_extract(parameters_json, '$.architecture') = 'dinov2')
        OR (kind = 'vision' AND (
            coalesce(json_extract(parameters_json, '$.architecture'), '') != 'wd14'
            OR coalesce(json_extract(parameters_json, '$.task'), '') != 'tags'))
    """)).scalars())
    if removed:
        bases = list(with_ids(connection,
            "SELECT id FROM knowledge_bases WHERE embedding_model_profile_id IN :ids", removed).scalars())
        if bases:
            for table in ("persona_knowledge_bindings", "session_knowledge_bindings", "kb_chunk_fts", "kb_embeddings", "kb_chunks", "kb_sources"):
                with_ids(connection, f"DELETE FROM {table} WHERE knowledge_base_id IN :ids", bases)
            with_ids(connection, "DELETE FROM knowledge_bases WHERE id IN :ids", bases)
        with_ids(connection, "UPDATE knowledge_settings SET reranker_model_profile_id = NULL WHERE reranker_model_profile_id IN :ids", removed)
        with_ids(connection, "UPDATE sessionrecord SET model_profile_id = NULL WHERE model_profile_id IN :ids", removed)
        for key in ("default_model_profile_id", "utility_model_profile_id"):
            with_ids(connection, f"""UPDATE appmetadatarecord SET value = json_remove(value, '$.{key}')
                WHERE key = 'model_settings' AND json_extract(value, '$.{key}') IN :ids""", removed)
        # Discard only unfinished runs whose private continuation needs a removed
        # model. Completed histories remain historical data, never rebound.
        runs = list(with_ids(connection, """SELECT run_id FROM runrecord
            WHERE status NOT IN ('DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED')
            AND json_extract(config_snapshot_json, '$.model_profile_id') IN :ids""", removed).scalars())
        if runs:
            with_ids(connection, "UPDATE sessionrecord SET waiting_run_id = NULL WHERE waiting_run_id IN :ids", runs)
            for table in ("runeventrecord", "runsteprecord", "messagerecord", "runrecord"):
                with_ids(connection, f"DELETE FROM {table} WHERE run_id IN :ids", runs)
        with_ids(connection, "DELETE FROM model_profiles WHERE id IN :ids", removed)
    for table in ("runtime_jobs", "runtime_installations"):
        connection.execute(sa.text(f"DELETE FROM {table} WHERE variant IN ('torch-cpu', 'torch-cu128', 'vulkan', 'onnx-gpu')"))


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
