"""Retain QQ deduplication and receipt identities after local history deletion."""
from alembic import op
import sqlalchemy as sa

revision = "0033_qq_history_deletion"
down_revision = "0032_qq_followup"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("qq_messages", "qq_deliveries"):
        op.add_column(table, sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_qq_message_batch", "qq_messages", ["batch_id", "deleted", "id"])


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
