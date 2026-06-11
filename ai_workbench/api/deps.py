from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.font_assets import ensure_fonts_directory
from ai_workbench.core.router import Router
from ai_workbench.core.runner import ActiveRunRegistry, AgentRunner, CommandRunner
from ai_workbench.core.runtime import WorkbenchRuntime
from ai_workbench.core.runtime_memory import RuntimeMemoryService
from ai_workbench.core.runtime_resources import RuntimeResourcesService
from ai_workbench.core.settings import AppSettingsStore
from ai_workbench.core.utility_llm import UtilityLLMService
from ai_workbench.core.intent_semantic_router import SemanticRouter
from ai_workbench.core.knowledge_models import LocalKnowledgeModelBackend, ensure_knowledge_directories
from ai_workbench.core.knowledge_store import MemoryKnowledgeStore
from ai_workbench.core.worldbook import MemoryWorldbookStore
from ai_workbench.core.stores import (
    AgentConfigStore,
    CapabilityConfigStore,
    LLMDefaultsStore,
    LLMProfileStore,
    MessageStore,
    MultimodalEmbeddingProfileStore,
    ProviderProfileStore,
    RunEventStore,
    RunStore,
    SessionStore,
    SessionAgentStateStore,
    VisionProfileStore,
)
from ai_workbench.core.time import utc_now
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.db.stores import (
    SqlAgentConfigStore,
    SqlCapabilityConfigStore,
    SqlLLMProfileStore,
    SqlLLMDefaultsStore,
    SqlMessageStore,
    SqlMultimodalEmbeddingProfileStore,
    SqlProviderProfileStore,
    SqlRunEventStore,
    SqlRunStore,
    SqlSessionStore,
    SqlSessionAgentStateStore,
    SqlVisionProfileStore,
)


@dataclass
class RuntimeState:
    agents: AgentRegistry
    capabilities: CapabilityRegistry
    commands: CommandRegistry
    runtimes: CapabilityRuntimeRegistry
    sessions: SessionStore
    messages: MessageStore
    runs: RunStore
    run_events: Any
    events: EventBus
    router: Router
    command_runner: CommandRunner
    agent_runner: AgentRunner
    runtime: WorkbenchRuntime
    runtime_memory: Any
    runtime_resources: Any
    active_runs: ActiveRunRegistry
    agent_configs: Any = None
    capability_configs: Any = None
    llm_profiles: Any = None
    provider_profiles: Any = None
    multimodal_embedding_profiles: Any = None
    vision_profiles: Any = None
    llm_defaults: Any = None
    app_settings: Any = None
    session_agent_states: Any = None
    knowledge: Any = None
    worldbooks: Any = None
    knowledge_model_backend: Any = None
    utility_llm: Any = None
    semantic_router: Any = None
    repo_root: Path | None = None
    database_url: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    active_websockets: int = 0


def build_runtime_state(
    root: str | Path | None = None,
    llm_runtime: Any = None,
    database_url: str | None = None,
    use_memory: bool = False,
) -> RuntimeState:
    repo_root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    ensure_fonts_directory(repo_root)
    ensure_knowledge_directories(repo_root)
    agents = AgentRegistry()
    agents.load_from_directory(repo_root / "agents")

    capabilities = CapabilityRegistry()
    capabilities.load_from_directory(repo_root / "capabilities")
    commands = CommandRegistry.from_capability_registry(capabilities)

    runtimes = CapabilityRuntimeRegistry()
    runtimes.load_from_directory(repo_root / "capabilities")
    if llm_runtime is not None:
        runtimes.replace("llm", llm_runtime)
    llm = runtimes.get_runtime("llm")

    agent_configs = None
    capability_configs = None
    worldbooks = None
    if use_memory:
        sessions = SessionStore()
        messages = MessageStore(session_store=sessions)
        runs = RunStore()
        run_events = RunEventStore()
        agent_configs = AgentConfigStore()
        capability_configs = CapabilityConfigStore()
        llm_profiles = LLMProfileStore()
        provider_profiles = ProviderProfileStore()
        multimodal_embedding_profiles = MultimodalEmbeddingProfileStore()
        vision_profiles = VisionProfileStore()
        llm_defaults = LLMDefaultsStore()
        app_settings = AppSettingsStore()
        session_agent_states = SessionAgentStateStore()
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
        agent_configs = SqlAgentConfigStore(engine)
        capability_configs = SqlCapabilityConfigStore(engine)
        llm_profiles = SqlLLMProfileStore(engine)
        provider_profiles = SqlProviderProfileStore(engine)
        multimodal_embedding_profiles = SqlMultimodalEmbeddingProfileStore(engine)
        vision_profiles = SqlVisionProfileStore(engine)
        llm_defaults = SqlLLMDefaultsStore(engine)
        from ai_workbench.db.database import get_database_url
        from ai_workbench.db.stores import SqlAppSettingsStore, SqlKnowledgeStore, SqlWorldbookStore

        app_settings = SqlAppSettingsStore(engine)
        session_agent_states = SqlSessionAgentStateStore(engine)
        knowledge = SqlKnowledgeStore(engine)
        worldbooks = SqlWorldbookStore(engine)
        resolved_database_url = get_database_url(database_url)
        interrupted_run_ids = runs.interrupt_unfinished_runs()
        sessions.clear_interrupted_waiting_runs(interrupted_run_ids)
    events = EventBus(run_event_store=run_events, app_settings_store=app_settings)
    active_runs = ActiveRunRegistry()
    router = Router(agent_registry=agents, command_registry=commands)
    command_runner = CommandRunner(
        command_registry=commands,
        runtime_registry=runtimes,
        run_store=runs,
        message_store=messages,
        event_bus=events,
        capability_config_store=capability_configs,
        capability_registry=capabilities,
    )
    knowledge_model_backend = LocalKnowledgeModelBackend(repo_root)
    utility_llm = UtilityLLMService(
        repo_root,
        llm_runtime=llm,
        llm_profile_store=llm_profiles,
        provider_profile_store=provider_profiles,
        capability_registry=capabilities,
        capability_config_store=capability_configs,
        llm_defaults_store=llm_defaults,
    )
    semantic_router = SemanticRouter()
    try:
        knowledge_runtime = runtimes.get_runtime("knowledge")
        configure = getattr(knowledge_runtime, "configure", None)
        if callable(configure):
            configure(knowledge_store=knowledge, model_backend=knowledge_model_backend)
    except KeyError:
        pass
    agent_runner = AgentRunner(
        agent_registry=agents,
        run_store=runs,
        message_store=messages,
        event_bus=events,
        llm_runtime=llm,
        session_store=sessions,
        runtime_registry=runtimes,
        agent_config_store=agent_configs,
        capability_registry=capabilities,
        capability_config_store=capability_configs,
        llm_profile_store=llm_profiles,
        provider_profile_store=provider_profiles,
        llm_defaults_store=llm_defaults,
        app_settings_store=app_settings,
        session_agent_state_store=session_agent_states,
        active_runs=active_runs,
        knowledge_store=knowledge,
        knowledge_model_backend=knowledge_model_backend,
        worldbook_store=worldbooks,
        utility_llm_service=utility_llm,
        semantic_router=semantic_router,
    )
    runtime_memory = RuntimeMemoryService(
        agents=agents,
        runtimes=runtimes,
        sessions=sessions,
        runs=runs,
        agent_configs=agent_configs,
        capability_configs=capability_configs,
        capabilities=capabilities,
        llm_profiles=llm_profiles,
        provider_profiles=provider_profiles,
        llm_defaults=llm_defaults,
        knowledge_model_backend=knowledge_model_backend,
        agent_runner=agent_runner,
    )
    runtime_resources = RuntimeResourcesService()
    try:
        runtime_control = runtimes.get_runtime("runtime")
        configure = getattr(runtime_control, "configure", None)
        if callable(configure):
            configure(runtime_memory)
    except KeyError:
        pass
    runtime = WorkbenchRuntime(router=router, command_runner=command_runner, agent_runner=agent_runner)
    return RuntimeState(
        agents=agents,
        capabilities=capabilities,
        commands=commands,
        runtimes=runtimes,
        sessions=sessions,
        messages=messages,
        runs=runs,
        run_events=run_events,
        events=events,
        router=router,
        command_runner=command_runner,
        agent_runner=agent_runner,
        runtime=runtime,
        runtime_memory=runtime_memory,
        runtime_resources=runtime_resources,
        active_runs=active_runs,
        agent_configs=agent_configs,
        capability_configs=capability_configs,
        llm_profiles=llm_profiles,
        provider_profiles=provider_profiles,
        multimodal_embedding_profiles=multimodal_embedding_profiles,
        vision_profiles=vision_profiles,
        llm_defaults=llm_defaults,
        app_settings=app_settings,
        session_agent_states=session_agent_states,
        knowledge=knowledge,
        worldbooks=worldbooks,
        knowledge_model_backend=knowledge_model_backend,
        utility_llm=utility_llm,
        semantic_router=semantic_router,
        repo_root=repo_root,
        database_url=resolved_database_url,
    )


def get_state(request: Request) -> RuntimeState:
    return request.app.state.runtime_state
