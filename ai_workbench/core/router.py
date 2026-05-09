import re
from typing import Optional, Tuple

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.schema.agent import AGENT_ID_RE
from ai_workbench.core.schema.command import COMMAND_NAME_RE
from ai_workbench.core.schema.route import RouteKind, RouteTarget
from ai_workbench.core.session import Session


ACTION_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]*$")
AGENT_INVOKE_RE = re.compile(r"^@(?P<agent>[a-zA-Z][a-zA-Z0-9_\-]*)(?::(?P<action>[a-zA-Z][a-zA-Z0-9_\-]*))?(?:\s+(?P<args>.*))?$")
COMMAND_INVOKE_RE = re.compile(r"^(?P<command>/[a-zA-Z][a-zA-Z0-9_\-]*)(?:\s+(?P<args>.*))?$")
CURRENT_AGENT_ACTION_RE = re.compile(r"^:(?P<action>[A-Za-z][A-Za-z0-9_\-]*)(?:\s+(?P<args>[\s\S]*))?$")


def parse_command_input(raw_input: str) -> Optional[Tuple[str, str]]:
    match = COMMAND_INVOKE_RE.match(raw_input)
    if not match:
        return None
    return match.group("command"), match.group("args") or ""


def parse_agent_input(raw_input: str) -> Optional[Tuple[str, str, str]]:
    match = AGENT_INVOKE_RE.match(raw_input)
    if not match:
        return None
    return match.group("agent"), match.group("action") or "default", match.group("args") or ""


def parse_current_agent_action_input(raw_input: str) -> Optional[Tuple[str, str]]:
    match = CURRENT_AGENT_ACTION_RE.match(raw_input)
    if not match:
        return None
    return match.group("action"), match.group("args") or ""


class Router:
    def __init__(self, agent_registry: AgentRegistry, command_registry: CommandRegistry) -> None:
        self.agent_registry = agent_registry
        self.command_registry = command_registry

    def route(self, session: Session, raw_input: str) -> RouteTarget:
        if session.waiting_run_id:
            return RouteTarget(
                kind=RouteKind.RESUME,
                session_id=session.session_id,
                raw_input=raw_input,
                run_id=session.waiting_run_id,
                args=raw_input,
            )

        if raw_input.startswith("/"):
            return self._route_command(session, raw_input)

        if raw_input.startswith("@"):
            return self._route_agent_invocation(session, raw_input)

        if raw_input.startswith(":"):
            shortcut = self._route_current_agent_action_shortcut(session, raw_input)
            if shortcut is not None:
                return shortcut

        return self._route_agent(session, raw_input, session.default_agent_id, "default", raw_input)

    def _route_command(self, session: Session, raw_input: str) -> RouteTarget:
        parsed = parse_command_input(raw_input)
        if parsed is None:
            return self._error(session, raw_input, "invalid_command", "Invalid command syntax.")

        command_name, args = parsed
        if not COMMAND_NAME_RE.match(command_name):
            return self._error(session, raw_input, "invalid_command", "Invalid command name.")

        try:
            self.command_registry.get(command_name)
        except KeyError:
            return self._error(session, raw_input, "unknown_command", f"Unknown command: {command_name}")

        return RouteTarget(
            kind=RouteKind.COMMAND,
            session_id=session.session_id,
            raw_input=raw_input,
            target_id=command_name,
            args=args,
        )

    def _route_agent_invocation(self, session: Session, raw_input: str) -> RouteTarget:
        parsed = parse_agent_input(raw_input)
        if parsed is None:
            return self._error(session, raw_input, "invalid_agent_invocation", "Invalid agent invocation syntax.")

        agent_id, action_id, args = parsed
        return self._route_agent(session, raw_input, agent_id, action_id, args)

    def _route_current_agent_action_shortcut(self, session: Session, raw_input: str) -> Optional[RouteTarget]:
        parsed = parse_current_agent_action_input(raw_input)
        if parsed is None:
            return None
        if not session.default_agent_id:
            return self._error(
                session,
                raw_input,
                "missing_default_agent",
                "Current session has no default Agent. Switch the session default Agent or use @agent_id:action.",
            )
        action_id, args = parsed
        return self._route_agent(
            session,
            raw_input,
            session.default_agent_id,
            action_id,
            args,
            invocation_route_kind="current_agent_action_shortcut",
        )

    def _route_agent(
        self,
        session: Session,
        raw_input: str,
        agent_id: str,
        action_id: str,
        args: str,
        invocation_route_kind: str = "agent",
    ) -> RouteTarget:
        if not AGENT_ID_RE.match(agent_id):
            return self._error(session, raw_input, "invalid_agent", "Invalid agent id.")
        if not ACTION_ID_RE.match(action_id):
            return self._error(session, raw_input, "invalid_agent_action", "Invalid agent action id.")

        try:
            agent = self.agent_registry.get(agent_id)
        except KeyError:
            return self._error(session, raw_input, "unknown_agent", f"Unknown agent: {agent_id}")

        known_actions = {action.id for action in agent.actions}
        if action_id not in known_actions:
            if invocation_route_kind == "current_agent_action_shortcut":
                return self._error(
                    session,
                    raw_input,
                    "unknown_agent_action",
                    (
                        f'Current agent "{agent.name}" has no action "{action_id}". '
                        "Use @agent_id:action to call another Agent, or switch the session default Agent."
                    ),
                )
            return self._error(
                session,
                raw_input,
                "unknown_agent_action",
                f"Unknown action '{action_id}' for agent '{agent_id}'.",
            )

        return RouteTarget(
            kind=RouteKind.AGENT,
            session_id=session.session_id,
            raw_input=raw_input,
            target_id=agent_id,
            action_id=action_id,
            args=args,
            invocation_route_kind=invocation_route_kind,
        )

    def _error(self, session: Session, raw_input: str, code: str, message: str) -> RouteTarget:
        return RouteTarget(
            kind=RouteKind.ERROR,
            session_id=session.session_id,
            raw_input=raw_input,
            error_code=code,
            error_message=message,
        )
