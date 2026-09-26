"""Add local processors and independently installed bundled runtime components."""
from alembic import op
import sqlalchemy as sa


revision = "0023_dlss_processor"
down_revision = "0022_projects"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_constraint("ck_model_kind", type_="check")
        batch.create_check_constraint("ck_model_kind",
            "kind IN ('llm', 'embedding', 'reranker', 'image_embedding', 'vision', 'tts', 'asr', 'processor')")
        batch.drop_constraint("ck_model_source", type_="check")
        batch.create_check_constraint("ck_model_source",
            "(source_type IS NULL AND kind IN ('llm', 'embedding', 'reranker') AND provider_profile_id IS NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'provider' AND kind IN ('llm', 'embedding') AND provider_profile_id IS NOT NULL AND execution_options_json IS NULL AND lifecycle_json IS NULL) OR "
            "(source_type IS 'local' AND kind IN ('llm', 'tts', 'vision', 'image_embedding', 'embedding', 'reranker', 'asr', 'processor') AND provider_profile_id IS NULL AND execution_options_json IS NOT NULL AND lifecycle_json IS NOT NULL)")
    op.create_table("runtime_components",
        sa.Column("component_id", sa.String(), primary_key=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("manifest_sha256", sa.String(), nullable=True),
        sa.Column("default_profile_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("component_id = 'dlss5nr'", name="ck_runtime_component"))
    op.add_column("runtime_jobs", sa.Column("component_id", sa.String(), nullable=True))


def downgrade():
    raise RuntimeError("Disposable test database downgrade is unsupported")
