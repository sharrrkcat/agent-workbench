"""Discard application settings containing retired display configuration."""

from alembic import op
import sqlalchemy as sa


revision = "0007_phase5_cleanup"
down_revision = "0006_phase4_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # General, Core Memory and Pet share this disposable test-state object.
    # The next read uses defaults; no JSON conversion or file operations.
    op.execute(sa.text("DELETE FROM appmetadatarecord WHERE key = 'app_settings'"))


def downgrade() -> None:
    raise RuntimeError("destructive test database downgrade is unsupported")
