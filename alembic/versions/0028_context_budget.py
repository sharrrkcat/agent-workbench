"""Add the provider LLM window setting without changing model resources."""
from alembic import op
import sqlalchemy as sa

revision = "0028_context_budget"
down_revision = "0027_context_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_profiles", sa.Column("context_window_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("destructive test database downgrade is unsupported")
