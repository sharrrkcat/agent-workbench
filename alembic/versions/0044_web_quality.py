"""Remove codec tool selections and discard derived web caches."""
import json

from alembic import op
import sqlalchemy as sa

revision = "0044_web_quality"
down_revision = "0043_web_cache"
branch_labels = None
depends_on = None
REMOVED = {"base64_encode", "base64_decode"}


def upgrade():
    connection = op.get_bind()
    for table, identity in (("sessionrecord", "session_id"), ("projects", "id")):
        for key, raw in connection.execute(sa.text(f"SELECT {identity}, configuration_json FROM {table}")).all():
            config = json.loads(raw)
            for settings in (config, config.get("overrides", {})):
                if isinstance(settings.get("tools_allowed"), list):
                    settings["tools_allowed"] = [name for name in settings["tools_allowed"] if name not in REMOVED]
            connection.execute(sa.text(f"UPDATE {table} SET configuration_json=:config WHERE {identity}=:key"),
                               {"config": json.dumps(config, ensure_ascii=False), "key": key})
    for run_id, config, state in connection.execute(sa.text("""SELECT run_id, config_snapshot_json, harness_state_json
            FROM runrecord WHERE status IN ('PENDING','RUNNING','CANCELLING','WAITING_FOR_USER')""")).all():
        if not any('"' + name + '"' in (config + state) for name in REMOVED):
            continue
        message = "Execution was interrupted because a selected tool was removed."
        connection.execute(sa.text("""UPDATE runrecord SET status='INTERRUPTED', current_step='interrupted', stage='interrupted',
            error_code='RUN_INTERRUPTED', error_message=:message, harness_state_json='{}',
            finished_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE run_id=:id"""), {"id": run_id, "message": message})
        connection.execute(sa.text("""UPDATE runsteprecord SET status='failed', error_code='RUN_INTERRUPTED',
            error_message=:message, finished_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE run_id=:id AND status IN ('pending','running')"""), {"id": run_id, "message": message})
        connection.execute(sa.text("UPDATE sessionrecord SET waiting_run_id=NULL WHERE waiting_run_id=:id"), {"id": run_id})
    connection.execute(sa.text("DELETE FROM web_session_pages"))
    connection.execute(sa.text("DELETE FROM web_pages"))


def downgrade():
    raise RuntimeError("destructive test database downgrade is unsupported")
