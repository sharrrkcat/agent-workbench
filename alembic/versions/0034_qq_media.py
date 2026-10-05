"""Persist ordered QQ media without rewriting existing transcript records."""
from alembic import op
import sqlalchemy as sa

revision = "0034_qq_media"
down_revision = "0033_qq_history_deletion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("qq_media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("text_start", sa.Integer(), nullable=False),
        sa.Column("text_end", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("source_json", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attachment_json", sa.String(), nullable=True),
        sa.Column("model_attachment_json", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.UniqueConstraint("message_id", "segment_index"), sqlite_autoincrement=True)
    op.create_index("ix_qq_media_message_id", "qq_media", ["message_id"])
    op.create_index("ix_qq_media_pending", "qq_media", ["status", "id"])


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
