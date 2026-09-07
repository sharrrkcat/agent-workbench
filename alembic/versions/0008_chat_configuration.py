"""Make chat configuration session-owned; discard affected disposable records."""

from alembic import op
import sqlalchemy as sa


revision = "0008_chat_configuration"
down_revision = "0007_phase5_cleanup"
branch_labels = None
depends_on = None


DDL = (
    """CREATE TABLE personas (
        id VARCHAR NOT NULL PRIMARY KEY, name VARCHAR NOT NULL,
        avatar_attachment_id VARCHAR, system_prompt VARCHAR NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )""",
    """CREATE TABLE sessionrecord (
        session_id VARCHAR NOT NULL PRIMARY KEY, title VARCHAR NOT NULL,
        context_mode VARCHAR NOT NULL, waiting_run_id VARCHAR, model_profile_id VARCHAR,
        current_persona_id VARCHAR NOT NULL REFERENCES personas(id),
        context_policy_json VARCHAR NOT NULL, generation_json VARCHAR NOT NULL,
        harness_enabled BOOLEAN NOT NULL, tools_allowed_json VARCHAR NOT NULL,
        title_generation_state VARCHAR NOT NULL, title_generation_metadata_json VARCHAR NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )""",
)


def upgrade() -> None:
    # Old snapshots and session defaults are discarded, never converted.
    for table in (
        "runeventrecord", "runsteprecord", "messagerecord", "runrecord",
        "session_knowledge_bindings", "session_worldbook_bindings", "session_personas",
        "persona_knowledge_bindings", "persona_worldbook_bindings",
    ):
        op.execute(sa.text(f"DELETE FROM {table}"))
    op.drop_table("sessionrecord")
    op.drop_table("personas")
    for statement in DDL:
        op.execute(sa.text(statement))
    seed = sa.text("""INSERT INTO personas (id, name, system_prompt, created_at, updated_at)
        VALUES (:id, :name, :prompt, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
    for persona_id, name, prompt in (
        ("00000000-0000-4000-8000-000000000001", "Chat", "You are a helpful assistant."),
        ("00000000-0000-4000-8000-000000000002", "Translate",
         "Translate the user's text accurately. Return only the translation."),
    ):
        op.get_bind().execute(seed, {"id": persona_id, "name": name, "prompt": prompt})


def downgrade() -> None:
    raise RuntimeError("destructive test database downgrade is unsupported")
