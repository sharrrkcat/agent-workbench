"""Knowledge and Worldbook HTTP results and diagnostics."""

from typing import Literal

from pydantic import Field

from ai_workbench.api.schemas.common import ApiModel, JsonObject, patch_model, public_model
from ai_workbench.core.knowledge_store import KnowledgeBase, KnowledgeBaseCreate, KnowledgeSource, KnowledgeSourceIndexResult
from ai_workbench.core.worldbook import Worldbook, WorldbookCreate, WorldbookEntry, WorldbookSettings


KnowledgeBaseResponse = public_model("KnowledgeBaseResponse", KnowledgeBase)
KnowledgeSourceResponse = public_model("KnowledgeSourceResponse", KnowledgeSource, fields={
    "metadata": (JsonObject, Field(description="Source provenance and attachment references stored by the source workflow.")),
})
SourceIndexResult = public_model("SourceIndexResult", KnowledgeSourceIndexResult)
WorldbookResponse = public_model("WorldbookResponse", Worldbook)
WorldbookEntryResponse = public_model("WorldbookEntryResponse", WorldbookEntry)
WorldbookSettingsResponse = public_model("WorldbookSettingsResponse", WorldbookSettings)
KnowledgeBaseRequest = patch_model("KnowledgeBaseRequest", KnowledgeBaseCreate, fields={
    "aliases_text": (str | None, Field(default_factory=lambda: None, description="An empty string or null clears aliases.")),
})
WorldbookRequest = patch_model("WorldbookRequest", WorldbookCreate, fields={
    "description": (str | None, Field(default_factory=lambda: None, description="An empty string or null clears the description.")),
})
WorldbookEntryRequest = patch_model("WorldbookEntryRequest", WorldbookEntry,
    omit={"id", "worldbook_id", "created_at", "updated_at"})


class KnowledgeBaseDeleted(ApiModel):
    deleted: bool
    knowledge_base_id: str


class KnowledgeSourceDeleted(ApiModel):
    deleted: bool
    source_id: str


class SourceIndexFailure(ApiModel):
    source_id: str
    status: Literal["failed"]
    chunks: int
    error: str


class BaseIndexResult(ApiModel):
    knowledge_base_id: str
    sources: list[SourceIndexResult | SourceIndexFailure]


class SourcePreview(ApiModel):
    source_id: str
    title: str
    uri: str
    content: str
    truncated: bool


class ChunkContent(ApiModel):
    chunk_id: str
    chunk_index: int
    heading_path: str
    char_start: int | None
    char_end: int | None
    content: str
    metadata: JsonObject = Field(description="Chunk location and source metadata; embeddings are not included.")


class ChunkResponse(ChunkContent):
    knowledge_base_id: str
    source_id: str
    source_title: str


class ChunkPreview(ChunkContent):
    content_preview: str
    truncated: bool
    embedding_dimension: int | None = None


class SourceChunks(ApiModel):
    source_id: str
    chunks: list[ChunkPreview]


class RetrievalResult(ApiModel):
    chunk_id: str
    knowledge_base_id: str
    source_id: str
    title: str
    heading_path: str
    content: str
    truncated: bool
    vector_score: float | None
    vector_rank: int | None
    keyword_score: float | None
    keyword_rank: int | None
    rrf_score: float
    rerank_score: float | None


class RetrievalMetadata(ApiModel):
    rerank_fallback: bool
    reranker_used: bool
    reranker_enabled: bool


class RetrievalDebug(RetrievalMetadata):
    warnings: list[str]
    merged_candidate_count: int
    reranker_failed: bool


class KnowledgeSearchResponse(ApiModel):
    query: str
    results: list[RetrievalResult]
    metadata: RetrievalMetadata
    context_preview: str
    debug: RetrievalDebug | None = None


class WorldbookDeleted(ApiModel):
    deleted: bool
    worldbook_id: str


class WorldbookEntryDeleted(ApiModel):
    deleted: bool
    entry_id: str


class WorldbookReordered(ApiModel):
    worldbook_id: str
    entries: list[WorldbookEntryResponse]


class WorldbookWarning(ApiModel):
    code: str
    message: str
    entry_id: str | None = None
    worldbook_id: str | None = None
    pattern: str | None = None


class WorldbookMatch(ApiModel):
    worldbook_id: str
    worldbook_name: str
    entry_id: str
    entry_name: str
    activation_mode: Literal["always", "keyword"]
    matched_keywords: list[str]
    matched_by_recursion: bool
    recursion_depth: int
    sort_order: int
    content_preview: str


class WorldbookMatchResponse(ApiModel):
    matched_count: int
    included_count: int
    truncated: bool
    recursion_depth: int
    recursion_rounds_used: int
    case_sensitive: bool
    whole_words: bool
    warnings: list[WorldbookWarning]
    results: list[WorldbookMatch]
