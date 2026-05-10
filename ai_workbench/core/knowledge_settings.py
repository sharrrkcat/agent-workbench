from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

DEFAULT_KNOWLEDGE_CONTEXT_INSTRUCTION = """\
The following snippets were retrieved from active session knowledge bases.
Use them only when relevant.
If the snippets do not contain enough evidence, say so.
Cite snippets as [K1], [K2]."""

DEFAULT_KNOWLEDGE_CONTEXT_SNIPPET_TEMPLATE = """\
[{index}]
Knowledge base: {knowledge_base_name}
Source: {source_title}
Section: {heading_path}
Content:
{content}"""


class KnowledgeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = 1
    models_root: str = "data/models"
    local_model_device: Literal["auto", "cpu", "cuda"] = "auto"
    embedding_batch_size: int = Field(default=16, ge=1, le=1024)
    embedding_timeout_seconds: int = Field(default=60, ge=1, le=3600)
    reranker_enabled: StrictBool = False
    reranker_model_path: str | None = None
    reranker_batch_size: int = Field(default=16, ge=1, le=1024)
    reranker_timeout_seconds: int = Field(default=60, ge=1, le=3600)
    reranker_candidate_limit: int = Field(default=50, ge=1, le=1000)
    hybrid_search_enabled: StrictBool = True
    default_vector_candidate_k: int = Field(default=20, ge=1, le=1000)
    default_keyword_candidate_k: int = Field(default=20, ge=1, le=1000)
    default_final_top_k: int = Field(default=6, ge=1, le=100)
    default_max_context_chars: int = Field(default=10000, ge=100, le=200000)
    default_min_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    default_chunk_size: int = Field(default=1000, ge=100, le=10000)
    default_chunk_overlap: int = Field(default=150, ge=0, le=5000)
    max_source_size_bytes: int = Field(default=2097152, ge=1024, le=104857600)
    max_chunks_per_source: int = Field(default=500, ge=1, le=100000)
    max_total_index_chars_per_source: int = Field(default=200000, ge=1000, le=10000000)
    knowledge_context_instruction: str = DEFAULT_KNOWLEDGE_CONTEXT_INSTRUCTION
    knowledge_context_snippet_template: str = DEFAULT_KNOWLEDGE_CONTEXT_SNIPPET_TEMPLATE

    @field_validator("reranker_model_path", mode="before")
    @classmethod
    def _normalize_reranker_model_path(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("knowledge_context_instruction", "knowledge_context_snippet_template", mode="before")
    @classmethod
    def _non_empty_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Knowledge context prompt fields must not be empty.")
        return text

    @field_validator("knowledge_context_snippet_template")
    @classmethod
    def _template_contains_content(cls, value: str) -> str:
        if "{content}" not in value:
            raise ValueError("Knowledge context snippet template must include {content}.")
        return value


class KnowledgeSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_model_device: Literal["auto", "cpu", "cuda"] | None = None
    embedding_batch_size: int | None = Field(default=None, ge=1, le=1024)
    embedding_timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    reranker_enabled: StrictBool | None = None
    reranker_model_path: str | None = None
    reranker_batch_size: int | None = Field(default=None, ge=1, le=1024)
    reranker_timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    reranker_candidate_limit: int | None = Field(default=None, ge=1, le=1000)
    hybrid_search_enabled: StrictBool | None = None
    default_vector_candidate_k: int | None = Field(default=None, ge=1, le=1000)
    default_keyword_candidate_k: int | None = Field(default=None, ge=1, le=1000)
    default_final_top_k: int | None = Field(default=None, ge=1, le=100)
    default_max_context_chars: int | None = Field(default=None, ge=100, le=200000)
    default_min_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    rrf_k: int | None = Field(default=None, ge=1, le=1000)
    default_chunk_size: int | None = Field(default=None, ge=100, le=10000)
    default_chunk_overlap: int | None = Field(default=None, ge=0, le=5000)
    max_source_size_bytes: int | None = Field(default=None, ge=1024, le=104857600)
    max_chunks_per_source: int | None = Field(default=None, ge=1, le=100000)
    max_total_index_chars_per_source: int | None = Field(default=None, ge=1000, le=10000000)
    knowledge_context_instruction: str | None = None
    knowledge_context_snippet_template: str | None = None

    @field_validator("reranker_model_path", mode="before")
    @classmethod
    def _normalize_reranker_model_path(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("knowledge_context_instruction", "knowledge_context_snippet_template", mode="before")
    @classmethod
    def _non_empty_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("Knowledge context prompt fields must not be empty.")
        return text

    @field_validator("knowledge_context_snippet_template")
    @classmethod
    def _template_contains_content(cls, value: str | None) -> str | None:
        if value is not None and "{content}" not in value:
            raise ValueError("Knowledge context snippet template must include {content}.")
        return value


def knowledge_settings_patch_updates(patch: KnowledgeSettingsPatch) -> dict[str, Any]:
    updates = patch.model_dump(exclude_unset=True)
    if "reranker_model_path" in patch.model_fields_set and not patch.reranker_model_path:
        updates["reranker_model_path"] = None
    return updates
