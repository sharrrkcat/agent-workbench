"""Runtime maintenance jobs; reset disposable task history without touching files."""
from alembic import op
import sqlalchemy as sa

revision = "0010_runtime_maintenance"
down_revision = "0009_pet_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE runtime_installations SET job_id = NULL")
    op.drop_table("runtime_jobs")
    op.create_table("runtime_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("runtime_id", sa.String()),
        sa.Column("variant", sa.String()),
        sa.Column("version", sa.String()),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("result_json", sa.String()),
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
    raise RuntimeError("Runtime maintenance test database downgrade is unsupported")
