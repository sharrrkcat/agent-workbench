"""Unify Persona collections and remove disposable group-chat configuration."""

from alembic import op
import sqlalchemy as sa


revision = "0021_persona_collections"
down_revision = "0020_directory_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (
        "runeventrecord", "runsteprecord", "messagerecord", "runrecord",
        "session_knowledge_bindings", "persona_knowledge_bindings", "persona_worldbook_bindings",
    ):
        op.execute(sa.text(f"DELETE FROM {table}"))
    for table in ("session_worldbook_bindings", "session_personas", "sessionrecord", "personas"):
        op.drop_table(table)
    op.execute(sa.text("DELETE FROM appmetadatarecord WHERE key = 'app_settings'"))
    op.execute(sa.text("""CREATE TABLE personas (
        id VARCHAR NOT NULL PRIMARY KEY, collection VARCHAR NOT NULL, name VARCHAR NOT NULL,
        avatar_attachment_id VARCHAR, system_prompt VARCHAR NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        CONSTRAINT ck_persona_collection CHECK (collection IN ('user', 'agent', 'roleplay_user', 'character')),
        CONSTRAINT ck_user_persona_singleton CHECK (collection != 'user' OR id = '00000000-0000-4000-8000-000000000004')
    )"""))
    op.create_index("ix_personas_collection", "personas", ["collection"])
    op.execute(sa.text("""CREATE TABLE sessionrecord (
        session_id VARCHAR NOT NULL PRIMARY KEY, title VARCHAR NOT NULL,
        waiting_run_id VARCHAR, model_profile_id VARCHAR,
        persona_id VARCHAR NOT NULL REFERENCES personas(id),
        context_policy_json VARCHAR NOT NULL, generation_json VARCHAR NOT NULL,
        harness_enabled BOOLEAN NOT NULL, tools_allowed_json VARCHAR NOT NULL,
        title_generation_state VARCHAR NOT NULL, title_generation_metadata_json VARCHAR NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )"""))
    seed = sa.text("""INSERT INTO personas (id, collection, name, system_prompt, created_at, updated_at)
        VALUES (:id, :collection, :name, :prompt, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
    for persona_id, collection, name, prompt in (
        ("00000000-0000-4000-8000-000000000003", "agent", "Cogita", "You are a helpful assistant."),
        ("00000000-0000-4000-8000-000000000004", "user", "User", ""),
    ):
        op.get_bind().execute(seed, {"id": persona_id, "collection": collection, "name": name, "prompt": prompt})


def downgrade() -> None:
    raise RuntimeError("destructive test database downgrade is unsupported")
