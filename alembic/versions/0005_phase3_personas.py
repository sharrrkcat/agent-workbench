"""Database personas; discard disposable chat rows without filesystem changes."""

from alembic import op
import sqlalchemy as sa

revision = "0005_phase3_personas"
down_revision = "0004_phase2b_runtimes"
branch_labels = None
depends_on = None


DDL = (
    """CREATE TABLE personas (
        id VARCHAR NOT NULL PRIMARY KEY, name VARCHAR NOT NULL,
        avatar_attachment_id VARCHAR, system_prompt VARCHAR NOT NULL,
        model_profile_id VARCHAR REFERENCES model_profiles(id),
        context_policy_json VARCHAR NOT NULL, generation_json VARCHAR NOT NULL,
        harness_enabled BOOLEAN NOT NULL, tools_allowed_json VARCHAR NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )""",
    "CREATE INDEX ix_personas_model_profile_id ON personas (model_profile_id)",
    """CREATE TABLE sessionrecord (
        session_id VARCHAR NOT NULL PRIMARY KEY, title VARCHAR NOT NULL,
        context_mode VARCHAR NOT NULL, waiting_run_id VARCHAR, model_profile_id VARCHAR,
        current_persona_id VARCHAR NOT NULL REFERENCES personas(id),
        context_policy_json VARCHAR, generation_json VARCHAR, harness_enabled BOOLEAN,
        tools_allowed_json VARCHAR, knowledge_binding_mode VARCHAR NOT NULL,
        worldbook_binding_mode VARCHAR NOT NULL, title_generation_state VARCHAR NOT NULL,
        title_generation_metadata_json VARCHAR NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )""",
    """CREATE TABLE session_personas (
        session_id VARCHAR NOT NULL,
        persona_id VARCHAR NOT NULL,
        sort_order INTEGER NOT NULL, enabled BOOLEAN NOT NULL,
        PRIMARY KEY (session_id, persona_id),
        FOREIGN KEY(session_id) REFERENCES sessionrecord(session_id),
        FOREIGN KEY(persona_id) REFERENCES personas(id)
    )""",
    "CREATE INDEX ix_session_personas_persona_id ON session_personas (persona_id)",
    """CREATE TABLE persona_knowledge_bindings (
        persona_id VARCHAR NOT NULL,
        knowledge_base_id VARCHAR NOT NULL,
        sort_order INTEGER NOT NULL, PRIMARY KEY (persona_id, knowledge_base_id),
        FOREIGN KEY(persona_id) REFERENCES personas(id),
        FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(id)
    )""",
    "CREATE INDEX ix_persona_knowledge_bindings_knowledge_base_id ON persona_knowledge_bindings (knowledge_base_id)",
    """CREATE TABLE persona_worldbook_bindings (
        persona_id VARCHAR NOT NULL,
        worldbook_id VARCHAR NOT NULL,
        sort_order INTEGER NOT NULL, PRIMARY KEY (persona_id, worldbook_id),
        FOREIGN KEY(persona_id) REFERENCES personas(id),
        FOREIGN KEY(worldbook_id) REFERENCES worldbooks(id)
    )""",
    "CREATE INDEX ix_persona_worldbook_bindings_worldbook_id ON persona_worldbook_bindings (worldbook_id)",
    """CREATE TABLE runrecord (
        run_id VARCHAR NOT NULL PRIMARY KEY, kind VARCHAR NOT NULL,
        persona_id VARCHAR NOT NULL, config_snapshot_json VARCHAR NOT NULL,
        session_id VARCHAR NOT NULL, status VARCHAR NOT NULL,
        current_step VARCHAR NOT NULL, stage VARCHAR NOT NULL, progress_message VARCHAR NOT NULL,
        progress_current INTEGER, progress_total INTEGER, cancel_requested BOOLEAN NOT NULL,
        started_at DATETIME, finished_at DATETIME, error_code VARCHAR, error_message VARCHAR,
        error VARCHAR, metadata_json VARCHAR NOT NULL, created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT ck_runrecord_kind CHECK (kind IN ('chat', 'resume'))
    )""",
    "CREATE INDEX ix_runrecord_persona_id ON runrecord (persona_id)",
    "CREATE INDEX ix_runrecord_session_id ON runrecord (session_id)",
)


def upgrade() -> None:
    # No chat data conversion: the project has only disposable test conversations.
    for table in ("runeventrecord", "runsteprecord", "messagerecord",
                  "session_knowledge_bindings", "session_worldbook_bindings"):
        op.execute(sa.text(f"DELETE FROM {table}"))
    op.drop_table("runrecord")
    op.drop_table("sessionrecord")
    for statement in DDL:
        op.execute(sa.text(statement))
    seed = sa.text("""INSERT INTO personas
        (id, name, system_prompt, context_policy_json, generation_json,
         harness_enabled, tools_allowed_json, created_at, updated_at)
        VALUES (:id, :name, :prompt, :policy, '{}', 0, '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
    for persona_id, name, prompt, mode in (
        ("00000000-0000-4000-8000-000000000001", "Chat", "You are a helpful assistant.", "session"),
        ("00000000-0000-4000-8000-000000000002", "Translate",
         "Translate the user's text accurately. Return only the translation.", "current_message"),
    ):
        op.get_bind().execute(seed, dict(id=persona_id, name=name, prompt=prompt,
            policy='{"mode":"' + mode + '","include_attachments":"explicit"}'))


def downgrade() -> None:
    raise RuntimeError("destructive test database downgrade is unsupported")
