"""Create the current SQLModel schema as a reproducible baseline.

This revision is deliberately self-contained.  It describes the schema that
was deployed at the start of Phase 0 instead of importing the application's
mutable SQLModel metadata.  ``content_json`` and ``output_type`` are retained
as historical columns on ``messagerecord`` so databases created from the
baseline remain readable by both generations of the message store.
"""

from __future__ import annotations

from alembic import op


revision = "0001_current_schema"
down_revision = None
branch_labels = None
depends_on = None


TABLES: tuple[str, ...] = (
    "agentconfigrecord",
    "appmetadatarecord",
    "capabilityconfigrecord",
    "embedding_model_profiles",
    "image_generation_model_profiles",
    "kb_chunks",
    "kb_embeddings",
    "kb_origins",
    "kb_sources",
    "knowledge_bases",
    "knowledge_settings",
    "llm_profiles",
    "llm_provider_profiles",
    "messagerecord",
    "multimodal_embedding_model_profiles",
    "reranker_model_profiles",
    "runeventrecord",
    "runrecord",
    "runsteprecord",
    "session_knowledge_bindings",
    "session_worldbook_bindings",
    "sessionagentstaterecord",
    "sessionrecord",
    "vision_model_profiles",
    "worldbook_entries",
    "worldbook_settings",
    "worldbooks",
)


TABLE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS agentconfigrecord (
      agent_id VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      display_json VARCHAR NOT NULL,
      runtime_json VARCHAR NOT NULL,
      user_config_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (agent_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS appmetadatarecord (
      "key" VARCHAR NOT NULL,
      value VARCHAR NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY ("key")
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS capabilityconfigrecord (
      capability_id VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      user_config_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (capability_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS embedding_model_profiles (
      id VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      alias VARCHAR NOT NULL,
      model_path VARCHAR NOT NULL,
      provider_profile_id VARCHAR,
      provider_model_id VARCHAR NOT NULL,
      dimension INTEGER,
      normalize BOOLEAN NOT NULL,
      document_instruction VARCHAR NOT NULL,
      query_instruction VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      external_inference_enabled BOOLEAN NOT NULL,
      notes VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS image_generation_model_profiles (
      id VARCHAR NOT NULL,
      alias VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      description VARCHAR NOT NULL,
      notes VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      architecture VARCHAR NOT NULL,
      variant VARCHAR NOT NULL,
      checkpoint_ref VARCHAR NOT NULL,
      vae_ref VARCHAR,
      dtype VARCHAR NOT NULL,
      device VARCHAR NOT NULL,
      clip_skip INTEGER,
      supported_tasks_json VARCHAR NOT NULL,
      metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kb_chunks (
      id VARCHAR NOT NULL,
      knowledge_base_id VARCHAR NOT NULL,
      source_id VARCHAR NOT NULL,
      chunk_index INTEGER NOT NULL,
      heading_path VARCHAR NOT NULL,
      content VARCHAR NOT NULL,
      char_start INTEGER NOT NULL,
      char_end INTEGER NOT NULL,
      token_count INTEGER,
      content_hash VARCHAR NOT NULL,
      metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      PRIMARY KEY (id),
      UNIQUE (source_id, chunk_index)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kb_embeddings (
      id VARCHAR NOT NULL,
      knowledge_base_id VARCHAR NOT NULL,
      source_id VARCHAR NOT NULL,
      chunk_id VARCHAR NOT NULL,
      embedding_model_profile_id VARCHAR NOT NULL,
      embedding_model_id_snapshot VARCHAR NOT NULL,
      embedding_dimension INTEGER NOT NULL,
      embedding_normalize_snapshot BOOLEAN NOT NULL,
      vector_blob BLOB NOT NULL,
      created_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kb_origins (
      id VARCHAR NOT NULL,
      knowledge_base_id VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      slug VARCHAR NOT NULL,
      root_path VARCHAR NOT NULL,
      include_globs VARCHAR NOT NULL,
      exclude_globs VARCHAR NOT NULL,
      default_chunk_profile VARCHAR,
      last_scan_at DATETIME,
      last_import_at DATETIME,
      status VARCHAR NOT NULL,
      error VARCHAR,
      metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id),
      UNIQUE (knowledge_base_id, slug)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kb_sources (
      id VARCHAR NOT NULL,
      knowledge_base_id VARCHAR NOT NULL,
      origin_id VARCHAR,
      source_type VARCHAR NOT NULL,
      uri VARCHAR NOT NULL,
      title VARCHAR NOT NULL,
      relative_path VARCHAR NOT NULL,
      virtual_path VARCHAR NOT NULL,
      folder_path VARCHAR NOT NULL,
      file_name VARCHAR NOT NULL,
      extension VARCHAR NOT NULL,
      path_depth INTEGER NOT NULL,
      file_status VARCHAR NOT NULL,
      source_mtime DATETIME,
      source_size_bytes INTEGER NOT NULL,
      mime_type VARCHAR,
      size_bytes INTEGER NOT NULL,
      content_hash VARCHAR NOT NULL,
      indexed_at DATETIME,
      status VARCHAR NOT NULL,
      error VARCHAR,
      metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_bases (
      id VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      description VARCHAR NOT NULL,
      aliases_text VARCHAR NOT NULL,
      embedding_model_profile_id VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      index_status VARCHAR NOT NULL,
      index_error VARCHAR,
      chunk_size_override INTEGER,
      chunk_overlap_override INTEGER,
      vector_candidate_k_override INTEGER,
      keyword_candidate_k_override INTEGER,
      final_top_k_override INTEGER,
      max_context_chars_override INTEGER,
      default_chunk_profile VARCHAR,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_settings (
      id INTEGER NOT NULL,
      models_root VARCHAR NOT NULL,
      local_model_device VARCHAR NOT NULL,
      embedding_batch_size INTEGER NOT NULL,
      embedding_timeout_seconds INTEGER NOT NULL,
      unload_embedding_model_after_use BOOLEAN NOT NULL,
      reranker_enabled BOOLEAN NOT NULL,
      reranker_profile_id VARCHAR,
      reranker_model_path VARCHAR,
      reranker_batch_size INTEGER NOT NULL,
      reranker_timeout_seconds INTEGER NOT NULL,
      reranker_candidate_limit INTEGER NOT NULL,
      unload_reranker_model_after_use BOOLEAN NOT NULL,
      hybrid_search_enabled BOOLEAN NOT NULL,
      default_vector_candidate_k INTEGER NOT NULL,
      default_keyword_candidate_k INTEGER NOT NULL,
      default_final_top_k INTEGER NOT NULL,
      default_max_context_chars INTEGER NOT NULL,
      default_min_score FLOAT,
      min_score_threshold FLOAT,
      retrieval_max_chunks_per_source INTEGER,
      retrieval_max_chunks_per_knowledge_base INTEGER,
      query_expansion_enabled BOOLEAN NOT NULL,
      query_expansion_max_variants INTEGER NOT NULL,
      query_expansion_prompt VARCHAR NOT NULL,
      rrf_k INTEGER NOT NULL,
      default_chunk_size INTEGER NOT NULL,
      default_chunk_overlap INTEGER NOT NULL,
      default_chunk_profile VARCHAR,
      max_source_size_bytes INTEGER NOT NULL,
      max_chunks_per_source INTEGER NOT NULL,
      max_total_index_chars_per_source INTEGER NOT NULL,
      knowledge_context_instruction VARCHAR NOT NULL,
      knowledge_context_snippet_template VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS llm_profiles (
      id VARCHAR NOT NULL,
      alias VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      provider_profile_id VARCHAR,
      provider VARCHAR NOT NULL,
      base_url VARCHAR NOT NULL,
      api_key VARCHAR NOT NULL,
      model_id VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      temperature FLOAT,
      top_p FLOAT,
      top_k INTEGER,
      max_tokens INTEGER,
      timeout INTEGER,
      supports_vision BOOLEAN NOT NULL,
      supports_tools BOOLEAN NOT NULL,
      supports_reasoning BOOLEAN NOT NULL,
      supports_streaming BOOLEAN NOT NULL,
      supports_json_mode BOOLEAN NOT NULL,
      external_inference_enabled BOOLEAN NOT NULL,
      notes VARCHAR,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS llm_provider_profiles (
      id VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      provider VARCHAR NOT NULL,
      base_url VARCHAR NOT NULL,
      api_key VARCHAR NOT NULL,
      timeout_seconds INTEGER,
      enabled BOOLEAN NOT NULL,
      metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messagerecord (
      message_id VARCHAR NOT NULL,
      session_id VARCHAR NOT NULL,
      role VARCHAR NOT NULL,
      content_json VARCHAR NOT NULL,
      output_type VARCHAR NOT NULL,
      speaker_type VARCHAR,
      speaker_id VARCHAR,
      speaker_name VARCHAR,
      origin VARCHAR,
      content_version INTEGER NOT NULL,
      parts_json VARCHAR NOT NULL,
      agent_id VARCHAR,
      command_name VARCHAR,
      action_id VARCHAR,
      run_id VARCHAR,
      parent_message_id VARCHAR,
      available_actions_json VARCHAR NOT NULL,
      metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      PRIMARY KEY (message_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS multimodal_embedding_model_profiles (
      id VARCHAR NOT NULL,
      alias VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      description VARCHAR NOT NULL,
      notes VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      external_inference_enabled BOOLEAN NOT NULL,
      provider_profile_id VARCHAR,
      provider_model_id VARCHAR NOT NULL,
      architecture VARCHAR NOT NULL,
      backend VARCHAR NOT NULL,
      embedding_space VARCHAR,
      dimensions INTEGER,
      normalize_default BOOLEAN NOT NULL,
      supported_input_types_json VARCHAR NOT NULL,
      preprocessing_signature VARCHAR,
      pooling_strategy VARCHAR NOT NULL,
      max_batch_size INTEGER,
      metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reranker_model_profiles (
      id VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      alias VARCHAR NOT NULL,
      provider_profile_id VARCHAR NOT NULL,
      provider_model_id VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      notes VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runeventrecord (
      event_id VARCHAR NOT NULL,
      run_id VARCHAR NOT NULL,
      session_id VARCHAR NOT NULL,
      type VARCHAR NOT NULL,
      message VARCHAR NOT NULL,
      payload_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      PRIMARY KEY (event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runrecord (
      run_id VARCHAR NOT NULL,
      kind VARCHAR NOT NULL,
      target_id VARCHAR NOT NULL,
      action_id VARCHAR,
      session_id VARCHAR NOT NULL,
      status VARCHAR NOT NULL,
      current_step VARCHAR NOT NULL,
      stage VARCHAR NOT NULL,
      progress_message VARCHAR NOT NULL,
      progress_current INTEGER,
      progress_total INTEGER,
      cancel_requested BOOLEAN NOT NULL,
      started_at DATETIME,
      finished_at DATETIME,
      error_code VARCHAR,
      error_message VARCHAR,
      error VARCHAR,
      metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runsteprecord (
      step_id VARCHAR NOT NULL,
      run_id VARCHAR NOT NULL,
      parent_step_id VARCHAR,
      label VARCHAR NOT NULL,
      status VARCHAR NOT NULL,
      message VARCHAR NOT NULL,
      "order" INTEGER NOT NULL,
      started_at DATETIME,
      finished_at DATETIME,
      error_code VARCHAR,
      error_message VARCHAR,
      metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (step_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_knowledge_bindings (
      id INTEGER NOT NULL,
      session_id VARCHAR NOT NULL,
      knowledge_base_id VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      sort_order INTEGER NOT NULL,
      created_at DATETIME NOT NULL,
      PRIMARY KEY (id),
      UNIQUE (session_id, knowledge_base_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_worldbook_bindings (
      id VARCHAR NOT NULL,
      session_id VARCHAR NOT NULL,
      worldbook_id VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      sort_order INTEGER NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id),
      UNIQUE (session_id, worldbook_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessionagentstaterecord (
      id INTEGER NOT NULL,
      session_id VARCHAR NOT NULL,
      agent_id VARCHAR NOT NULL,
      "key" VARCHAR NOT NULL,
      value_json VARCHAR NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id),
      UNIQUE (session_id, agent_id, "key")
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessionrecord (
      session_id VARCHAR NOT NULL,
      title VARCHAR NOT NULL,
      default_agent_id VARCHAR NOT NULL,
      context_mode VARCHAR NOT NULL,
      waiting_run_id VARCHAR,
      llm_profile_id VARCHAR,
      last_announced_llm_profile_id VARCHAR,
      title_generation_state VARCHAR NOT NULL,
      title_generation_metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (session_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vision_model_profiles (
      id VARCHAR NOT NULL,
      alias VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      description VARCHAR NOT NULL,
      notes VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      external_inference_enabled BOOLEAN NOT NULL,
      provider_profile_id VARCHAR,
      provider_model_id VARCHAR NOT NULL,
      architecture VARCHAR NOT NULL,
      backend VARCHAR NOT NULL,
      supported_tasks_json VARCHAR NOT NULL,
      max_batch_size INTEGER,
      metadata_json VARCHAR NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worldbook_entries (
      id VARCHAR NOT NULL,
      worldbook_id VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      keywords_text VARCHAR NOT NULL,
      content VARCHAR NOT NULL,
      activation_mode VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      sort_order INTEGER NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worldbook_settings (
      id INTEGER NOT NULL,
      worldbook_enabled_for_prompt_agents BOOLEAN NOT NULL,
      worldbook_enabled_for_script_agents BOOLEAN NOT NULL,
      worldbook_max_entries_per_call INTEGER NOT NULL,
      worldbook_max_context_chars INTEGER NOT NULL,
      worldbook_regex_case_insensitive BOOLEAN NOT NULL,
      worldbook_recursion_depth INTEGER NOT NULL,
      worldbook_case_sensitive BOOLEAN NOT NULL,
      worldbook_whole_words BOOLEAN NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worldbooks (
      id VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      description VARCHAR NOT NULL,
      enabled BOOLEAN NOT NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id)
    )
    """,
)


INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_embedding_model_profiles_alias ON embedding_model_profiles (alias)",
    "CREATE INDEX IF NOT EXISTS ix_embedding_model_profiles_provider_profile_id ON embedding_model_profiles (provider_profile_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_image_generation_model_profiles_alias ON image_generation_model_profiles (alias)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_content_hash ON kb_chunks (content_hash)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_knowledge_base_id ON kb_chunks (knowledge_base_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_source_id ON kb_chunks (source_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_embeddings_chunk_id ON kb_embeddings (chunk_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_embeddings_embedding_model_profile_id ON kb_embeddings (embedding_model_profile_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_embeddings_knowledge_base_id ON kb_embeddings (knowledge_base_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_embeddings_source_id ON kb_embeddings (source_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_origins_knowledge_base_id ON kb_origins (knowledge_base_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_origins_slug ON kb_origins (slug)",
    "CREATE INDEX IF NOT EXISTS ix_kb_origins_status ON kb_origins (status)",
    "CREATE INDEX IF NOT EXISTS ix_kb_sources_content_hash ON kb_sources (content_hash)",
    "CREATE INDEX IF NOT EXISTS ix_kb_sources_file_status ON kb_sources (file_status)",
    "CREATE INDEX IF NOT EXISTS ix_kb_sources_knowledge_base_id ON kb_sources (knowledge_base_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_sources_origin_id ON kb_sources (origin_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_sources_source_type ON kb_sources (source_type)",
    "CREATE INDEX IF NOT EXISTS ix_kb_sources_status ON kb_sources (status)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_bases_embedding_model_profile_id ON knowledge_bases (embedding_model_profile_id)",
    "CREATE INDEX IF NOT EXISTS ix_llm_profiles_alias ON llm_profiles (alias)",
    "CREATE INDEX IF NOT EXISTS ix_llm_profiles_provider_profile_id ON llm_profiles (provider_profile_id)",
    "CREATE INDEX IF NOT EXISTS ix_messagerecord_session_id ON messagerecord (session_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_multimodal_embedding_model_profiles_alias ON multimodal_embedding_model_profiles (alias)",
    "CREATE INDEX IF NOT EXISTS ix_multimodal_embedding_model_profiles_provider_profile_id ON multimodal_embedding_model_profiles (provider_profile_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_reranker_model_profiles_alias ON reranker_model_profiles (alias)",
    "CREATE INDEX IF NOT EXISTS ix_reranker_model_profiles_provider_profile_id ON reranker_model_profiles (provider_profile_id)",
    "CREATE INDEX IF NOT EXISTS ix_runeventrecord_run_id ON runeventrecord (run_id)",
    "CREATE INDEX IF NOT EXISTS ix_runeventrecord_session_id ON runeventrecord (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_runrecord_session_id ON runrecord (session_id)",
    'CREATE INDEX IF NOT EXISTS ix_runsteprecord_order ON runsteprecord ("order")',
    "CREATE INDEX IF NOT EXISTS ix_runsteprecord_parent_step_id ON runsteprecord (parent_step_id)",
    "CREATE INDEX IF NOT EXISTS ix_runsteprecord_run_id ON runsteprecord (run_id)",
    "CREATE INDEX IF NOT EXISTS ix_session_knowledge_bindings_knowledge_base_id ON session_knowledge_bindings (knowledge_base_id)",
    "CREATE INDEX IF NOT EXISTS ix_session_knowledge_bindings_session_id ON session_knowledge_bindings (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_session_knowledge_bindings_sort_order ON session_knowledge_bindings (sort_order)",
    "CREATE INDEX IF NOT EXISTS ix_session_worldbook_bindings_session_id ON session_worldbook_bindings (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_session_worldbook_bindings_sort_order ON session_worldbook_bindings (sort_order)",
    "CREATE INDEX IF NOT EXISTS ix_session_worldbook_bindings_worldbook_id ON session_worldbook_bindings (worldbook_id)",
    "CREATE INDEX IF NOT EXISTS ix_sessionagentstaterecord_agent_id ON sessionagentstaterecord (agent_id)",
    'CREATE INDEX IF NOT EXISTS ix_sessionagentstaterecord_key ON sessionagentstaterecord ("key")',
    "CREATE INDEX IF NOT EXISTS ix_sessionagentstaterecord_session_id ON sessionagentstaterecord (session_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_vision_model_profiles_alias ON vision_model_profiles (alias)",
    "CREATE INDEX IF NOT EXISTS ix_vision_model_profiles_provider_profile_id ON vision_model_profiles (provider_profile_id)",
    "CREATE INDEX IF NOT EXISTS ix_worldbook_entries_sort_order ON worldbook_entries (sort_order)",
    "CREATE INDEX IF NOT EXISTS ix_worldbook_entries_worldbook_id ON worldbook_entries (worldbook_id)",
)


def upgrade() -> None:
    for ddl in TABLE_DDL:
        op.execute(ddl)
    op.execute(
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
    for ddl in INDEX_DDL:
        op.execute(ddl)


def downgrade() -> None:
    # Downgrades are intended only for disposable test databases.  Production
    # rollback is restore-from-backup by policy.
    op.execute("DROP TABLE IF EXISTS kb_chunk_fts")
    for table in reversed(TABLES):
        op.execute(f'DROP TABLE IF EXISTS "{table}"')
