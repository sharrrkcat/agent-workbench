"""Unify memory controls and remove review-only records and evidence indexes."""

from alembic import op
import sqlalchemy as sa


revision = "0054_memory_controls"
down_revision = "0053_durable_memory"
branch_labels = None
depends_on = None


def upgrade():
    for table, column, paths in (
        ("characters", "configuration_json", ("$.memory_learning",)),
        ("sessionrecord", "configuration_json", ("$.overrides.memory_learning",)),
        ("runrecord", "config_snapshot_json", ("$.memory_learning", "$.sources.memory_learning")),
        ("runrecord", "metadata_json", ("$.configuration.memory_learning", "$.configuration.sources.memory_learning")),
    ):
        arguments = ", ".join(f"'{path}'" for path in paths)
        op.execute(sa.text(f"UPDATE {table} SET {column} = json_remove({column}, {arguments})"))

    # Policy semantics changed; old derived context must not retain recalled facts.
    normal = "SELECT session_id FROM sessionrecord WHERE kind = 'normal'"
    for table in ("context_checkpoints", "context_retrieval"):
        op.execute(sa.text(f"DELETE FROM {table} WHERE session_id IN ({normal})"))
    op.execute(sa.text("UPDATE sessionrecord SET memory_version = memory_version + 1 WHERE kind = 'normal'"))

    obsolete = "SELECT id FROM durable_memories WHERE status = 'needs_review'"
    for table in ("durable_memory_terms", "durable_memory_dependencies"):
        op.execute(sa.text(f"DELETE FROM {table} WHERE memory_id IN ({obsolete})"))
    op.execute(sa.text("DELETE FROM durable_memories WHERE status = 'needs_review'"))
    op.drop_table("durable_memory_evidence")
    with op.batch_alter_table("durable_memories") as batch:
        batch.drop_constraint("ck_memory_status", type_="check")
        batch.create_check_constraint("ck_memory_status", "status IN ('active', 'deleted')")


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
