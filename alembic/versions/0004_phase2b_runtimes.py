"""Managed runtime configuration and installation jobs; no filesystem changes."""
from alembic import op
import sqlalchemy as sa

revision = "0004_phase2b_runtimes"
down_revision = "0003_phase2a_models"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("model_profiles", sa.Column("runtime_id", sa.String(), nullable=True))
    op.add_column("model_profiles", sa.Column("runtime_variant", sa.String(), nullable=True))
    op.add_column("model_profiles", sa.Column("runtime_options_json", sa.String(), nullable=False, server_default="{}"))
    op.create_table("runtime_installations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("runtime_id", sa.String(), nullable=False),
        sa.Column("variant", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("job_id", sa.String()),
        sa.Column("error_code", sa.String()),
        sa.Column("manifest_sha256", sa.String()),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("runtime_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("runtime_id", sa.String(), nullable=False),
        sa.Column("variant", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer()),
        sa.Column("error_code", sa.String()),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("log_path", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()))


def downgrade():
    raise RuntimeError("Phase 2b test database downgrade is unsupported")
