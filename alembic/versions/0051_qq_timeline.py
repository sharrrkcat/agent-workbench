"""Index bounded QQ timeline reads and pending program work without changing records."""
from alembic import op
import sqlalchemy as sa

revision = "0051_qq_timeline"
down_revision = "0050_history_retrieval"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_qq_message_timeline", "qq_messages", ["session_id", "timestamp", "id"], sqlite_where=sa.text("deleted = 0"))
    op.create_index("ix_qq_program_timeline", "qq_deliveries", ["session_id", "created_at", "id"], sqlite_where=sa.text("deleted = 0 AND origin != 'model'"))
    op.create_index("ix_qq_program_delivery_pending", "qq_deliveries", ["session_id", "id"], sqlite_where=sa.text("status = 'pending' AND deleted = 0 AND origin != 'model'"))
    op.create_index("ix_qq_batch_active_session", "qq_batches", ["session_id"], sqlite_where=sa.text("status = 'running'"))


def downgrade():
    for name, table in (("ix_qq_batch_active_session", "qq_batches"), ("ix_qq_program_delivery_pending", "qq_deliveries"),
                        ("ix_qq_program_timeline", "qq_deliveries"), ("ix_qq_message_timeline", "qq_messages")):
        op.drop_index(name, table_name=table)
