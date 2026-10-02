"""Remove history modes and selected-message configuration."""
from alembic import op
import sqlalchemy as sa

revision = "0026_history_limits"
down_revision = "0025_model_request_options"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    connection.execute(sa.text("""UPDATE sessionrecord SET configuration_json = json_remove(
        configuration_json, '$.context_policy.mode', '$.overrides.context_policy.mode')"""))
    connection.execute(sa.text("""UPDATE projects SET configuration_json = json_remove(
        configuration_json, '$.context_policy.mode')"""))
    connection.execute(sa.text("""UPDATE runrecord SET
        config_snapshot_json = json_remove(config_snapshot_json, '$.context_policy.mode'),
        metadata_json = json_remove(metadata_json, '$.context_source_message_id', '$.configuration.context_policy.mode')"""))


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
