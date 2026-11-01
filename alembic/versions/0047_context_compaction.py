"""Add rolling checkpoints and reset affected disposable chat sessions."""
from alembic import op
import sqlalchemy as sa
import json

revision = "0047_context_compaction"
down_revision = "0046_qq_commands"
branch_labels = None
depends_on = None


def upgrade():
    sessions = "SELECT session_id FROM sessionrecord WHERE kind IN ('ordinary', 'workspace')"
    runs = f"SELECT run_id FROM runrecord WHERE session_id IN ({sessions})"
    for table in ("runeventrecord", "runsteprecord"):
        op.execute(sa.text(f"DELETE FROM {table} WHERE run_id IN ({runs})"))
    for table in ("messagerecord", "runrecord", "session_knowledge_bindings", "web_session_pages"):
        op.execute(sa.text(f"DELETE FROM {table} WHERE session_id IN ({sessions})"))
    op.execute(sa.text(f"DELETE FROM sessionrecord WHERE session_id IN ({sessions})"))
    # Discard old policy values; no interpretation or conversion of numeric limits.
    op.get_bind().execute(sa.text("""UPDATE projects SET configuration_json = json_set(configuration_json,
        '$.context_policy', json(:policy)) WHERE kind = 'workspace'"""), {"policy": json.dumps({
            "history_enabled": True, "include_attachments": "explicit", "compaction": {
                "enabled": True, "trigger_percent": 80, "target_percent": 55, "max_summary_tokens": None}})})
    with op.batch_alter_table("runsteprecord") as batch:
        batch.drop_constraint("ck_runsteprecord_kind", type_="check")
        batch.create_check_constraint("ck_runsteprecord_kind", "kind IN ('context', 'model', 'compaction', 'save', 'approval', 'tool')")
    op.create_table("context_checkpoints",
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessionrecord.session_id"), primary_key=True),
        sa.Column("checkpoint_json", sa.Text(), nullable=False))


def downgrade():
    raise RuntimeError("Destructive test database downgrade is unsupported")
