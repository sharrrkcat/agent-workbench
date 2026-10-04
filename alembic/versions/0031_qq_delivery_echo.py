"""Record observed echoes of confirmed QQ deliveries."""
from alembic import op
import sqlalchemy as sa

revision = "0031_qq_delivery_echo"
down_revision = "0030_qqbot"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("qq_deliveries", sa.Column("echoed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_qq_delivery_external", "qq_deliveries", ["session_id", "external_id"])


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
