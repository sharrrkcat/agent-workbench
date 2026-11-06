"""Add attributed durable facts and bind new normal conversations to a Persona."""

from alembic import op
import sqlalchemy as sa


revision = "0053_durable_memory"
down_revision = "0052_characters_personas"
branch_labels = None
depends_on = None


def upgrade():
    # Existing normal history can contain mixed Personas. Recreate disposable
    # normal conversations, retaining identities, QQ data and all data files.
    normal = "SELECT session_id FROM sessionrecord WHERE kind = 'normal'"
    runs = f"SELECT run_id FROM runrecord WHERE session_id IN ({normal})"
    op.execute(sa.text(f"DELETE FROM runsteprecord WHERE run_id IN ({runs})"))
    for table in ("web_session_pages", "context_checkpoints", "context_retrieval", "runeventrecord", "messagerecord", "runrecord"):
        op.execute(sa.text(f"DELETE FROM {table} WHERE session_id IN ({normal})"))
    op.execute(sa.text("DELETE FROM sessionrecord WHERE kind = 'normal'"))
    op.add_column("sessionrecord", sa.Column("bound_persona_id", sa.String()))
    op.add_column("sessionrecord", sa.Column("memory_isolation", sa.String(), nullable=False, server_default="shared"))
    op.add_column("sessionrecord", sa.Column("memory_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("durable_memories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("pool", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False),
        sa.Column("persona_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("managed_by", sa.String(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("origin_run_id", sa.String()),
        sa.Column("origin_session_id", sa.String()),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.CheckConstraint("pool IN ('character', 'general')", name="ck_memory_pool"),
        sa.CheckConstraint("pool != 'general' OR session_id IS NULL", name="ck_general_memory_session"),
        sa.CheckConstraint("status IN ('active', 'needs_review', 'deleted')", name="ck_memory_status"))
    op.create_index("ix_memory_audience", "durable_memories", ["persona_id", "pool", "character_id", "status"])
    for name in ("persona_id", "session_id", "origin_run_id", "origin_session_id"):
        op.create_index(f"ix_durable_memories_{name}", "durable_memories", [name])
    op.create_table("durable_memory_terms",
        sa.Column("memory_id", sa.String(), primary_key=True),
        sa.Column("term", sa.String(), primary_key=True),
        sa.Column("weight", sa.Integer(), nullable=False))
    op.create_index("ix_durable_memory_terms_term", "durable_memory_terms", ["term"])
    for table, key in (("durable_memory_dependencies", "session_id"), ("durable_memory_evidence", "message_id")):
        op.create_table(table, sa.Column("memory_id", sa.String(), primary_key=True), sa.Column(key, sa.String(), primary_key=True))
        op.create_index(f"ix_{table}_{key}", table, [key])


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
