from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.router import Router
from ai_workbench.core.runner import ActiveRunRegistry, AgentRunner, CommandRunner
from ai_workbench.core.runtime import WorkbenchRuntime
from ai_workbench.core.stores import (
    AgentConfigStore,
    CapabilityConfigStore,
    LLMProfileStore,
    MessageStore,
    RunEventStore,
    RunStore,
    SessionStore,
)
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.db.stores import (
    SqlAgentConfigStore,
    SqlCapabilityConfigStore,
    SqlLLMProfileStore,
    SqlMessageStore,
    SqlRunEventStore,
    SqlRunStore,
    SqlSessionStore,
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
    active_runs: ActiveRunRegistry
    agent_configs: Any = None
    capability_configs: Any = None
    llm_profiles: Any = None


def build_runtime_state(
    root: str | Path | None = None,
    llm_runtime: Any = None,
    database_url: str | None = None,
    use_memory: bool = False,
) -> RuntimeState:
    repo_root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
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
    if use_memory:
        sessions = SessionStore()
        messages = MessageStore(session_store=sessions)
        runs = RunStore()
        run_events = RunEventStore()
        agent_configs = AgentConfigStore()
        capability_configs = CapabilityConfigStore()
        llm_profiles = LLMProfileStore()
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
        interrupted_run_ids = runs.interrupt_unfinished_runs()
        sessions.clear_interrupted_waiting_runs(interrupted_run_ids)
    events = EventBus(run_event_store=run_events)
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
        active_runs=active_runs,
    )
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
        active_runs=active_runs,
        agent_configs=agent_configs,
        capability_configs=capability_configs,
        llm_profiles=llm_profiles,
    )


def get_state(request: Request) -> RuntimeState:
    return request.app.state.runtime_state
