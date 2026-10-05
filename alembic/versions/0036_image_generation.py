"""Add provider-only image generation profiles without changing existing data."""
from alembic import op

revision = "0036_image_generation"
down_revision = "0035_provider_tts"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_constraint("ck_model_kind", type_="check")
        batch.create_check_constraint("ck_model_kind",
            "kind IN ('llm', 'embedding', 'reranker', 'image_embedding', 'vision', 'tts', 'asr', 'processor', 'image_generation')")
        batch.drop_constraint("ck_model_source", type_="check")
        batch.create_check_constraint("ck_model_source",
            "(source_type IS NULL AND kind IN ('llm', 'embedding', 'reranker') AND provider_profile_id IS NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'provider' AND kind IN ('llm', 'embedding', 'tts', 'image_generation') AND provider_profile_id IS NOT NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'local' AND kind IN ('llm', 'tts', 'vision', 'image_embedding', 'embedding', 'reranker', 'asr', 'processor') AND provider_profile_id IS NULL AND execution_options_json IS NOT NULL AND lifecycle_json IS NOT NULL)")


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
