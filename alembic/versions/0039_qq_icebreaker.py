"""Persist per-group icebreaker cooldowns; observations are process-local."""
from alembic import op
import sqlalchemy as sa

revision = "0039_qq_icebreaker"
down_revision = "0038_qq_image_generation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("qq_bindings", sa.Column("icebreaker_cooldown_until", sa.Float(), nullable=True))


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
