"""Destructive Phase 1 schema replacement.

The project has no production users yet.  This revision intentionally drops
the baseline tables and recreates the compact SQLModel schema.  It does not
read, copy, count, or transform rows.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0002_phase1_prune"
down_revision = "0001_current_schema"
branch_labels = None
depends_on = None


# The baseline table names are listed explicitly so the operation remains
# deterministic and does not depend on reflection or application data.
DROP_TABLES = (
    "kb_chunk_fts",
    "agentconfigrecord",
    "capabilityconfigrecord",
    "sessionagentstaterecord",
    "image_generation_model_profiles",
    "reranker_model_profiles",
    "kb_origins",
    "messagerecord",
    "runsteprecord",
    "runrecord",
    "runeventrecord",
    "sessionrecord",
    "appmetadatarecord",
    "knowledge_settings",
    "knowledge_bases",
    "kb_sources",
    "kb_chunks",
    "kb_embeddings",
    "session_knowledge_bindings",
    "worldbook_settings",
    "worldbooks",
    "worldbook_entries",
    "session_worldbook_bindings",
    "llm_profiles",
    "llm_provider_profiles",
    "embedding_model_profiles",
    "multimodal_embedding_model_profiles",
    "vision_model_profiles",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(text("PRAGMA foreign_keys=OFF"))
    for table in DROP_TABLES:
        op.execute(text(f'DROP TABLE IF EXISTS "{table}"'))

    # Importing the static SQLModel declarations is safe here: create_all only
    # emits DDL for the just-dropped tables and performs no row reads.
    from sqlmodel import SQLModel
    import ai_workbench.db.models  # noqa: F401

    SQLModel.metadata.create_all(bind=bind)
    if bind.dialect.name == "sqlite":
        op.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunk_fts
                USING fts5(
                  chunk_id UNINDEXED,
                  knowledge_base_id UNINDEXED,
                  source_id UNINDEXED,
                  title,
                  heading_path,
                  content,
                  search_text,
                  tokenize = 'unicode61'
                )
                """
            )
        )
        op.execute(text("PRAGMA foreign_keys=ON"))


def downgrade() -> None:
    raise RuntimeError("destructive Phase 1 migration downgrade is unsupported")

