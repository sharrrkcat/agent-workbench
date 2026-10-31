"""Add QQ command ingress and durable administrator notifications."""
from alembic import op
import sqlalchemy as sa

revision = "0046_qq_commands"
down_revision = "0045_web_filters"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("qq_messages", sa.Column("kind", sa.String(), nullable=False, server_default="chat"))
    op.add_column("qq_messages", sa.Column("command_status", sa.String(), nullable=True))
    op.create_index("ix_qq_command_queue", "qq_messages", ["command_status", "id"])
    with op.batch_alter_table("qq_deliveries") as batch:
        batch.alter_column("run_id", existing_type=sa.String(), nullable=True)
        batch.alter_column("tool_call_id", existing_type=sa.String(), nullable=True)
        batch.add_column(sa.Column("origin", sa.String(), nullable=False, server_default="model"))
        batch.add_column(sa.Column("command_message_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("notification_id", sa.Integer(), nullable=True))
        batch.create_unique_constraint("uq_qq_delivery_command", ["command_message_id"])
        batch.create_unique_constraint("uq_qq_delivery_notification", ["notification_id"])
    op.create_table("qq_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("source_session_id", sa.String(), nullable=True),
        sa.Column("event_key", sa.String(), nullable=False, unique=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("last_at", sa.Float(), nullable=False),
        sa.Column("resolved_at", sa.Float(), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sqlite_autoincrement=True)
    op.create_index("ix_qq_notifications_project_id", "qq_notifications", ["project_id"])


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
