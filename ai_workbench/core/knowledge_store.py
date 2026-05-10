from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from ai_workbench.core.time import utc_now
from ai_workbench.core.knowledge_settings import KnowledgeSettings, KnowledgeSettingsPatch, knowledge_settings_patch_updates


ALIAS_PATTERN_DESCRIPTION = "lowercase letters, numbers, underscores, and hyphens only"


def validate_alias(value: str) -> str:
    import re

    alias = str(value or "").strip().lower()
    if not alias:
        raise ValueError("Alias must not be empty.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", alias):
        raise ValueError(f"Alias must use {ALIAS_PATTERN_DESCRIPTION}.")
    return alias


class EmbeddingModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    alias: str
    model_path: str
    dimension: int | None = Field(default=None, ge=1)
    normalize: StrictBool = True
    document_instruction: str = ""
    query_instruction: str = ""
    enabled: StrictBool = True
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Name must not be empty.")
        return text

    @field_validator("alias")
    @classmethod
    def _alias(cls, value: str) -> str:
        return validate_alias(value)

    @field_validator("document_instruction", "query_instruction", "notes", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value)


class EmbeddingModelProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    alias: str
    model_path: str
    dimension: int | None = Field(default=None, ge=1)
    normalize: StrictBool = True
    document_instruction: str = ""
    query_instruction: str = ""
    enabled: StrictBool = True
    notes: str = ""

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return EmbeddingModelProfile(name=value, alias="tmp", model_path="embeddings/tmp").name

    @field_validator("alias")
    @classmethod
    def _alias(cls, value: str) -> str:
        return validate_alias(value)


class EmbeddingModelProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    alias: str | None = None
    model_path: str | None = None
    dimension: int | None = Field(default=None, ge=1)
    normalize: StrictBool | None = None
    document_instruction: str | None = None
    query_instruction: str | None = None
    enabled: StrictBool | None = None
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("Name must not be empty.")
        return text

    @field_validator("alias")
    @classmethod
    def _alias(cls, value: str | None) -> str | None:
        return validate_alias(value) if value is not None else None


KnowledgeIndexStatus = Literal["empty", "ready", "indexing", "failed", "needs_reindex"]


class KnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    embedding_model_profile_id: str
    enabled: StrictBool = True
    index_status: KnowledgeIndexStatus = "empty"
    index_error: str | None = None
    chunk_size_override: int | None = Field(default=None, ge=100, le=10000)
    chunk_overlap_override: int | None = Field(default=None, ge=0, le=5000)
    vector_candidate_k_override: int | None = Field(default=None, ge=1, le=1000)
    keyword_candidate_k_override: int | None = Field(default=None, ge=1, le=1000)
    final_top_k_override: int | None = Field(default=None, ge=1, le=100)
    max_context_chars_override: int | None = Field(default=None, ge=100, le=200000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Name must not be empty.")
        return text


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    embedding_model_profile_id: str
    enabled: StrictBool = True
    chunk_size_override: int | None = Field(default=None, ge=100, le=10000)
    chunk_overlap_override: int | None = Field(default=None, ge=0, le=5000)
    vector_candidate_k_override: int | None = Field(default=None, ge=1, le=1000)
    keyword_candidate_k_override: int | None = Field(default=None, ge=1, le=1000)
    final_top_k_override: int | None = Field(default=None, ge=1, le=100)
    max_context_chars_override: int | None = Field(default=None, ge=100, le=200000)


class KnowledgeBasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    embedding_model_profile_id: str | None = None
    enabled: StrictBool | None = None
    chunk_size_override: int | None = Field(default=None, ge=100, le=10000)
    chunk_overlap_override: int | None = Field(default=None, ge=0, le=5000)
    vector_candidate_k_override: int | None = Field(default=None, ge=1, le=1000)
    keyword_candidate_k_override: int | None = Field(default=None, ge=1, le=1000)
    final_top_k_override: int | None = Field(default=None, ge=1, le=100)
    max_context_chars_override: int | None = Field(default=None, ge=100, le=200000)


class SessionKnowledgeBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    session_id: str
    knowledge_base_id: str
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    knowledge_base: KnowledgeBase | None = None


KnowledgeSourceStatus = Literal["pending", "indexing", "indexed", "needs_reindex", "failed", "deleted"]
KnowledgeSourceType = Literal["pasted_text", "attachment_text"]


class KnowledgeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    knowledge_base_id: str
    source_type: KnowledgeSourceType
    uri: str = ""
    title: str
    mime_type: str | None = None
    size_bytes: int = 0
    content_hash: str
    indexed_at: datetime | None = None
    status: KnowledgeSourceStatus = "pending"
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunks: int = 0
    embedding_model_profile_id: str | None = None
    embedding_dimension: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeSourceIndexResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    status: str
    chunks: int
    embedding_model_profile_id: str | None = None
    embedding_dimension: int | None = None
    indexed_at: datetime | None = None
    error: str | None = None
    skipped: bool = False


class KnowledgeStore:
    def get_settings(self) -> Any:
        raise NotImplementedError

    def patch_settings(self, values: dict[str, Any]) -> Any:
        raise NotImplementedError

    def list_embedding_profiles(self) -> list[EmbeddingModelProfile]:
        raise NotImplementedError

    def create_embedding_profile(self, profile: EmbeddingModelProfile) -> EmbeddingModelProfile:
        raise NotImplementedError

    def get_embedding_profile(self, profile_id: str) -> EmbeddingModelProfile:
        raise NotImplementedError

    def update_embedding_profile(self, profile_id: str, values: dict[str, Any]) -> EmbeddingModelProfile:
        raise NotImplementedError

    def delete_embedding_profile(self, profile_id: str) -> EmbeddingModelProfile:
        raise NotImplementedError

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        raise NotImplementedError

    def create_knowledge_base(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        raise NotImplementedError

    def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        raise NotImplementedError

    def update_knowledge_base(self, knowledge_base_id: str, values: dict[str, Any]) -> KnowledgeBase:
        raise NotImplementedError

    def delete_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        raise NotImplementedError

    def list_session_bindings(self, session_id: str) -> list[SessionKnowledgeBinding]:
        raise NotImplementedError

    def replace_session_bindings(self, session_id: str, knowledge_base_ids: list[str]) -> list[SessionKnowledgeBinding]:
        raise NotImplementedError

    def delete_session_bindings(self, session_id: str) -> None:
        raise NotImplementedError

    def list_sources(self, knowledge_base_id: str) -> list[KnowledgeSource]:
        raise NotImplementedError

    def get_source(self, source_id: str) -> KnowledgeSource:
        raise NotImplementedError

    def upsert_indexed_source(
        self,
        *,
        source: KnowledgeSource,
        chunks: list[Any],
        vectors: list[list[float]],
        embedding_model_profile: EmbeddingModelProfile,
        embedding_dimension: int,
        search_texts: list[str],
    ) -> KnowledgeSourceIndexResult:
        raise NotImplementedError

    def mark_source_failed(self, source: KnowledgeSource, error: str) -> KnowledgeSourceIndexResult:
        raise NotImplementedError

    def delete_source(self, source_id: str) -> KnowledgeSource:
        raise NotImplementedError

    def source_text_reference(self, source_id: str) -> dict[str, Any]:
        raise NotImplementedError


class MemoryKnowledgeStore(KnowledgeStore):
    def __init__(self) -> None:
        self._settings = KnowledgeSettings()
        self._embedding_profiles: dict[str, EmbeddingModelProfile] = {}
        self._knowledge_bases: dict[str, KnowledgeBase] = {}
        self._bindings: dict[tuple[str, str], SessionKnowledgeBinding] = {}
        self._next_binding_id = 1

    def get_settings(self) -> KnowledgeSettings:
        return self._settings

    def patch_settings(self, values: dict[str, Any]) -> KnowledgeSettings:
        patch = KnowledgeSettingsPatch.model_validate(values)
        updates = knowledge_settings_patch_updates(patch)
        changed_chunk_defaults = any(
            key in updates and getattr(self._settings, key) != updates[key]
            for key in ("default_chunk_size", "default_chunk_overlap")
        )
        self._settings = KnowledgeSettings.model_validate({**self._settings.model_dump(), **updates})
        if changed_chunk_defaults:
            self._mark_kbs_using_default_chunking_needs_reindex()
        return self._settings

    def list_embedding_profiles(self) -> list[EmbeddingModelProfile]:
        return sorted(self._embedding_profiles.values(), key=lambda item: (item.alias, item.created_at))

    def create_embedding_profile(self, profile: EmbeddingModelProfile) -> EmbeddingModelProfile:
        if any(item.alias == profile.alias for item in self._embedding_profiles.values()):
            raise ValueError("KNOWLEDGE_EMBEDDING_ALIAS_EXISTS")
        self._embedding_profiles[profile.id] = profile
        return profile

    def get_embedding_profile(self, profile_id: str) -> EmbeddingModelProfile:
        try:
            return self._embedding_profiles[profile_id]
        except KeyError as exc:
            raise KeyError(f"unknown embedding model profile: {profile_id}") from exc

    def update_embedding_profile(self, profile_id: str, values: dict[str, Any]) -> EmbeddingModelProfile:
        existing = self.get_embedding_profile(profile_id)
        if "alias" in values and any(item.alias == values["alias"] and item.id != existing.id for item in self._embedding_profiles.values()):
            raise ValueError("KNOWLEDGE_EMBEDDING_ALIAS_EXISTS")
        stale_keys = {"model_path", "dimension", "normalize", "document_instruction"}
        needs_reindex = any(key in values and getattr(existing, key) != values[key] for key in stale_keys)
        updated = EmbeddingModelProfile.model_validate(existing.model_copy(update={**values, "updated_at": utc_now()}).model_dump())
        self._embedding_profiles[existing.id] = updated
        if needs_reindex:
            self._mark_kbs_for_profile_needs_reindex(existing.id)
        return updated

    def delete_embedding_profile(self, profile_id: str) -> EmbeddingModelProfile:
        existing = self.get_embedding_profile(profile_id)
        if any(kb.embedding_model_profile_id == existing.id for kb in self._knowledge_bases.values()):
            raise ValueError("KNOWLEDGE_EMBEDDING_MODEL_IN_USE")
        del self._embedding_profiles[existing.id]
        return existing

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        return sorted(self._knowledge_bases.values(), key=lambda item: (item.name.lower(), item.created_at))

    def create_knowledge_base(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        self._knowledge_bases[knowledge_base.id] = knowledge_base
        return knowledge_base

    def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        try:
            return self._knowledge_bases[knowledge_base_id]
        except KeyError as exc:
            raise KeyError(f"unknown knowledge base: {knowledge_base_id}") from exc

    def update_knowledge_base(self, knowledge_base_id: str, values: dict[str, Any]) -> KnowledgeBase:
        existing = self.get_knowledge_base(knowledge_base_id)
        stale_keys = {"embedding_model_profile_id", "chunk_size_override", "chunk_overlap_override"}
        needs_reindex = any(key in values and getattr(existing, key) != values[key] for key in stale_keys)
        updated = KnowledgeBase.model_validate(existing.model_copy(update={**values, "updated_at": utc_now()}).model_dump())
        if needs_reindex and existing.index_status in {"ready", "needs_reindex", "failed"}:
            updated = updated.model_copy(update={"index_status": "needs_reindex", "index_error": None})
        self._knowledge_bases[existing.id] = updated
        return updated

    def _mark_kbs_for_profile_needs_reindex(self, profile_id: str) -> None:
        for kb in list(self._knowledge_bases.values()):
            if kb.embedding_model_profile_id == profile_id and kb.index_status in {"ready", "needs_reindex", "failed"}:
                self._knowledge_bases[kb.id] = kb.model_copy(update={"index_status": "needs_reindex", "index_error": None, "updated_at": utc_now()})

    def _mark_kbs_using_default_chunking_needs_reindex(self) -> None:
        for kb in list(self._knowledge_bases.values()):
            if kb.chunk_size_override is None and kb.chunk_overlap_override is None and kb.index_status in {"ready", "needs_reindex", "failed"}:
                self._knowledge_bases[kb.id] = kb.model_copy(update={"index_status": "needs_reindex", "index_error": None, "updated_at": utc_now()})

    def delete_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        existing = self.get_knowledge_base(knowledge_base_id)
        del self._knowledge_bases[existing.id]
        self._bindings = {key: value for key, value in self._bindings.items() if value.knowledge_base_id != existing.id}
        return existing

    def list_session_bindings(self, session_id: str) -> list[SessionKnowledgeBinding]:
        bindings = [binding for binding in self._bindings.values() if binding.session_id == session_id]
        return [binding.model_copy(update={"knowledge_base": self._knowledge_bases.get(binding.knowledge_base_id)}) for binding in bindings]

    def replace_session_bindings(self, session_id: str, knowledge_base_ids: list[str]) -> list[SessionKnowledgeBinding]:
        self.delete_session_bindings(session_id)
        seen: set[str] = set()
        for knowledge_base_id in knowledge_base_ids:
            if knowledge_base_id in seen:
                continue
            self.get_knowledge_base(knowledge_base_id)
            seen.add(knowledge_base_id)
            binding = SessionKnowledgeBinding(
                id=self._next_binding_id,
                session_id=session_id,
                knowledge_base_id=knowledge_base_id,
                enabled=True,
            )
            self._next_binding_id += 1
            self._bindings[(session_id, knowledge_base_id)] = binding
        return self.list_session_bindings(session_id)

    def delete_session_bindings(self, session_id: str) -> None:
        self._bindings = {key: value for key, value in self._bindings.items() if value.session_id != session_id}
