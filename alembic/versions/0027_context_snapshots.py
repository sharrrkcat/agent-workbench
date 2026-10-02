"""Persist private per-model-call context snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0027_context_snapshots"
down_revision = "0026_history_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runsteprecord", sa.Column("context_snapshot_json", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("destructive test database downgrade is unsupported")
