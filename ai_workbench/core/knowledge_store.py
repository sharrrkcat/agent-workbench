"""Knowledge domain models and an in-memory knowledge store."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from ai_workbench.core.knowledge_settings import KnowledgeSettings, KnowledgeSettingsPatch, knowledge_settings_patch_updates
from ai_workbench.core.time import utc_now


def validate_alias(value: str) -> str:
    import re
    alias = str(value or "").strip().lower()
    if not alias or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", alias):
        raise ValueError("Alias must use lowercase letters, numbers, underscores, and hyphens.")
    return alias


def normalize_aliases_text(value: Any) -> str:
    seen: set[str] = set(); result: list[str] = []
    for raw in str(value or "").split(","):
        item = raw.strip()[:120]
        if item and item.casefold() not in seen:
            seen.add(item.casefold()); result.append(item)
    return ", ".join(result[:50])


class EmbeddingModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    alias: str
    model_path: str = ""
    provider_profile_id: str | None = None
    provider_model_id: str = ""
    dimension: int | None = Field(default=None, ge=1)
    normalize: StrictBool = True
    document_instruction: str = ""
    query_instruction: str = ""
    enabled: StrictBool = True
    external_inference_enabled: StrictBool = False
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("name")
    @classmethod
    def non_empty_name(cls, value: str) -> str:
        if not str(value).strip(): raise ValueError("Name must not be empty.")
        return str(value).strip()
    @field_validator("alias")
    @classmethod
    def valid_alias(cls, value: str) -> str: return validate_alias(value)


class EmbeddingModelProfileCreate(EmbeddingModelProfile):
    id: str = Field(default_factory=lambda: str(uuid4()))


class EmbeddingModelProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    alias: str | None = None
    model_path: str | None = None
    provider_profile_id: str | None = None
    provider_model_id: str | None = None
    dimension: int | None = Field(default=None, ge=1)
    normalize: bool | None = None
    document_instruction: str | None = None
    query_instruction: str | None = None
    enabled: bool | None = None
    external_inference_enabled: bool | None = None
    notes: str | None = None


KnowledgeIndexStatus = Literal["empty", "ready", "indexing", "failed", "needs_reindex"]
KnowledgeSourceStatus = Literal["pending", "indexing", "indexed", "needs_reindex", "failed", "deleted"]
KnowledgeSourceType = Literal["pasted_text", "attachment_text", "file"]


class KnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    aliases_text: str = ""
    embedding_model_profile_id: str
    enabled: StrictBool = True
    index_status: KnowledgeIndexStatus = "empty"
    index_error: str | None = None
    vector_candidate_k_override: int | None = Field(default=None, ge=1, le=1000)
    keyword_candidate_k_override: int | None = Field(default=None, ge=1, le=1000)
    final_top_k_override: int | None = Field(default=None, ge=1, le=100)
    max_context_chars_override: int | None = Field(default=None, ge=100, le=200000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not str(value).strip(): raise ValueError("Name must not be empty.")
        return str(value).strip()
    @field_validator("aliases_text", mode="before")
    @classmethod
    def aliases(cls, value: Any) -> str: return normalize_aliases_text(value)


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    aliases_text: str = ""
    embedding_model_profile_id: str
    enabled: bool = True
    vector_candidate_k_override: int | None = Field(default=None, ge=1, le=1000)
    keyword_candidate_k_override: int | None = Field(default=None, ge=1, le=1000)
    final_top_k_override: int | None = Field(default=None, ge=1, le=100)
    max_context_chars_override: int | None = Field(default=None, ge=100, le=200000)


class KnowledgeBasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    aliases_text: str | None = None
    embedding_model_profile_id: str | None = None
    enabled: bool | None = None
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
    sort_order: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    knowledge_base: KnowledgeBase | None = None


class KnowledgeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: str(uuid4()))
    knowledge_base_id: str
    source_type: KnowledgeSourceType
    uri: str = ""
    title: str
    relative_path: str = ""
    virtual_path: str = ""
    folder_path: str = ""
    file_name: str = ""
    extension: str = ""
    path_depth: int = 0
    file_status: str = "ready"
    source_mtime: datetime | None = None
    source_size_bytes: int = 0
    mime_type: str | None = None
    size_bytes: int = 0
    content_hash: str
    indexed_at: datetime | None = None
    status: KnowledgeSourceStatus = "pending"
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunks: int = 0
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
    """Structural interface implemented by memory and SQL stores."""
    pass


class MemoryKnowledgeStore(KnowledgeStore):
    def __init__(self) -> None:
        self._settings = KnowledgeSettings()
        self._embedding_profiles: dict[str, EmbeddingModelProfile] = {}
        self._bases: dict[str, KnowledgeBase] = {}
        self._bindings: dict[tuple[str, str], SessionKnowledgeBinding] = {}
        self._sources: dict[str, KnowledgeSource] = {}
        self._chunks: dict[str, list[Any]] = {}
        self._vectors: dict[str, list[list[float]]] = {}
        self._search_texts: dict[str, list[str]] = {}

    def get_settings(self) -> KnowledgeSettings: return self._settings
    def patch_settings(self, values: dict[str, Any]) -> KnowledgeSettings:
        patch = KnowledgeSettingsPatch.model_validate(values)
        self._settings = KnowledgeSettings.model_validate({**self._settings.model_dump(), **knowledge_settings_patch_updates(patch)})
        return self._settings
    def list_embedding_profiles(self) -> list[EmbeddingModelProfile]: return sorted(self._embedding_profiles.values(), key=lambda item: item.alias)
    def create_embedding_profile(self, profile: EmbeddingModelProfile) -> EmbeddingModelProfile:
        if any(item.alias == profile.alias for item in self._embedding_profiles.values()): raise ValueError("KNOWLEDGE_EMBEDDING_ALIAS_EXISTS")
        self._embedding_profiles[profile.id] = profile; return profile
    def get_embedding_profile(self, profile_id: str) -> EmbeddingModelProfile:
        if profile_id not in self._embedding_profiles: raise KeyError(f"unknown embedding model profile: {profile_id}")
        return self._embedding_profiles[profile_id]
    def find_embedding_profile_by_alias(self, alias: str) -> EmbeddingModelProfile | None: return next((item for item in self._embedding_profiles.values() if item.alias == alias), None)
    def get_embedding_profile_by_id_or_alias(self, value: str) -> EmbeddingModelProfile:
        try: return self.get_embedding_profile(value)
        except KeyError:
            item=self.find_embedding_profile_by_alias(value)
            if item is None: raise KeyError(f"unknown embedding model profile: {value}")
            return item
    def update_embedding_profile(self, profile_id: str, values: dict[str, Any]) -> EmbeddingModelProfile:
        current=self.get_embedding_profile(profile_id); updated=EmbeddingModelProfile.model_validate({**current.model_dump(),**values,"updated_at":utc_now()}); self._embedding_profiles[profile_id]=updated; return updated
    def delete_embedding_profile(self, profile_id: str) -> EmbeddingModelProfile:
        current=self.get_embedding_profile(profile_id)
        if any(item.embedding_model_profile_id == profile_id for item in self._bases.values()): raise ValueError("KNOWLEDGE_EMBEDDING_MODEL_IN_USE")
        del self._embedding_profiles[profile_id]; return current
    def list_knowledge_bases(self) -> list[KnowledgeBase]: return sorted(self._bases.values(), key=lambda item: item.name.casefold())
    def create_knowledge_base(self, knowledge_base: KnowledgeBase) -> KnowledgeBase: self._bases[knowledge_base.id]=knowledge_base; return knowledge_base
    def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        if knowledge_base_id not in self._bases: raise KeyError(f"unknown knowledge base: {knowledge_base_id}")
        return self._bases[knowledge_base_id]
    def update_knowledge_base(self, knowledge_base_id: str, values: dict[str, Any]) -> KnowledgeBase:
        current=self.get_knowledge_base(knowledge_base_id); updated=KnowledgeBase.model_validate({**current.model_dump(),**values,"updated_at":utc_now()}); self._bases[knowledge_base_id]=updated; return updated
    def delete_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        current=self.get_knowledge_base(knowledge_base_id); del self._bases[knowledge_base_id]
        for key in list(self._bindings):
            if key[1] == knowledge_base_id: del self._bindings[key]
        for source_id, source in list(self._sources.items()):
            if source.knowledge_base_id == knowledge_base_id: self._sources.pop(source_id); self._chunks.pop(source_id, None); self._vectors.pop(source_id, None); self._search_texts.pop(source_id, None)
        return current
    def list_session_bindings(self, session_id: str) -> list[SessionKnowledgeBinding]:
        result=[]
        for binding in sorted((item for (sid,_),item in self._bindings.items() if sid==session_id), key=lambda item:item.sort_order):
            result.append(binding.model_copy(update={"knowledge_base": self._bases.get(binding.knowledge_base_id)}))
        return result
    def replace_session_bindings(self, session_id: str, knowledge_base_ids: list[str]) -> list[SessionKnowledgeBinding]:
        for key in list(self._bindings):
            if key[0] == session_id: del self._bindings[key]
        for index,kb_id in enumerate(dict.fromkeys(knowledge_base_ids)):
            self.get_knowledge_base(kb_id); binding=SessionKnowledgeBinding(session_id=session_id,knowledge_base_id=kb_id,sort_order=(index+1)*10); self._bindings[(session_id,kb_id)] = binding
        return self.list_session_bindings(session_id)
    def delete_session_bindings(self, session_id: str) -> None:
        for key in list(self._bindings):
            if key[0] == session_id: del self._bindings[key]
    def list_sources(self, knowledge_base_id: str) -> list[KnowledgeSource]: return [item for item in self._sources.values() if item.knowledge_base_id==knowledge_base_id]
    def get_source(self, source_id: str) -> KnowledgeSource:
        if source_id not in self._sources: raise KeyError(f"unknown knowledge source: {source_id}")
        return self._sources[source_id]
    def upsert_indexed_source(self, *, source: KnowledgeSource, chunks: list[Any], vectors: list[list[float]], embedding_model_profile: EmbeddingModelProfile, embedding_dimension: int, search_texts: list[str]) -> KnowledgeSourceIndexResult:
        indexed=source.model_copy(update={"status":"indexed","chunks":len(chunks),"indexed_at":utc_now(),"error":None}); self._sources[source.id]=indexed; self._chunks[source.id]=list(chunks); self._vectors[source.id]=list(vectors); self._search_texts[source.id]=list(search_texts); return KnowledgeSourceIndexResult(source_id=source.id,status="indexed",chunks=len(chunks),embedding_model_profile_id=embedding_model_profile.id,embedding_dimension=embedding_dimension,indexed_at=indexed.indexed_at)
    def mark_source_failed(self, source: KnowledgeSource, error: str) -> KnowledgeSourceIndexResult:
        self._sources[source.id]=source.model_copy(update={"status":"failed","error":error}); return KnowledgeSourceIndexResult(source_id=source.id,status="failed",chunks=0,error=error)
    def delete_source(self, source_id: str) -> KnowledgeSource:
        current=self.get_source(source_id); del self._sources[source_id]; self._chunks.pop(source_id,None); self._vectors.pop(source_id,None); self._search_texts.pop(source_id,None); return current
    def source_text_reference(self, source_id: str) -> dict[str, Any]:
        source=self.get_source(source_id); return {"source_id":source.id,"uri":source.uri,"title":source.title}
    def list_chunks(self, source_id: str) -> list[Any]: return list(self._chunks.get(source_id, []))
