"""Explicit dependency assembly for the compact workbench."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request

from ai_workbench.core.chat_runner import ChatRunner
from ai_workbench.core.events import EventBus
from ai_workbench.core.font_assets import ensure_fonts_directory
from ai_workbench.core.knowledge_models import LocalKnowledgeModelBackend, ensure_knowledge_directories
from ai_workbench.core.knowledge_service import KnowledgeService
from ai_workbench.core.knowledge_store import MemoryKnowledgeStore
from ai_workbench.core.llm_service import LLMService
from ai_workbench.core.network_policy import NetworkPolicy
from ai_workbench.core.pet_service import PetService
from ai_workbench.core.runtime import ActiveRunRegistry, WorkbenchRuntime
from ai_workbench.core.runtime_memory import RuntimeMemoryService
from ai_workbench.core.runtime_resources import RuntimeResourcesService
from ai_workbench.core.settings import AppSettingsStore
from ai_workbench.core.stores import (
    LLMDefaultsStore,
    LLMProfileStore,
    MessageStore,
    MultimodalEmbeddingProfileStore,
    ProviderProfileStore,
    RunEventStore,
    RunStore,
    SessionStore,
    VisionProfileStore,
)
from ai_workbench.core.time import utc_now
from ai_workbench.core.utility_llm import UtilityLLMService
from ai_workbench.core.worldbook import MemoryWorldbookStore
from ai_workbench.db.database import get_engine, get_database_url, init_db
from ai_workbench.db.stores import (
    SqlAppSettingsStore,
    SqlKnowledgeStore,
    SqlLLMDefaultsStore,
    SqlLLMProfileStore,
    SqlMessageStore,
    SqlMultimodalEmbeddingProfileStore,
    SqlProviderProfileStore,
    SqlRunEventStore,
    SqlRunStore,
    SqlSessionStore,
    SqlVisionProfileStore,
    SqlWorldbookStore,
)


@dataclass
class RuntimeState:
    sessions: Any
    messages: Any
    runs: Any
    run_events: Any
    events: EventBus
    runtime: WorkbenchRuntime
    chat_runner: ChatRunner
    active_runs: ActiveRunRegistry
    llm: LLMService
    llm_profiles: Any
    provider_profiles: Any
    llm_defaults: Any
    app_settings: Any
    knowledge: Any
    knowledge_service: KnowledgeService
    knowledge_model_backend: Any
    worldbooks: Any
    pet_service: PetService
    utility_llm: UtilityLLMService
    network_policy: NetworkPolicy
    runtime_memory: RuntimeMemoryService
    runtime_resources: RuntimeResourcesService
    multimodal_embedding_profiles: Any
    vision_profiles: Any
    repo_root: Path
    database_url: str
    started_at: datetime = field(default_factory=utc_now)
    active_websockets: int = 0


def build_runtime_state(
    root: str | Path | None = None,
    llm_runtime: Any = None,
    database_url: str | None = None,
    use_memory: bool = False,
) -> RuntimeState:
    repo_root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    repo_root = repo_root.resolve()
    ensure_fonts_directory(repo_root)
    ensure_knowledge_directories(repo_root)

    if use_memory:
        sessions = SessionStore()
        messages = MessageStore(session_store=sessions)
        runs = RunStore()
        run_events = RunEventStore()
        llm_profiles = LLMProfileStore()
        provider_profiles = ProviderProfileStore()
        llm_defaults = LLMDefaultsStore()
        app_settings = AppSettingsStore()
        knowledge = MemoryKnowledgeStore()
        worldbooks = MemoryWorldbookStore()
        multimodal_profiles = MultimodalEmbeddingProfileStore()
        vision_profiles = VisionProfileStore()
        resolved_database_url = "sqlite:///:memory:"
    else:
        engine = get_engine(database_url)
        init_db(engine)
        sessions = SqlSessionStore(engine)
        messages = SqlMessageStore(engine)
        runs = SqlRunStore(engine)
        run_events = SqlRunEventStore(engine)
        llm_profiles = SqlLLMProfileStore(engine)
        provider_profiles = SqlProviderProfileStore(engine)
        llm_defaults = SqlLLMDefaultsStore(engine)
        app_settings = SqlAppSettingsStore(engine)
        knowledge = SqlKnowledgeStore(engine)
        worldbooks = SqlWorldbookStore(engine)
        multimodal_profiles = SqlMultimodalEmbeddingProfileStore(engine)
        vision_profiles = SqlVisionProfileStore(engine)
        resolved_database_url = get_database_url(database_url)
        interrupted = runs.interrupt_unfinished_runs()
        sessions.clear_interrupted_waiting_runs(interrupted)

    llm = LLMService(llm_runtime)
    active_runs = ActiveRunRegistry()
    events = EventBus(run_event_store=run_events, app_settings_store=app_settings)
    backend = LocalKnowledgeModelBackend(repo_root)
    knowledge_service = KnowledgeService(
        store=knowledge,
        model_backend=backend,
        provider_profiles=provider_profiles,
        repo_root=repo_root,
    )
    utility_llm = UtilityLLMService(
        llm_runtime=llm_runtime,
        llm_profile_store=llm_profiles,
        provider_profile_store=provider_profiles,
        app_settings_store=app_settings,
    )
    chat_runner = ChatRunner(
        sessions=sessions,
        messages=messages,
        runs=runs,
        events=events,
        llm=llm,
        llm_profiles=llm_profiles,
        provider_profiles=provider_profiles,
        llm_defaults=llm_defaults,
        app_settings=app_settings,
        utility_llm=utility_llm,
        knowledge=knowledge,
        knowledge_model_backend=backend,
        worldbooks=worldbooks,
        active_runs=active_runs,
    )
    runtime = WorkbenchRuntime(chat_runner=chat_runner, active_runs=active_runs)
    runtime_memory = RuntimeMemoryService(
        llm=llm,
        knowledge_model_backend=backend,
        llm_profiles=llm_profiles,
        provider_profiles=provider_profiles,
        llm_defaults=llm_defaults,
        sessions=sessions,
    )
    runtime_resources = RuntimeResourcesService()
    pet_service = PetService(repo_root=repo_root, app_settings_store=app_settings)
    return RuntimeState(
        sessions=sessions,
        messages=messages,
        runs=runs,
        run_events=run_events,
        events=events,
        runtime=runtime,
        chat_runner=chat_runner,
        active_runs=active_runs,
        llm=llm,
        llm_profiles=llm_profiles,
        provider_profiles=provider_profiles,
        llm_defaults=llm_defaults,
        app_settings=app_settings,
        knowledge=knowledge,
        knowledge_service=knowledge_service,
        knowledge_model_backend=backend,
        worldbooks=worldbooks,
        pet_service=pet_service,
        utility_llm=utility_llm,
        network_policy=NetworkPolicy(),
        runtime_memory=runtime_memory,
        runtime_resources=runtime_resources,
        multimodal_embedding_profiles=multimodal_profiles,
        vision_profiles=vision_profiles,
        repo_root=repo_root,
        database_url=resolved_database_url,
    )


def get_state(request: Request) -> RuntimeState:
    return request.app.state.runtime_state
