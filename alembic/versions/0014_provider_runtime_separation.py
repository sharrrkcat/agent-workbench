"""Separate provider configuration while preserving local installation/job identity."""
from alembic import op
import sqlalchemy as sa

revision = "0014_provider_runtime_separation"
down_revision = "0013_unified_backend"
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
    connection.execute(sa.text("DELETE FROM appmetadatarecord WHERE key = 'local_runtime_settings'"))
    runs = """SELECT run_id FROM runrecord WHERE status NOT IN ('DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED')
        AND json_extract(config_snapshot_json, '$.model_profile_id') IN (SELECT id FROM model_profiles)"""
    connection.execute(sa.text(f"UPDATE sessionrecord SET waiting_run_id = NULL WHERE waiting_run_id IN ({runs})"))
    for table in ("runeventrecord", "runsteprecord", "messagerecord", "runrecord"):
        connection.execute(sa.text(f"DELETE FROM {table} WHERE run_id IN ({runs})"))

    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("runtime_installations", naming_convention=naming) as batch:
        batch.drop_constraint("fk_runtime_installations_backend_profile_id_backend_profiles", type_="foreignkey")
        batch.alter_column("backend_profile_id", new_column_name="id", existing_type=sa.String())
        batch.create_check_constraint("ck_local_runtime_identity", "id = 'local'")
    with op.batch_alter_table("runtime_jobs", naming_convention=naming) as batch:
        batch.drop_constraint("fk_runtime_jobs_backend_profile_id_backend_profiles", type_="foreignkey")
        batch.drop_column("backend_profile_id")
    op.drop_table("model_profiles")
    op.drop_table("backend_profiles")

    op.create_table("provider_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("connection_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("model_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("source_type", sa.String()),
        sa.Column("provider_profile_id", sa.String(), sa.ForeignKey("provider_profiles.id")),
        sa.Column("model_ref", sa.String(), nullable=False),
        sa.Column("capabilities_json", sa.String(), nullable=False),
        sa.Column("parameters_json", sa.String(), nullable=False),
        sa.Column("lifecycle_json", sa.String()),
        sa.Column("execution_options_json", sa.String()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("external_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('llm', 'embedding', 'reranker', 'image_embedding', 'vision', 'tts')", name="ck_model_kind"),
        sa.CheckConstraint("(source_type IS NULL AND provider_profile_id IS NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'provider' AND kind IN ('llm', 'embedding') AND provider_profile_id IS NOT NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'local' AND kind IN ('llm', 'tts') AND provider_profile_id IS NULL AND execution_options_json IS NOT NULL AND lifecycle_json IS NOT NULL)", name="ck_model_source"))
    op.create_index("ix_model_profiles_alias", "model_profiles", ["alias"], unique=True)
    op.create_index("ix_model_profiles_kind", "model_profiles", ["kind"])
    op.create_index("ix_model_profiles_provider_profile_id", "model_profiles", ["provider_profile_id"])


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
