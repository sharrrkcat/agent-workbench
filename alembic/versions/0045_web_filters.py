"""Add persistent web-search filtering and seed its initial subscriptions once."""
from alembic import op
import sqlalchemy as sa

revision = "0045_web_filters"
down_revision = "0044_web_quality"
branch_labels = None
depends_on = None


def upgrade():
    settings = op.create_table("web_filter_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("custom_rules", sa.Text(), nullable=False),
        sa.Column("next_update_at", sa.DateTime(), nullable=True))
    subscriptions = op.create_table("web_filter_subscriptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("rules_text", sa.Text(), nullable=False),
        sa.Column("rule_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("error_line", sa.Integer(), nullable=True))
    op.bulk_insert(settings, [{"id": 1, "custom_rules": "\n".join(f"*://*.{host}/*" for host in (
        "youtube.com", "instagram.com", "facebook.com", "tiktok.com", "flipboard.com", "fb.watch", "baidu.com", "ifeng.com"))}])
    sources = (
        ("BadWebsiteBlocklist", "https://raw.githubusercontent.com/popcar2/BadWebsiteBlocklist/refs/heads/main/uBlacklist.txt"),
        ("uBlacklist Pinterest", "https://raw.githubusercontent.com/rjaus/ublacklist-pinterest/main/ublacklist-pinterest.txt"),
        ("GitHub Translation", "https://raw.githubusercontent.com/arosh/ublacklist-github-translation/master/uBlacklist.txt"),
        ("uBlock-Origin dev filter", "https://raw.githubusercontent.com/quenhus/uBlock-Origin-dev-filter/main/dist/other_format/uBlacklist/all.txt"),
    )
    op.bulk_insert(subscriptions, [{"id": f"default-{i}", "name": name, "url": url,
        "enabled": True, "rules_text": "", "rule_count": 0} for i, (name, url) in enumerate(sources, 1)])


def downgrade():
    op.drop_table("web_filter_subscriptions")
    op.drop_table("web_filter_settings")

