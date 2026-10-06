"""Record image-generation keywords from actual incoming text segments."""
from alembic import op
import sqlalchemy as sa

revision = "0042_qq_image_tools"
down_revision = "0041_qq_trigger_grants"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("qq_messages", sa.Column("image_generation_keyword", sa.Boolean(),
        nullable=False, server_default=sa.false()))


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
