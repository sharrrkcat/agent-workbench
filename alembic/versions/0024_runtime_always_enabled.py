"""Remove the local runtime enablement setting."""
from alembic import op
import sqlalchemy as sa

revision = "0024_runtime_always_enabled"
down_revision = "0023_dlss_processor"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("""UPDATE appmetadatarecord
        SET value = json_remove(value, '$.enabled')
        WHERE key = 'local_runtime_settings'"""))


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
