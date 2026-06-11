from datetime import datetime
from typing import Optional

from sqlalchemy import Column, LargeBinary, UniqueConstraint
from sqlmodel import Field, SQLModel

from ai_workbench.core.time import utc_now


class SessionRecord(SQLModel, table=True):
    session_id: str = Field(primary_key=True)
    title: str = ""
    default_agent_id: str = "chat"
    context_mode: str = "single_assistant"
    waiting_run_id: Optional[str] = None
    llm_profile_id: Optional[str] = None
    last_announced_llm_profile_id: Optional[str] = None
    title_generation_state: str = "pending"
    title_generation_metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MessageRecord(SQLModel, table=True):
    message_id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    role: str
    speaker_type: Optional[str] = None
    speaker_id: Optional[str] = None
    speaker_name: Optional[str] = None
    origin: Optional[str] = None
    content_version: int = 2
    parts_json: str = "[]"
    agent_id: Optional[str] = None
    command_name: Optional[str] = None
    action_id: Optional[str] = None
    run_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    available_actions_json: str = "[]"
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)


class RunRecord(SQLModel, table=True):
    run_id: str = Field(primary_key=True)
    kind: str
    target_id: str
    action_id: Optional[str] = None
    session_id: str = Field(index=True)
    status: str
    current_step: str = ""
    stage: str = ""
    progress_message: str = ""
    progress_current: Optional[int] = None
    progress_total: Optional[int] = None
    cancel_requested: bool = False
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error: Optional[str] = None
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RunStepRecord(SQLModel, table=True):
    step_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    parent_step_id: Optional[str] = Field(default=None, index=True)
    label: str
    status: str
    message: str = ""
    order: int = Field(default=0, index=True)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RunEventRecord(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    session_id: str = Field(index=True)
    type: str
    message: str = ""
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)


class AgentConfigRecord(SQLModel, table=True):
    agent_id: str = Field(primary_key=True)
    enabled: bool = True
    display_json: str = "{}"
    runtime_json: str = "{}"
    user_config_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CapabilityConfigRecord(SQLModel, table=True):
    capability_id: str = Field(primary_key=True)
    enabled: bool = True
    user_config_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SessionAgentStateRecord(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("session_id", "agent_id", "key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    key: str = Field(index=True)
    value_json: str = "{}"
    updated_at: datetime = Field(default_factory=utc_now)


class LLMProfileRecord(SQLModel, table=True):
    __tablename__ = "llm_profiles"

    id: str = Field(primary_key=True)
    alias: str = Field(index=True)
    name: str
    provider_profile_id: Optional[str] = Field(default=None, index=True)
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model_id: str = ""
    enabled: bool = True
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None
    supports_vision: bool = False
    supports_tools: bool = False
    supports_reasoning: bool = False
    supports_streaming: bool = True
    supports_json_mode: bool = False
    external_inference_enabled: bool = False
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeSettingsRecord(SQLModel, table=True):
    __tablename__ = "knowledge_settings"

    id: int = Field(default=1, primary_key=True)
    models_root: str = "data/models"
    local_model_device: str = "auto"
    embedding_batch_size: int = 16
    embedding_timeout_seconds: int = 60
    unload_embedding_model_after_use: bool = False
    reranker_enabled: bool = False
    reranker_profile_id: Optional[str] = None
    reranker_model_path: Optional[str] = None
    reranker_batch_size: int = 16
    reranker_timeout_seconds: int = 60
    reranker_candidate_limit: int = 50
    unload_reranker_model_after_use: bool = False
    hybrid_search_enabled: bool = True
    default_vector_candidate_k: int = 20
    default_keyword_candidate_k: int = 20
    default_final_top_k: int = 6
    default_max_context_chars: int = 10000
    default_min_score: Optional[float] = None
    min_score_threshold: Optional[float] = None
    retrieval_max_chunks_per_source: Optional[int] = None
    retrieval_max_chunks_per_knowledge_base: Optional[int] = None
    query_expansion_enabled: bool = False
    query_expansion_max_variants: int = 3
    query_expansion_prompt: str = (
        "Generate up to {max_variants} short search query variants for the user's query.\n"
        "Use the same language when useful.\n"
        "Return only a JSON array of strings.\n\n"
        "User query:\n"
        "{query}"
    )
    rrf_k: int = 60
    default_chunk_size: int = 1000
    default_chunk_overlap: int = 150
    default_chunk_profile: Optional[str] = None
    max_source_size_bytes: int = 2097152
    max_chunks_per_source: int = 500
    max_total_index_chars_per_source: int = 200000
    knowledge_context_instruction: str = (
        "The following snippets were retrieved from active session knowledge bases.\n"
        "Use them only when relevant.\n"
        "If the snippets do not contain enough evidence, say so.\n"
        "Cite snippets as [K1], [K2]."
    )
    knowledge_context_snippet_template: str = (
        "[{index}]\n"
        "Knowledge base: {knowledge_base_name}\n"
        "Source: {source_title}\n"
        "Section: {heading_path}\n"
        "Content:\n"
        "{content}"
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorldbookSettingsRecord(SQLModel, table=True):
    __tablename__ = "worldbook_settings"

    id: int = Field(default=1, primary_key=True)
    worldbook_enabled_for_prompt_agents: bool = True
    worldbook_enabled_for_script_agents: bool = False
    worldbook_max_entries_per_call: int = 20
    worldbook_max_context_chars: int = 8000
    worldbook_regex_case_insensitive: bool = True
    worldbook_recursion_depth: int = 0
    worldbook_case_sensitive: bool = False
    worldbook_whole_words: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorldbookRecord(SQLModel, table=True):
    __tablename__ = "worldbooks"

    id: str = Field(primary_key=True)
    name: str
    description: str = ""
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorldbookEntryRecord(SQLModel, table=True):
    __tablename__ = "worldbook_entries"

    id: str = Field(primary_key=True)
    worldbook_id: str = Field(index=True)
    name: str
    keywords_text: str = ""
    content: str
    activation_mode: str = "keyword"
    enabled: bool = True
    sort_order: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SessionWorldbookBindingRecord(SQLModel, table=True):
    __tablename__ = "session_worldbook_bindings"
    __table_args__ = (UniqueConstraint("session_id", "worldbook_id"),)

    id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    worldbook_id: str = Field(index=True)
    enabled: bool = True
    sort_order: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class EmbeddingModelProfileRecord(SQLModel, table=True):
    __tablename__ = "embedding_model_profiles"

    id: str = Field(primary_key=True)
    name: str
    alias: str = Field(index=True, unique=True)
    model_path: str = ""
    provider_profile_id: Optional[str] = Field(default=None, index=True)
    provider_model_id: str = ""
    dimension: Optional[int] = None
    normalize: bool = True
    document_instruction: str = ""
    query_instruction: str = ""
    enabled: bool = True
    external_inference_enabled: bool = False
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RerankerModelProfileRecord(SQLModel, table=True):
    __tablename__ = "reranker_model_profiles"

    id: str = Field(primary_key=True)
    name: str
    alias: str = Field(index=True, unique=True)
    provider_profile_id: str = Field(index=True)
    provider_model_id: str = ""
    enabled: bool = True
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MultimodalEmbeddingModelProfileRecord(SQLModel, table=True):
    __tablename__ = "multimodal_embedding_model_profiles"

    id: str = Field(primary_key=True)
    name: str
    description: str = ""
    notes: str = ""
    enabled: bool = True
    external_inference_enabled: bool = False
    provider_profile_id: Optional[str] = Field(default=None, index=True)
    provider_model_id: str = ""
    architecture: str
    backend: str = "auto"
    embedding_space: Optional[str] = None
    dimensions: Optional[int] = None
    normalize_default: bool = True
    supported_input_types_json: str = '["image", "text"]'
    preprocessing_signature: Optional[str] = None
    pooling_strategy: str = "model_default"
    max_batch_size: Optional[int] = None
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class VisionModelProfileRecord(SQLModel, table=True):
    __tablename__ = "vision_model_profiles"

    id: str = Field(primary_key=True)
    name: str
    description: str = ""
    notes: str = ""
    enabled: bool = True
    external_inference_enabled: bool = False
    provider_profile_id: Optional[str] = Field(default=None, index=True)
    provider_model_id: str = ""
    architecture: str = "florence2"
    backend: str = "transformers"
    supported_tasks_json: str = '["caption", "detailed_caption", "ocr", "object_detection"]'
    max_batch_size: Optional[int] = 1
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeBaseRecord(SQLModel, table=True):
    __tablename__ = "knowledge_bases"

    id: str = Field(primary_key=True)
    name: str
    description: str = ""
    aliases_text: str = ""
    embedding_model_profile_id: str = Field(index=True)
    enabled: bool = True
    index_status: str = "empty"
    index_error: Optional[str] = None
    chunk_size_override: Optional[int] = None
    chunk_overlap_override: Optional[int] = None
    vector_candidate_k_override: Optional[int] = None
    keyword_candidate_k_override: Optional[int] = None
    final_top_k_override: Optional[int] = None
    max_context_chars_override: Optional[int] = None
    default_chunk_profile: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeOriginRecord(SQLModel, table=True):
    __tablename__ = "kb_origins"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "slug"),)

    id: str = Field(primary_key=True)
    knowledge_base_id: str = Field(index=True)
    name: str
    slug: str = Field(index=True)
    root_path: str
    include_globs: str = "**/*"
    exclude_globs: str = ""
    default_chunk_profile: Optional[str] = None
    last_scan_at: Optional[datetime] = None
    last_import_at: Optional[datetime] = None
    status: str = Field(default="ready", index=True)
    error: Optional[str] = None
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SessionKnowledgeBindingRecord(SQLModel, table=True):
    __tablename__ = "session_knowledge_bindings"
    __table_args__ = (UniqueConstraint("session_id", "knowledge_base_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    knowledge_base_id: str = Field(index=True)
    enabled: bool = True
    sort_order: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeSourceRecord(SQLModel, table=True):
    __tablename__ = "kb_sources"

    id: str = Field(primary_key=True)
    knowledge_base_id: str = Field(index=True)
    origin_id: Optional[str] = Field(default=None, index=True)
    source_type: str = Field(index=True)
    uri: str = ""
    title: str = ""
    relative_path: str = ""
    virtual_path: str = ""
    folder_path: str = ""
    file_name: str = ""
    extension: str = ""
    path_depth: int = 0
    file_status: str = Field(default="ready", index=True)
    source_mtime: Optional[datetime] = None
    source_size_bytes: int = 0
    mime_type: Optional[str] = None
    size_bytes: int = 0
    content_hash: str = Field(index=True)
    indexed_at: Optional[datetime] = None
    status: str = Field(default="pending", index=True)
    error: Optional[str] = None
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeChunkRecord(SQLModel, table=True):
    __tablename__ = "kb_chunks"
    __table_args__ = (UniqueConstraint("source_id", "chunk_index"),)

    id: str = Field(primary_key=True)
    knowledge_base_id: str = Field(index=True)
    source_id: str = Field(index=True)
    chunk_index: int
    heading_path: str = ""
    content: str
    char_start: int
    char_end: int
    token_count: Optional[int] = None
    content_hash: str = Field(index=True)
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeEmbeddingRecord(SQLModel, table=True):
    __tablename__ = "kb_embeddings"

    id: str = Field(primary_key=True)
    knowledge_base_id: str = Field(index=True)
    source_id: str = Field(index=True)
    chunk_id: str = Field(index=True)
    embedding_model_profile_id: str = Field(index=True)
    embedding_model_id_snapshot: str
    embedding_dimension: int
    embedding_normalize_snapshot: bool = True
    vector_blob: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)


class ProviderProfileRecord(SQLModel, table=True):
    __tablename__ = "llm_provider_profiles"

    id: str = Field(primary_key=True)
    name: str
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: Optional[int] = 60
    enabled: bool = True
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AppMetadataRecord(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=utc_now)
