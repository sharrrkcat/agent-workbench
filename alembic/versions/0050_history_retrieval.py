"""Store private on-demand history state independently of rolling summaries."""
from alembic import op
import sqlalchemy as sa

revision = "0050_history_retrieval"
down_revision = "0049_qq_context_compaction"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("context_retrieval",
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessionrecord.session_id"), primary_key=True),
        sa.Column("state_json", sa.Text(), nullable=False))


def downgrade():
    op.drop_table("context_retrieval")
