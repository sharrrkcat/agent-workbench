"""Discard disposable settings containing the removed Pet presentation schema."""

from alembic import op
import sqlalchemy as sa


revision = "0009_pet_foundation"
down_revision = "0008_chat_configuration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM appmetadatarecord WHERE key = 'app_settings'"))


def downgrade() -> None:
    raise RuntimeError("destructive test database downgrade is unsupported")
