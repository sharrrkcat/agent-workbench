"""Index bounded history reads and version destructive conversation changes."""
from alembic import op
import sqlalchemy as sa

revision = "0029_bounded_history"
down_revision = "0028_context_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessionrecord", sa.Column("history_version", sa.Integer(), nullable=False, server_default="0"))
    for table, name, columns in (
        ("messagerecord", "ix_message_session_order", ["session_id", "created_at", "message_id"]),
        ("messagerecord", "ix_message_run_order", ["run_id", "created_at", "message_id"]),
        ("runrecord", "ix_run_session_order", ["session_id", "created_at", "run_id"]),
        ("runrecord", "ix_run_session_status", ["session_id", "status"]),
        ("runeventrecord", "ix_event_run_order", ["run_id", "created_at", "event_id"]),
    ):
        op.create_index(name, table, columns)


def downgrade() -> None:
    raise RuntimeError("Test database downgrade is unsupported")
