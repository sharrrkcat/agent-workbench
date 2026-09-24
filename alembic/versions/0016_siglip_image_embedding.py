"""Enable local SigLIP profiles and remove obsolete image-embedding drafts."""
from alembic import op
import sqlalchemy as sa

revision = "0016_siglip_image_embedding"
down_revision = "0015_wd14_vision"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("DELETE FROM model_profiles WHERE kind = 'image_embedding'"))
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_constraint("ck_model_source", type_="check")
        batch.create_check_constraint("ck_model_source",
            "(source_type IS NULL AND provider_profile_id IS NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'provider' AND kind IN ('llm', 'embedding') AND provider_profile_id IS NOT NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'local' AND kind IN ('llm', 'tts', 'vision', 'image_embedding') AND provider_profile_id IS NULL AND execution_options_json IS NOT NULL AND lifecycle_json IS NOT NULL)")


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
