"""Allow independent manual compaction runs without changing existing data."""
from alembic import op

revision = "0048_manual_compaction"
down_revision = "0047_context_compaction"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("runrecord") as batch:
        batch.drop_constraint("ck_runrecord_kind", type_="check")
        batch.create_check_constraint("ck_runrecord_kind", "kind IN ('chat', 'tool', 'compaction')")


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
