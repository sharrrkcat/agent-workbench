"""Add typed Projects and replace disposable conversation configuration."""

from alembic import op
import sqlalchemy as sa


revision = "0022_projects"
down_revision = "0021_persona_collections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("runeventrecord", "runsteprecord", "messagerecord", "runrecord", "session_knowledge_bindings"):
        op.execute(sa.text(f"DELETE FROM {table}"))
    op.drop_table("sessionrecord")
    op.create_table("projects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("configuration_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('workspace', 'timeline')", name="ck_project_kind"))
    for table, resource, target in (
        ("project_knowledge_bindings", "knowledge_base_id", "knowledge_bases.id"),
        ("project_worldbook_bindings", "worldbook_id", "worldbooks.id"),
    ):
        op.create_table(table,
            sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), primary_key=True),
            sa.Column(resource, sa.String(), sa.ForeignKey(target), primary_key=True),
            sa.Column("sort_order", sa.Integer(), nullable=False))
    op.create_table("sessionrecord",
        sa.Column("session_id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id")),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("waiting_run_id", sa.String()),
        sa.Column("configuration_json", sa.String(), nullable=False),
        sa.Column("title_generation_state", sa.String(), nullable=False),
        sa.Column("title_generation_metadata_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('ordinary', 'workspace')", name="ck_session_kind"),
        sa.CheckConstraint("(kind = 'ordinary' AND project_id IS NULL) OR (kind = 'workspace' AND project_id IS NOT NULL)", name="ck_session_project"))
    op.create_index("ix_sessionrecord_project_id", "sessionrecord", ["project_id"])


def downgrade() -> None:
    raise RuntimeError("destructive test database downgrade is unsupported")
