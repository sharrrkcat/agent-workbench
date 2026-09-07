"""Add private harness state and direct tool runs."""

from alembic import op
import sqlalchemy as sa


revision = "0006_phase4_tools"
down_revision = "0005_phase3_personas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Chat/run rows are disposable in the test phase. Rebuild the constrained
    # run table so SQLite can change the kind check without compatibility code.
    op.execute(sa.text("DELETE FROM runsteprecord"))
    op.execute(sa.text("DELETE FROM runeventrecord"))
    op.execute(sa.text("DELETE FROM messagerecord"))
    op.execute(sa.text("UPDATE sessionrecord SET waiting_run_id = NULL"))
    op.execute(sa.text("DROP TABLE runrecord"))
    op.execute(sa.text("""CREATE TABLE runrecord (
        run_id VARCHAR NOT NULL PRIMARY KEY, kind VARCHAR NOT NULL,
        persona_id VARCHAR NOT NULL, config_snapshot_json VARCHAR NOT NULL,
        harness_state_json VARCHAR NOT NULL, session_id VARCHAR NOT NULL,
        status VARCHAR NOT NULL, current_step VARCHAR NOT NULL,
        stage VARCHAR NOT NULL, progress_message VARCHAR NOT NULL,
        progress_current INTEGER, progress_total INTEGER,
        cancel_requested BOOLEAN NOT NULL, started_at DATETIME,
        finished_at DATETIME, error_code VARCHAR, error_message VARCHAR,
        error VARCHAR, metadata_json VARCHAR NOT NULL, created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT ck_runrecord_kind CHECK (kind IN ('chat', 'tool'))
    )"""))
    op.execute(sa.text("CREATE INDEX ix_runrecord_persona_id ON runrecord (persona_id)"))
    op.execute(sa.text("CREATE INDEX ix_runrecord_session_id ON runrecord (session_id)"))


def downgrade() -> None:
    raise RuntimeError("destructive test database downgrade is unsupported")
