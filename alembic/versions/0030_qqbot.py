"""QQBot Projects and durable conversation queues."""
from alembic import op
import sqlalchemy as sa

revision = "0030_qqbot"
down_revision = "0029_bounded_history"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("ck_project_kind", type_="check")
        batch.create_check_constraint("ck_project_kind", "kind IN ('workspace', 'timeline', 'qqbot')")
    with op.batch_alter_table("sessionrecord") as batch:
        batch.drop_constraint("ck_session_kind", type_="check")
        batch.drop_constraint("ck_session_project", type_="check")
        batch.create_check_constraint("ck_session_kind", "kind IN ('ordinary', 'workspace', 'qqbot')")
        batch.create_check_constraint("ck_session_project", "(kind = 'ordinary' AND project_id IS NULL) OR (kind IN ('workspace', 'qqbot') AND project_id IS NOT NULL)")
    op.create_table("qq_bindings", sa.Column("session_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False), sa.Column("target_kind", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False), sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("pause_reason", sa.String(), nullable=False), sa.Column("deadline", sa.Float()),
        sa.UniqueConstraint("project_id", "target_kind", "target_id"))
    op.create_index("ix_qq_bindings_project_id", "qq_bindings", ["project_id"])
    op.create_table("qq_messages", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False), sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("sender_id", sa.String(), nullable=False), sa.Column("sender_name", sa.String(), nullable=False),
        sa.Column("timestamp", sa.String(), nullable=False), sa.Column("text", sa.String(), nullable=False),
        sa.Column("references_json", sa.String(), nullable=False), sa.Column("disposition", sa.String(), nullable=False),
        sa.Column("batch_id", sa.Integer()), sa.UniqueConstraint("session_id", "external_id"))
    op.create_index("ix_qq_messages_session_id", "qq_messages", ["session_id"])
    op.create_index("ix_qq_message_pending", "qq_messages", ["session_id", "disposition", "id"])
    op.create_table("qq_batches", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("text", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False), sa.Column("input_message_id", sa.String()),
        sa.Column("run_id", sa.String()), sa.Column("error_code", sa.String()))
    op.create_index("ix_qq_batches_session_id", "qq_batches", ["session_id"])
    op.create_index("ix_qq_batch_queue", "qq_batches", ["project_id", "status", "id"])
    op.create_table("qq_deliveries", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False), sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("tool_call_id", sa.String(), nullable=False), sa.Column("text", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("external_id", sa.String()),
        sa.Column("error_code", sa.String()), sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("run_id", "tool_call_id"))
    op.create_index("ix_qq_deliveries_session_id", "qq_deliveries", ["session_id"])
    op.create_index("ix_qq_deliveries_run_id", "qq_deliveries", ["run_id"])


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
