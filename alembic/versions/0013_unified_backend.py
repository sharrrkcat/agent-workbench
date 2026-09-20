"""Replace disposable backend/model/runtime configuration; never touch files."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0013_unified_backend"
down_revision = "0012_runtime_families"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    bases = "SELECT id FROM knowledge_bases WHERE embedding_model_profile_id IN (SELECT id FROM model_profiles)"
    for table in ("persona_knowledge_bindings", "session_knowledge_bindings", "kb_chunk_fts", "kb_embeddings", "kb_chunks", "kb_sources"):
        connection.execute(sa.text(f"DELETE FROM {table} WHERE knowledge_base_id IN ({bases})"))
    connection.execute(sa.text(f"DELETE FROM knowledge_bases WHERE id IN ({bases})"))
    connection.execute(sa.text("UPDATE knowledge_settings SET reranker_model_profile_id = NULL"))
    connection.execute(sa.text("UPDATE sessionrecord SET model_profile_id = NULL"))
    connection.execute(sa.text("""UPDATE appmetadatarecord
        SET value = json_remove(value, '$.default_model_profile_id', '$.utility_model_profile_id')
        WHERE key = 'model_settings'"""))
    connection.execute(sa.text("DELETE FROM appmetadatarecord WHERE key = 'runtime_settings'"))
    runs = """SELECT run_id FROM runrecord WHERE status NOT IN ('DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED')
        AND json_extract(config_snapshot_json, '$.model_profile_id') IN (SELECT id FROM model_profiles)"""
    connection.execute(sa.text(f"UPDATE sessionrecord SET waiting_run_id = NULL WHERE waiting_run_id IN ({runs})"))
    for table in ("runeventrecord", "runsteprecord", "messagerecord", "runrecord"):
        connection.execute(sa.text(f"DELETE FROM {table} WHERE run_id IN ({runs})"))
    for table in ("runtime_jobs", "runtime_installations", "model_profiles", "provider_profiles"):
        op.drop_table(table)

    op.create_table("backend_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("connection_json", sa.String()),
        sa.Column("download_json", sa.String()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("(type = 'local' AND id = 'local') OR (type = 'openai_compatible' AND id != 'local')", name="ck_backend_identity"))
    now = datetime.now(timezone.utc)
    connection.execute(sa.text("""INSERT INTO backend_profiles
        (id, name, type, enabled, connection_json, download_json, created_at, updated_at)
        VALUES ('local', 'Local backend', 'local', 1, NULL, '{}', :now, :now)"""), {"now": now})

    op.create_table("model_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("backend_profile_id", sa.String(), sa.ForeignKey("backend_profiles.id")),
        sa.Column("model_ref", sa.String(), nullable=False),
        sa.Column("capabilities_json", sa.String(), nullable=False),
        sa.Column("parameters_json", sa.String(), nullable=False),
        sa.Column("lifecycle_json", sa.String(), nullable=False),
        sa.Column("execution_options_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("external_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('llm', 'embedding', 'reranker', 'image_embedding', 'vision', 'tts')", name="ck_model_kind"))
    op.create_index("ix_model_profiles_alias", "model_profiles", ["alias"], unique=True)
    op.create_index("ix_model_profiles_kind", "model_profiles", ["kind"])
    op.create_index("ix_model_profiles_backend_profile_id", "model_profiles", ["backend_profile_id"])

    op.create_table("runtime_installations",
        sa.Column("backend_profile_id", sa.String(), sa.ForeignKey("backend_profiles.id"), primary_key=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("job_id", sa.String()),
        sa.Column("error_code", sa.String()),
        sa.Column("manifest_sha256", sa.String()),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("runtime_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("backend_profile_id", sa.String(), sa.ForeignKey("backend_profiles.id")),
        sa.Column("version", sa.String()),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("result_json", sa.String()),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer()),
        sa.Column("error_code", sa.String()),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("log_path", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()))


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
