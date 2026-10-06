"""Use one participant grant identity for keywords and confirmed icebreakers."""
from alembic import op
import sqlalchemy as sa

revision = "0041_qq_trigger_grants"
down_revision = "0040_qq_resources"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("qq_participants", "keyword_message_id", new_column_name="grant_message_id",
        existing_type=sa.Integer(), existing_nullable=False)


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
