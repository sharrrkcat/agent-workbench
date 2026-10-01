"""Replace editable capability declarations with request options."""
from alembic import op
import sqlalchemy as sa

revision = "0025_model_request_options"
down_revision = "0024_runtime_always_enabled"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_column("capabilities_json")
        batch.add_column(sa.Column("request_options_json", sa.Text(), nullable=True))
    op.get_bind().execute(sa.text("UPDATE model_profiles SET request_options_json = :options WHERE kind = 'llm'"),
        {"options": '{"streaming":true,"skip_tool_capability_check":false,"skip_vision_capability_check":false}'})


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
