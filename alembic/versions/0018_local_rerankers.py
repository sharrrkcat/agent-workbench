"""Enable local rerankers and reset their abandoned batch parameter."""
from alembic import op

revision = "0018_local_rerankers"
down_revision = "0017_local_text_embeddings"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE model_profiles SET parameters_json = '{}' WHERE kind = 'reranker'")
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_constraint("ck_model_source", type_="check")
        batch.create_check_constraint("ck_model_source",
            "(source_type IS NULL AND provider_profile_id IS NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'provider' AND kind IN ('llm', 'embedding') AND provider_profile_id IS NOT NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'local' AND kind IN ('llm', 'tts', 'vision', 'image_embedding', 'embedding', 'reranker') AND provider_profile_id IS NULL AND execution_options_json IS NOT NULL AND lifecycle_json IS NOT NULL)")


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
