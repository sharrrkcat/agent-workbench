"""Add generated-image delivery references; never modify attachment files."""
from alembic import op
import sqlalchemy as sa

revision = "0038_qq_image_generation"
down_revision = "0037_qq_media_assets"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("qq_deliveries") as batch:
        batch.add_column(sa.Column("kind", sa.String(), nullable=False, server_default="text"))
        batch.add_column(sa.Column("prompt", sa.String(), nullable=True))
        batch.add_column(sa.Column("asset_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_qq_delivery_asset", "qq_media_assets", ["asset_id"], ["id"])
        batch.create_index("ix_qq_deliveries_asset_id", ["asset_id"])


def downgrade():
    raise RuntimeError("test database downgrade is unsupported")
