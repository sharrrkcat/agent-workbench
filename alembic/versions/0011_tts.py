"""Allow TTS model profiles; no file or model-data operations."""
from alembic import op

revision = "0011_tts"
down_revision = "0010_runtime_maintenance"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_constraint("ck_model_kind", type_="check")
        batch.create_check_constraint("ck_model_kind", "kind IN ('llm', 'embedding', 'reranker', 'image_embedding', 'vision', 'tts')")


def downgrade():
    raise RuntimeError("TTS test database downgrade is unsupported")
