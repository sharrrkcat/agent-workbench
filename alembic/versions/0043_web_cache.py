"""Store bounded web-tool evidence separately from cached page bodies."""
from alembic import op
import sqlalchemy as sa

revision = "0043_web_cache"
down_revision = "0042_qq_image_tools"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("web_pages",
        sa.Column("url_key", sa.String(), primary_key=True),
        sa.Column("raw_url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("snippet", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("links_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("content_src", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("content_src IN ('search', 'extract')", name="ck_web_content_src"))
    op.create_index("ix_web_pages_last_accessed_at", "web_pages", ["last_accessed_at"])
    op.create_table("web_session_pages",
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessionrecord.session_id"), primary_key=True),
        sa.Column("url_key", sa.String(), sa.ForeignKey("web_pages.url_key"), primary_key=True),
        sa.Column("query", sa.String(), primary_key=True),
        sa.Column("accessed_at", sa.DateTime(), nullable=False))
    op.create_index("ix_web_session_pages_url_key", "web_session_pages", ["url_key"])


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
