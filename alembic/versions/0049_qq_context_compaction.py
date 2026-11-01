"""Reset QQ context policies for token/window history without touching records."""
import json

from alembic import op
import sqlalchemy as sa

revision = "0049_qq_context_compaction"
down_revision = "0048_manual_compaction"
branch_labels = None
depends_on = None


def upgrade():
    policy = {"history_enabled": True, "strategy": "token_budget", "include_attachments": "none",
        "compaction": {"enabled": True, "trigger_percent": 80, "target_percent": 55, "max_summary_tokens": None},
        "message_window": {"max_messages": 100}}
    op.get_bind().execute(sa.text("""UPDATE projects SET configuration_json = json_set(configuration_json,
        '$.context_policy', json(:policy)) WHERE kind = 'qqbot'"""), {"policy": json.dumps(policy)})


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
