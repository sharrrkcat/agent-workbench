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


CREATE_STATEMENTS = (
    "\nCREATE TABLE appmetadatarecord (\n\t\"key\" VARCHAR NOT NULL, \n\tvalue VARCHAR NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (\"key\")\n)\n\n",
    "\nCREATE TABLE embedding_model_profiles (\n\tid VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\talias VARCHAR NOT NULL, \n\tmodel_path VARCHAR NOT NULL, \n\tprovider_profile_id VARCHAR, \n\tprovider_model_id VARCHAR NOT NULL, \n\tdimension INTEGER, \n\tnormalize BOOLEAN NOT NULL, \n\tdocument_instruction VARCHAR NOT NULL, \n\tquery_instruction VARCHAR NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\texternal_inference_enabled BOOLEAN NOT NULL, \n\tnotes VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE kb_chunks (\n\tid VARCHAR NOT NULL, \n\tknowledge_base_id VARCHAR NOT NULL, \n\tsource_id VARCHAR NOT NULL, \n\tchunk_index INTEGER NOT NULL, \n\theading_path VARCHAR NOT NULL, \n\tcontent VARCHAR NOT NULL, \n\tchar_start INTEGER NOT NULL, \n\tchar_end INTEGER NOT NULL, \n\ttoken_count INTEGER, \n\tcontent_hash VARCHAR NOT NULL, \n\tmetadata_json VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (source_id, chunk_index)\n)\n\n",
    "\nCREATE TABLE kb_embeddings (\n\tid VARCHAR NOT NULL, \n\tknowledge_base_id VARCHAR NOT NULL, \n\tsource_id VARCHAR NOT NULL, \n\tchunk_id VARCHAR NOT NULL, \n\tembedding_model_profile_id VARCHAR NOT NULL, \n\tembedding_model_id_snapshot VARCHAR NOT NULL, \n\tembedding_dimension INTEGER NOT NULL, \n\tembedding_normalize_snapshot BOOLEAN NOT NULL, \n\tvector_blob BLOB NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE kb_sources (\n\tid VARCHAR NOT NULL, \n\tknowledge_base_id VARCHAR NOT NULL, \n\tsource_type VARCHAR NOT NULL, \n\turi VARCHAR NOT NULL, \n\ttitle VARCHAR NOT NULL, \n\trelative_path VARCHAR NOT NULL, \n\tvirtual_path VARCHAR NOT NULL, \n\tfolder_path VARCHAR NOT NULL, \n\tfile_name VARCHAR NOT NULL, \n\textension VARCHAR NOT NULL, \n\tpath_depth INTEGER NOT NULL, \n\tfile_status VARCHAR NOT NULL, \n\tsource_mtime DATETIME, \n\tsource_size_bytes INTEGER NOT NULL, \n\tmime_type VARCHAR, \n\tsize_bytes INTEGER NOT NULL, \n\tcontent_hash VARCHAR NOT NULL, \n\tindexed_at DATETIME, \n\tstatus VARCHAR NOT NULL, \n\terror VARCHAR, \n\tmetadata_json VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE knowledge_bases (\n\tid VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tdescription VARCHAR NOT NULL, \n\taliases_text VARCHAR NOT NULL, \n\tembedding_model_profile_id VARCHAR NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tindex_status VARCHAR NOT NULL, \n\tindex_error VARCHAR, \n\tvector_candidate_k_override INTEGER, \n\tkeyword_candidate_k_override INTEGER, \n\tfinal_top_k_override INTEGER, \n\tmax_context_chars_override INTEGER, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE knowledge_settings (\n\tid INTEGER NOT NULL, \n\tmodels_root VARCHAR NOT NULL, \n\tlocal_model_device VARCHAR NOT NULL, \n\tembedding_batch_size INTEGER NOT NULL, \n\tembedding_timeout_seconds INTEGER NOT NULL, \n\treranker_enabled BOOLEAN NOT NULL, \n\treranker_model_profile_id VARCHAR, \n\treranker_candidate_limit INTEGER NOT NULL, \n\thybrid_search_enabled BOOLEAN NOT NULL, \n\tdefault_vector_candidate_k INTEGER NOT NULL, \n\tdefault_keyword_candidate_k INTEGER NOT NULL, \n\tdefault_final_top_k INTEGER NOT NULL, \n\tdefault_max_context_chars INTEGER NOT NULL, \n\tdefault_min_score FLOAT, \n\tmin_score_threshold FLOAT, \n\tretrieval_max_chunks_per_source INTEGER, \n\tretrieval_max_chunks_per_knowledge_base INTEGER, \n\trrf_k INTEGER NOT NULL, \n\tdefault_chunk_size INTEGER NOT NULL, \n\tdefault_chunk_overlap INTEGER NOT NULL, \n\tmax_source_size_bytes INTEGER NOT NULL, \n\tmax_chunks_per_source INTEGER NOT NULL, \n\tmax_total_index_chars_per_source INTEGER NOT NULL, \n\tknowledge_context_instruction VARCHAR NOT NULL, \n\tknowledge_context_snippet_template VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE llm_profiles (\n\tid VARCHAR NOT NULL, \n\talias VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tprovider_profile_id VARCHAR, \n\tprovider VARCHAR NOT NULL, \n\tbase_url VARCHAR NOT NULL, \n\tapi_key VARCHAR NOT NULL, \n\tmodel_id VARCHAR NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\ttemperature FLOAT, \n\ttop_p FLOAT, \n\ttop_k INTEGER, \n\tmax_tokens INTEGER, \n\ttimeout INTEGER, \n\tsupports_vision BOOLEAN NOT NULL, \n\tsupports_tools BOOLEAN NOT NULL, \n\tsupports_reasoning BOOLEAN NOT NULL, \n\tsupports_streaming BOOLEAN NOT NULL, \n\tsupports_json_mode BOOLEAN NOT NULL, \n\texternal_inference_enabled BOOLEAN NOT NULL, \n\tnotes VARCHAR, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE llm_provider_profiles (\n\tid VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tprovider VARCHAR NOT NULL, \n\tbase_url VARCHAR NOT NULL, \n\tapi_key VARCHAR NOT NULL, \n\ttimeout_seconds INTEGER, \n\tenabled BOOLEAN NOT NULL, \n\tmetadata_json VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE messagerecord (\n\tmessage_id VARCHAR NOT NULL, \n\tsession_id VARCHAR NOT NULL, \n\trole VARCHAR NOT NULL, \n\tspeaker_type VARCHAR, \n\tspeaker_id VARCHAR, \n\tspeaker_name VARCHAR, \n\torigin VARCHAR, \n\tcontent_version INTEGER NOT NULL, \n\tparts_json VARCHAR NOT NULL, \n\trun_id VARCHAR, \n\tparent_message_id VARCHAR, \n\tmetadata_json VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (message_id)\n)\n\n",
    "\nCREATE TABLE multimodal_embedding_model_profiles (\n\tid VARCHAR NOT NULL, \n\talias VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tdescription VARCHAR NOT NULL, \n\tnotes VARCHAR NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\texternal_inference_enabled BOOLEAN NOT NULL, \n\tprovider_profile_id VARCHAR, \n\tprovider_model_id VARCHAR NOT NULL, \n\tarchitecture VARCHAR NOT NULL, \n\tbackend VARCHAR NOT NULL, \n\tembedding_space VARCHAR, \n\tdimensions INTEGER, \n\tnormalize_default BOOLEAN NOT NULL, \n\tsupported_input_types_json VARCHAR NOT NULL, \n\tpreprocessing_signature VARCHAR, \n\tpooling_strategy VARCHAR NOT NULL, \n\tmax_batch_size INTEGER, \n\tmetadata_json VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE runeventrecord (\n\tevent_id VARCHAR NOT NULL, \n\trun_id VARCHAR NOT NULL, \n\tsession_id VARCHAR NOT NULL, \n\ttype VARCHAR NOT NULL, \n\tmessage VARCHAR NOT NULL, \n\tpayload_json VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (event_id)\n)\n\n",
    "\nCREATE TABLE runrecord (\n\trun_id VARCHAR NOT NULL, \n\tkind VARCHAR NOT NULL, \n\ttarget VARCHAR NOT NULL, \n\tsession_id VARCHAR NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tcurrent_step VARCHAR NOT NULL, \n\tstage VARCHAR NOT NULL, \n\tprogress_message VARCHAR NOT NULL, \n\tprogress_current INTEGER, \n\tprogress_total INTEGER, \n\tcancel_requested BOOLEAN NOT NULL, \n\tstarted_at DATETIME, \n\tfinished_at DATETIME, \n\terror_code VARCHAR, \n\terror_message VARCHAR, \n\terror VARCHAR, \n\tmetadata_json VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (run_id), \n\tCONSTRAINT ck_runrecord_kind CHECK (kind IN ('chat', 'resume'))\n)\n\n",
    "\nCREATE TABLE runsteprecord (\n\tstep_id VARCHAR NOT NULL, \n\trun_id VARCHAR NOT NULL, \n\tkind VARCHAR NOT NULL, \n\tparent_step_id VARCHAR, \n\tlabel VARCHAR NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tmessage VARCHAR NOT NULL, \n\t\"order\" INTEGER NOT NULL, \n\tstarted_at DATETIME, \n\tfinished_at DATETIME, \n\terror_code VARCHAR, \n\terror_message VARCHAR, \n\tmetadata_json VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (step_id), \n\tCONSTRAINT ck_runsteprecord_kind CHECK (kind IN ('context', 'model', 'save', 'approval', 'tool'))\n)\n\n",
    "\nCREATE TABLE session_knowledge_bindings (\n\tid INTEGER NOT NULL, \n\tsession_id VARCHAR NOT NULL, \n\tknowledge_base_id VARCHAR NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tsort_order INTEGER NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (session_id, knowledge_base_id)\n)\n\n",
    "\nCREATE TABLE session_worldbook_bindings (\n\tid VARCHAR NOT NULL, \n\tsession_id VARCHAR NOT NULL, \n\tworldbook_id VARCHAR NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tsort_order INTEGER NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (session_id, worldbook_id)\n)\n\n",
    "\nCREATE TABLE sessionrecord (\n\tsession_id VARCHAR NOT NULL, \n\ttitle VARCHAR NOT NULL, \n\tcontext_mode VARCHAR NOT NULL, \n\twaiting_run_id VARCHAR, \n\tllm_profile_id VARCHAR, \n\tlast_announced_llm_profile_id VARCHAR, \n\ttitle_generation_state VARCHAR NOT NULL, \n\ttitle_generation_metadata_json VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (session_id)\n)\n\n",
    "\nCREATE TABLE vision_model_profiles (\n\tid VARCHAR NOT NULL, \n\talias VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tdescription VARCHAR NOT NULL, \n\tnotes VARCHAR NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\texternal_inference_enabled BOOLEAN NOT NULL, \n\tprovider_profile_id VARCHAR, \n\tprovider_model_id VARCHAR NOT NULL, \n\tarchitecture VARCHAR NOT NULL, \n\tbackend VARCHAR NOT NULL, \n\tsupported_tasks_json VARCHAR NOT NULL, \n\tmax_batch_size INTEGER, \n\tmetadata_json VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE worldbook_entries (\n\tid VARCHAR NOT NULL, \n\tworldbook_id VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tkeywords_text VARCHAR NOT NULL, \n\tcontent VARCHAR NOT NULL, \n\tactivation_mode VARCHAR NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tsort_order INTEGER NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE worldbook_settings (\n\tid INTEGER NOT NULL, \n\tworldbook_enabled BOOLEAN NOT NULL, \n\tworldbook_max_entries_per_call INTEGER NOT NULL, \n\tworldbook_max_context_chars INTEGER NOT NULL, \n\tworldbook_regex_case_insensitive BOOLEAN NOT NULL, \n\tworldbook_recursion_depth INTEGER NOT NULL, \n\tworldbook_case_sensitive BOOLEAN NOT NULL, \n\tworldbook_whole_words BOOLEAN NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE worldbooks (\n\tid VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tdescription VARCHAR NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "CREATE UNIQUE INDEX ix_embedding_model_profiles_alias ON embedding_model_profiles (alias)",
    "CREATE INDEX ix_embedding_model_profiles_provider_profile_id ON embedding_model_profiles (provider_profile_id)",
    "CREATE INDEX ix_kb_chunks_content_hash ON kb_chunks (content_hash)",
    "CREATE INDEX ix_kb_chunks_knowledge_base_id ON kb_chunks (knowledge_base_id)",
    "CREATE INDEX ix_kb_chunks_source_id ON kb_chunks (source_id)",
    "CREATE INDEX ix_kb_embeddings_chunk_id ON kb_embeddings (chunk_id)",
    "CREATE INDEX ix_kb_embeddings_embedding_model_profile_id ON kb_embeddings (embedding_model_profile_id)",
    "CREATE INDEX ix_kb_embeddings_knowledge_base_id ON kb_embeddings (knowledge_base_id)",
    "CREATE INDEX ix_kb_embeddings_source_id ON kb_embeddings (source_id)",
    "CREATE INDEX ix_kb_sources_content_hash ON kb_sources (content_hash)",
    "CREATE INDEX ix_kb_sources_file_status ON kb_sources (file_status)",
    "CREATE INDEX ix_kb_sources_knowledge_base_id ON kb_sources (knowledge_base_id)",
    "CREATE INDEX ix_kb_sources_source_type ON kb_sources (source_type)",
    "CREATE INDEX ix_kb_sources_status ON kb_sources (status)",
    "CREATE INDEX ix_knowledge_bases_embedding_model_profile_id ON knowledge_bases (embedding_model_profile_id)",
    "CREATE INDEX ix_llm_profiles_alias ON llm_profiles (alias)",
    "CREATE INDEX ix_llm_profiles_provider_profile_id ON llm_profiles (provider_profile_id)",
    "CREATE INDEX ix_messagerecord_session_id ON messagerecord (session_id)",
    "CREATE UNIQUE INDEX ix_multimodal_embedding_model_profiles_alias ON multimodal_embedding_model_profiles (alias)",
    "CREATE INDEX ix_multimodal_embedding_model_profiles_provider_profile_id ON multimodal_embedding_model_profiles (provider_profile_id)",
    "CREATE INDEX ix_runeventrecord_run_id ON runeventrecord (run_id)",
    "CREATE INDEX ix_runeventrecord_session_id ON runeventrecord (session_id)",
    "CREATE INDEX ix_runrecord_session_id ON runrecord (session_id)",
    "CREATE INDEX ix_runsteprecord_order ON runsteprecord (\"order\")",
    "CREATE INDEX ix_runsteprecord_parent_step_id ON runsteprecord (parent_step_id)",
    "CREATE INDEX ix_runsteprecord_run_id ON runsteprecord (run_id)",
    "CREATE INDEX ix_session_knowledge_bindings_knowledge_base_id ON session_knowledge_bindings (knowledge_base_id)",
    "CREATE INDEX ix_session_knowledge_bindings_session_id ON session_knowledge_bindings (session_id)",
    "CREATE INDEX ix_session_knowledge_bindings_sort_order ON session_knowledge_bindings (sort_order)",
    "CREATE INDEX ix_session_worldbook_bindings_session_id ON session_worldbook_bindings (session_id)",
    "CREATE INDEX ix_session_worldbook_bindings_sort_order ON session_worldbook_bindings (sort_order)",
    "CREATE INDEX ix_session_worldbook_bindings_worldbook_id ON session_worldbook_bindings (worldbook_id)",
    "CREATE UNIQUE INDEX ix_vision_model_profiles_alias ON vision_model_profiles (alias)",
    "CREATE INDEX ix_vision_model_profiles_provider_profile_id ON vision_model_profiles (provider_profile_id)",
    "CREATE INDEX ix_worldbook_entries_sort_order ON worldbook_entries (sort_order)",
    "CREATE INDEX ix_worldbook_entries_worldbook_id ON worldbook_entries (worldbook_id)",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(text("PRAGMA foreign_keys=OFF"))
    for table in DROP_TABLES:
        op.execute(text(f'DROP TABLE IF EXISTS "{table}"'))

    for statement in CREATE_STATEMENTS:
        op.execute(text(statement))
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
