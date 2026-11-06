"""Replace disposable conversation ownership with Characters and user Personas."""

from alembic import op
import sqlalchemy as sa


revision = "0052_characters_personas"
down_revision = "0051_qq_timeline"
branch_labels = None
depends_on = None


def upgrade():
    # Shared catalogs/assets and their files are deliberately outside this reset.
    for table in (
        "qq_notifications", "qq_deliveries", "qq_media", "qq_participants",
        "qq_messages", "qq_batches", "qq_bindings", "web_session_pages",
        "context_checkpoints", "context_retrieval", "runeventrecord",
        "runsteprecord", "messagerecord", "runrecord",
    ):
        op.execute(sa.text(f"DELETE FROM {table}"))
    for table in (
        "session_knowledge_bindings", "persona_knowledge_bindings", "persona_worldbook_bindings",
        "project_knowledge_bindings", "project_worldbook_bindings", "sessionrecord", "projects", "personas",
    ):
        op.drop_table(table)

    op.create_table("personas",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("avatar_attachment_id", sa.String()),
        sa.Column("background", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.execute(sa.text("""INSERT INTO personas (id, name, background, created_at, updated_at)
        VALUES ('00000000-0000-4000-8000-000000000004', 'User', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""))
    op.create_table("characters",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("configuration_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('normal', 'qqbot')", name="ck_character_kind"))
    # Runtime bootstrap creates Cogita through normal Character creation, so the
    # initial model and tool list use the same one-time selection as other entries.
    op.create_table("sessionrecord",
        sa.Column("session_id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), sa.ForeignKey("characters.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("waiting_run_id", sa.String()),
        sa.Column("configuration_json", sa.String(), nullable=False),
        sa.Column("title_generation_state", sa.String(), nullable=False),
        sa.Column("title_generation_metadata_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("history_version", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("kind IN ('normal', 'qqbot')", name="ck_session_kind"))
    op.create_index("ix_sessionrecord_character_id", "sessionrecord", ["character_id"])

    with op.batch_alter_table("runrecord") as batch:
        batch.add_column(sa.Column("character_id", sa.String(), nullable=False))
        batch.alter_column("persona_id", existing_type=sa.String(), nullable=True)
        batch.create_index("ix_runrecord_character_id", ["character_id"])

    for table in ("qq_bindings", "qq_batches", "qq_notifications"):
        op.alter_column(table, "project_id", new_column_name="character_id")
    for table in ("qq_bindings", "qq_notifications"):
        op.drop_index(f"ix_{table}_project_id", table_name=table)
        op.create_index(f"ix_{table}_character_id", table, ["character_id"])


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
