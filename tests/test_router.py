from pathlib import Path

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.router import Router
from ai_workbench.core.schema.route import RouteKind
from ai_workbench.core.stores import SessionStore


ROOT = Path(__file__).resolve().parents[1]


def make_router() -> Router:
    agents = AgentRegistry()
    agents.load_from_directory(ROOT / "agents")

    capabilities = CapabilityRegistry()
    capabilities.load_from_directory(ROOT / "capabilities")
    commands = CommandRegistry.from_capability_registry(capabilities)

    return Router(agent_registry=agents, command_registry=commands)


def make_session(default_agent_id: str = "chat"):
    return SessionStore().create_session(default_agent_id=default_agent_id)


def test_plain_text_routes_to_session_default_agent() -> None:
    route = make_router().route(make_session(default_agent_id="chat"), "hello")

    assert route.kind == RouteKind.AGENT
    assert route.target_id == "chat"
    assert route.action_id == "default"
    assert route.args == "hello"


def test_base64_command_routes_to_command_target() -> None:
    route = make_router().route(make_session(), "/base64 hello")

    assert route.kind == RouteKind.COMMAND
    assert route.target_id == "/base64"
    assert route.args == "hello"


def test_agent_invocation_routes_to_default_action() -> None:
    route = make_router().route(make_session(), "@translate hello")

    assert route.kind == RouteKind.AGENT
    assert route.target_id == "translate"
    assert route.action_id == "default"
    assert route.args == "hello"


def test_agent_action_invocation_routes_to_named_action() -> None:
    route = make_router().route(make_session(), "@translate:formal")

    assert route.kind == RouteKind.AGENT
    assert route.target_id == "translate"
    assert route.action_id == "formal"
    assert route.args == ""


def test_agent_action_invocation_preserves_args() -> None:
    route = make_router().route(make_session(), "@translate:formal more formal please")

    assert route.kind == RouteKind.AGENT
    assert route.target_id == "translate"
    assert route.action_id == "formal"
    assert route.args == "more formal please"


def test_unknown_command_returns_structured_error() -> None:
    route = make_router().route(make_session(), "/missing hello")

    assert route.kind == RouteKind.ERROR
    assert route.error_code == "unknown_command"
    assert "Unknown command: /missing" == route.error_message


def test_unknown_agent_returns_structured_error() -> None:
    route = make_router().route(make_session(), "@missing hello")

    assert route.kind == RouteKind.ERROR
    assert route.error_code == "unknown_agent"
    assert "Unknown agent: missing" == route.error_message


def test_unknown_agent_action_returns_structured_error() -> None:
    route = make_router().route(make_session(), "@translate:missing hello")

    assert route.kind == RouteKind.ERROR
    assert route.error_code == "unknown_agent_action"
    assert "Unknown action 'missing' for agent 'translate'." == route.error_message


def test_waiting_run_routes_to_resume_before_parsing_command_or_agent() -> None:
    store = SessionStore()
    session = store.create_session(default_agent_id="chat")
    session = store.set_waiting_run(session.session_id, "run-123")

    command_route = make_router().route(session, "/missing should not parse")
    agent_route = make_router().route(session, "@missing should not parse")

    assert command_route.kind == RouteKind.RESUME
    assert command_route.run_id == "run-123"
    assert command_route.args == "/missing should not parse"
    assert agent_route.kind == RouteKind.RESUME
    assert agent_route.run_id == "run-123"
    assert agent_route.args == "@missing should not parse"

