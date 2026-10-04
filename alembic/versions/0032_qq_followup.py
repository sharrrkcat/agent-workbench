"""Persist QQ participant eligibility and immutable batch trigger policy."""
from alembic import op
import sqlalchemy as sa

revision = "0032_qq_followup"
down_revision = "0031_qq_delivery_echo"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("qq_participants",
        sa.Column("session_id", sa.String(), primary_key=True),
        sa.Column("sender_id", sa.String(), primary_key=True),
        sa.Column("keyword_message_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("in_window", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("qq_bindings", sa.Column("window_kind", sa.String(), nullable=False, server_default="keyword"))
    op.add_column("qq_batches", sa.Column("trigger_kind", sa.String(), nullable=False, server_default="keyword"))
    op.add_column("qq_batches", sa.Column("participants_json", sa.String(), nullable=False, server_default="{}"))


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
