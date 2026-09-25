"""Use directory-derived model configuration and restrict local-only sources."""
from alembic import op


revision = "0020_directory_models"
down_revision = "0019_asr"
branch_labels = None
depends_on = None


def upgrade():
    affected = """SELECT id FROM model_profiles WHERE kind IN ('tts', 'vision')
        OR (kind = 'llm' AND source_type IS 'local' AND lower(model_ref) LIKE '%.gguf')
        OR (kind IN ('image_embedding', 'asr') AND source_type IS NULL)"""
    runs = f"""SELECT run_id FROM runrecord WHERE status NOT IN ('DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED')
        AND json_extract(config_snapshot_json, '$.model_profile_id') IN ({affected})"""
    op.execute(f"UPDATE sessionrecord SET waiting_run_id = NULL WHERE waiting_run_id IN ({runs})")
    for table in ("runeventrecord", "runsteprecord", "messagerecord", "runrecord"):
        op.execute(f"DELETE FROM {table} WHERE run_id IN ({runs})")
    op.execute(f"UPDATE sessionrecord SET model_profile_id = NULL WHERE model_profile_id IN ({affected})")
    for field in ("default_model_profile_id", "utility_model_profile_id"):
        op.execute(f"""UPDATE appmetadatarecord SET value = json_remove(value, '$.{field}')
            WHERE key = 'model_settings' AND json_extract(value, '$.{field}') IN ({affected})""")
    op.execute(f"DELETE FROM model_profiles WHERE id IN ({affected})")
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_constraint("ck_model_source", type_="check")
        batch.create_check_constraint("ck_model_source",
            "(source_type IS NULL AND kind IN ('llm', 'embedding', 'reranker') AND provider_profile_id IS NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'provider' AND kind IN ('llm', 'embedding') AND provider_profile_id IS NOT NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'local' AND kind IN ('llm', 'tts', 'vision', 'image_embedding', 'embedding', 'reranker', 'asr') AND provider_profile_id IS NULL AND execution_options_json IS NOT NULL AND lifecycle_json IS NOT NULL)")


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
