"""Explicit assembly for the shared model and chat services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request

from ai_workbench.core.chat_runner import ChatRunner
from ai_workbench.core.harness import HarnessSettingsStore, ToolRegistry, register_builtin_tools
from ai_workbench.core.chat_service import ChatService
from ai_workbench.core.personas import PersonaStore
from ai_workbench.core.events import EventBus
from ai_workbench.core.knowledge_service import KnowledgeService
from ai_workbench.core.knowledge_store import MemoryKnowledgeStore
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.openai_adapter import OpenAIAdapter
from ai_workbench.core.models.store import ModelProfileStore, ProviderProfileStore, ModelSettingsStore
from ai_workbench.core.network_policy import NetworkPolicy
from ai_workbench.core.runtime import ActiveRunRegistry, WorkbenchRuntime
from ai_workbench.core.runtime_resources import RuntimeResourcesService
from ai_workbench.core.settings import AppSettingsStore
from ai_workbench.core.stores import MessageStore, RunEventStore, RunStore, SessionStore
from ai_workbench.core.time import utc_now
from ai_workbench.core.utility_llm import UtilityLLMService
from ai_workbench.core.worldbook import MemoryWorldbookStore
from ai_workbench.db.database import get_engine, get_database_url, init_db
from ai_workbench.db.stores import (
    SqlAppSettingsStore, SqlKnowledgeStore, SqlMessageStore,
    SqlRunEventStore, SqlRunStore, SqlSessionStore, SqlWorldbookStore,
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
    chat_service: ChatService
    personas: PersonaStore
    active_runs: ActiveRunRegistry
    model_manager: ModelManager
    model_profiles: ModelProfileStore
    provider_profiles: ProviderProfileStore
    model_settings: ModelSettingsStore
    app_settings: Any
    knowledge: Any
    knowledge_service: KnowledgeService
    worldbooks: Any
    utility_llm: UtilityLLMService
    network_policy: NetworkPolicy
    tool_registry: ToolRegistry
    harness_settings: HarnessSettingsStore
    runtime_resources: RuntimeResourcesService
    runtime_supervisor: RuntimeSupervisor
    repo_root: Path
    database_url: str
    started_at: datetime = field(default_factory=utc_now)
    active_websockets: int = 0


def build_runtime_state(root: str | Path | None = None, database_url: str | None = None,
                        use_memory: bool = False, adapter_factory=OpenAIAdapter) -> RuntimeState:
    repo_root = Path(root or Path(__file__).resolve().parents[2]).resolve()
    engine = None
    if use_memory:
        sessions = SessionStore()
        messages = MessageStore(session_store=sessions)
        runs = RunStore()
        run_events = RunEventStore()
        app_settings = AppSettingsStore()
        knowledge = MemoryKnowledgeStore()
        worldbooks = MemoryWorldbookStore()
        resolved_database_url = "sqlite:///:memory:"
    else:
        engine = get_engine(database_url)
        init_db(engine)
        sessions = SqlSessionStore(engine)
        messages = SqlMessageStore(engine)
        runs = SqlRunStore(engine)
        run_events = SqlRunEventStore(engine)
        app_settings = SqlAppSettingsStore(engine)
        knowledge = SqlKnowledgeStore(engine)
        worldbooks = SqlWorldbookStore(engine)
        resolved_database_url = get_database_url(database_url)
        sessions.clear_interrupted_waiting_runs(runs.interrupt_unfinished_runs())

    profiles = ModelProfileStore(engine)
    providers = ProviderProfileStore(engine)
    model_settings = ModelSettingsStore(engine)
    active_runs = ActiveRunRegistry()
    network_policy = NetworkPolicy()
    events = EventBus(run_event_store=run_events, app_settings_store=app_settings)
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)
    harness_settings = HarnessSettingsStore(engine)
    supervisor = RuntimeSupervisor(repo_root, RuntimeStore(engine), events)
    manager = ModelManager(profiles, providers, model_settings, events, adapter_factory, supervisor)
    utility_llm = UtilityLLMService(model_manager=manager, app_settings_store=app_settings)
    personas = PersonaStore(engine)
    chat_service = ChatService(personas=personas, sessions=sessions, runs=runs, model_manager=manager,
        app_settings=app_settings, knowledge=knowledge, worldbooks=worldbooks, tool_registry=tool_registry)
    knowledge_service = KnowledgeService(store=knowledge, model_manager=manager, repo_root=repo_root,
        session_binding_resolver=lambda session_id: chat_service.effective_binding_ids(sessions.get_session(session_id), "knowledge"))
    chat_runner = ChatRunner(
        sessions=sessions, messages=messages, runs=runs, events=events,
        model_manager=manager, app_settings=app_settings, utility_llm=utility_llm,
        knowledge_service=knowledge_service, worldbooks=worldbooks, active_runs=active_runs,
        chat_service=chat_service,
        tool_registry=tool_registry, harness_settings=harness_settings, network_policy=network_policy, repo_root=repo_root,
    )
    runtime = WorkbenchRuntime(chat_runner=chat_runner, active_runs=active_runs)
    return RuntimeState(
        sessions=sessions, messages=messages, runs=runs, run_events=run_events, events=events,
        runtime=runtime, chat_runner=chat_runner, active_runs=active_runs,
        chat_service=chat_service, personas=personas,
        model_manager=manager, model_profiles=profiles, provider_profiles=providers,
        model_settings=model_settings, app_settings=app_settings, knowledge=knowledge,
        knowledge_service=knowledge_service, worldbooks=worldbooks,
        utility_llm=utility_llm, network_policy=network_policy,
        runtime_resources=RuntimeResourcesService(), repo_root=repo_root,
        runtime_supervisor=supervisor,
        tool_registry=tool_registry, harness_settings=harness_settings,
        database_url=resolved_database_url,
    )


def get_state(request: Request) -> RuntimeState:
    return request.app.state.runtime_state
