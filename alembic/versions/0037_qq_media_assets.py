"""Replace disposable QQ history with shared media resources; never touch files."""
from alembic import op
import sqlalchemy as sa

revision = "0037_qq_media_assets"
down_revision = "0036_image_generation"
branch_labels = None
depends_on = None


def upgrade():
    sessions = "SELECT session_id FROM sessionrecord WHERE kind = 'qqbot'"
    runs = f"SELECT run_id FROM runrecord WHERE session_id IN ({sessions})"
    op.execute(f"DELETE FROM runsteprecord WHERE run_id IN ({runs})")
    for table in ("runeventrecord", "messagerecord", "runrecord"):
        op.execute(f"DELETE FROM {table} WHERE session_id IN ({sessions})")
    op.execute(f"UPDATE sessionrecord SET waiting_run_id = NULL, history_version = history_version + 1 WHERE session_id IN ({sessions})")
    op.drop_table("qq_media")
    for table in ("qq_deliveries", "qq_batches", "qq_participants", "qq_messages"):
        op.execute(f"DELETE FROM {table}")
    op.execute("UPDATE qq_bindings SET deadline = NULL, window_kind = 'keyword'")
    op.create_table("qq_media_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("attachment_json", sa.String(), nullable=False),
        sa.Column("model_attachment_json", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("sha256"), sqlite_autoincrement=True)
    op.create_table("qq_media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("text_start", sa.Integer(), nullable=False),
        sa.Column("text_end", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("source_json", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("qq_media_assets.id"), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.UniqueConstraint("message_id", "segment_index"), sqlite_autoincrement=True)
    op.create_index("ix_qq_media_message_id", "qq_media", ["message_id"])
    op.create_index("ix_qq_media_asset_id", "qq_media", ["asset_id"])
    op.create_index("ix_qq_media_pending", "qq_media", ["status", "id"])


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
