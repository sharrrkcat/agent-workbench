"""SQLModel persistence schema for the workbench."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Column, LargeBinary, UniqueConstraint, String
from sqlmodel import Field, SQLModel

from ai_workbench.core.time import utc_now


class SessionRecord(SQLModel, table=True):
    session_id: str = Field(primary_key=True)
    title: str = ""
    context_mode: str = "single_assistant"
    waiting_run_id: Optional[str] = None
    model_profile_id: Optional[str] = None
    current_persona_id: str = Field(foreign_key="personas.id")
    context_policy_json: Optional[str] = None
    generation_json: Optional[str] = None
    harness_enabled: Optional[bool] = None
    tools_allowed_json: Optional[str] = None
    knowledge_binding_mode: str = "inherit"
    worldbook_binding_mode: str = "inherit"
    title_generation_state: str = "pending"
    title_generation_metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PersonaRecord(SQLModel, table=True):
    __tablename__ = "personas"
    id: str = Field(primary_key=True)
    name: str
    avatar_attachment_id: Optional[str] = None
    system_prompt: str = ""
    model_profile_id: Optional[str] = Field(default=None, foreign_key="model_profiles.id", index=True)
    context_policy_json: str
    generation_json: str = "{}"
    harness_enabled: bool = False
    tools_allowed_json: str = "[]"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SessionPersonaRecord(SQLModel, table=True):
    __tablename__ = "session_personas"
    session_id: str = Field(primary_key=True, foreign_key="sessionrecord.session_id")
    persona_id: str = Field(primary_key=True, foreign_key="personas.id", index=True)
    sort_order: int = 0
    enabled: bool = True


class PersonaKnowledgeBindingRecord(SQLModel, table=True):
    __tablename__ = "persona_knowledge_bindings"
    persona_id: str = Field(primary_key=True, foreign_key="personas.id")
    knowledge_base_id: str = Field(primary_key=True, foreign_key="knowledge_bases.id", index=True)
    sort_order: int = 0


class PersonaWorldbookBindingRecord(SQLModel, table=True):
    __tablename__ = "persona_worldbook_bindings"
    persona_id: str = Field(primary_key=True, foreign_key="personas.id")
    worldbook_id: str = Field(primary_key=True, foreign_key="worldbooks.id", index=True)
    sort_order: int = 0


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
    run_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)


class RunRecord(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint("kind IN ('chat', 'tool')", name="ck_runrecord_kind"),
    )
    run_id: str = Field(primary_key=True)
    kind: str
    persona_id: str = Field(index=True)
    config_snapshot_json: str = "{}"
    harness_state_json: str = "{}"
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
    __table_args__ = (
        CheckConstraint(
            "kind IN ('context', 'model', 'save', 'approval', 'tool')",
            name="ck_runsteprecord_kind",
        ),
    )
    step_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    kind: str
    parent_step_id: Optional[str] = Field(default=None, index=True)
    label: str = ""
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


class ProviderProfileRecord(SQLModel, table=True):
    __tablename__ = "provider_profiles"
    id: str = Field(primary_key=True)
    name: str
    protocol: str = "openai_compatible"
    base_url: str
    api_key: str = ""
    timeout_seconds: float = 60
    concurrency: int = 1
    queue_size: int = 32
    queue_timeout_seconds: float = 30
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ModelProfileRecord(SQLModel, table=True):
    __tablename__ = "model_profiles"
    __table_args__ = (CheckConstraint("kind IN ('llm', 'embedding', 'reranker', 'image_embedding', 'vision')", name="ck_model_kind"),)
    id: str = Field(primary_key=True)
    alias: str = Field(index=True, unique=True)
    name: str
    kind: str = Field(index=True)
    provider_profile_id: Optional[str] = Field(default=None, foreign_key="provider_profiles.id", index=True)
    model_ref: str
    capabilities_json: str = "{}"
    parameters_json: str = "{}"
    lifecycle_json: str = "{}"
    enabled: bool = True
    external_enabled: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    runtime_id: Optional[str] = None
    runtime_variant: Optional[str] = None
    runtime_options_json: str = Field(default="{}", sa_column=Column(String, nullable=False, server_default="{}"))


class AppMetadataRecord(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=utc_now)


class RuntimeInstallationRecord(SQLModel, table=True):
    __tablename__ = "runtime_installations"
    id: str = Field(primary_key=True)
    runtime_id: str
    variant: str
    version: str
    state: str
    job_id: Optional[str] = None
    error_code: Optional[str] = None
    manifest_sha256: Optional[str] = None
    updated_at: datetime = Field(default_factory=utc_now)


class RuntimeJobRecord(SQLModel, table=True):
    __tablename__ = "runtime_jobs"
    id: str = Field(primary_key=True)
    runtime_id: str
    variant: str
    version: str
    operation: str
    state: str
    stage: str
    progress_current: int = 0
    progress_total: Optional[int] = None
    error_code: Optional[str] = None
    cancel_requested: bool = False
    log_path: str = ""
    revision: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: Optional[datetime] = None


class KnowledgeSettingsRecord(SQLModel, table=True):
    __tablename__ = "knowledge_settings"

    id: int = Field(default=1, primary_key=True)
    reranker_enabled: bool = False
    reranker_model_profile_id: Optional[str] = None
    reranker_candidate_limit: int = 50
    hybrid_search_enabled: bool = True
    default_vector_candidate_k: int = 20
    default_keyword_candidate_k: int = 20
    default_final_top_k: int = 6
    default_max_context_chars: int = 10000
    default_min_score: Optional[float] = None
    min_score_threshold: Optional[float] = None
    retrieval_max_chunks_per_source: Optional[int] = None
    retrieval_max_chunks_per_knowledge_base: Optional[int] = None
    rrf_k: int = 60
    default_chunk_size: int = 1000
    default_chunk_overlap: int = 150
    max_source_size_bytes: int = 2097152
    max_chunks_per_source: int = 500
    max_total_index_chars_per_source: int = 200000
    knowledge_context_instruction: str = "The following snippets were retrieved from active session knowledge bases.\nUse them only when relevant.\nIf the snippets do not contain enough evidence, say so.\nCite snippets as [K1], [K2]."
    knowledge_context_snippet_template: str = "[{index}]\nKnowledge base: {knowledge_base_name}\nSource: {source_title}\nSection: {heading_path}\nContent:\n{content}"
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
    vector_candidate_k_override: Optional[int] = None
    keyword_candidate_k_override: Optional[int] = None
    final_top_k_override: Optional[int] = None
    max_context_chars_override: Optional[int] = None
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


class WorldbookSettingsRecord(SQLModel, table=True):
    __tablename__ = "worldbook_settings"

    id: int = Field(default=1, primary_key=True)
    worldbook_enabled: bool = True
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
