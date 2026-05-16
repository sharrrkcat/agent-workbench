from typing import Any

from ai_workbench.core.llm_config import LLMConfigError
from ai_workbench.core.intent_router import build_intent_routing_metadata
from ai_workbench.core.router import Router
from ai_workbench.core.runner import AgentRunner, CommandRunner
from ai_workbench.core.schema.invocation import ActionInvocationRequest
from ai_workbench.core.schema.result import RunResult
from ai_workbench.core.schema.route import RouteKind, RouteTarget
from ai_workbench.core.session import Session
from ai_workbench.core.message_parts import text_from_parts


class WorkbenchRuntime:
    def __init__(self, router: Router, command_runner: CommandRunner, agent_runner: AgentRunner = None) -> None:
        self.router = router
        self.command_runner = command_runner
        self.agent_runner = agent_runner

    async def handle_input(
        self,
        session: Session,
        raw_input: str,
        input_message_id: str = "",
        attachments: list[dict] | None = None,
    ) -> RunResult:
        attachments = attachments or []
        route = self.router.route(session, raw_input)
        intent_metadata = await self._intent_routing_metadata(session, route)
        route = self._apply_intent_route(route, intent_metadata)
        if route.kind == RouteKind.ERROR:
            return RunResult(success=False, run_id="", error=route.error_message, error_code=route.error_code)
        if route.kind == RouteKind.COMMAND:
            if not input_message_id and isinstance(intent_metadata, dict) and intent_metadata.get("route_action") == "pet_command":
                input_message_id = self._create_intent_command_user_message(
                    session_id=route.session_id,
                    content=raw_input,
                    attachments=attachments,
                    intent_metadata=intent_metadata,
                )
            return await self.command_runner.run(route.target_id or "", route.args, route.session_id, input_message_id=input_message_id, intent_routing_metadata=intent_metadata)
        if route.kind == RouteKind.AGENT:
            if self.agent_runner is None:
                return RunResult(success=False, run_id="", error="Agent runner is not configured.")
            source_message_id = ""
            if (route.action_id or "default") != "default":
                latest = self.agent_runner.message_store.find_latest_assistant_message(
                    route.session_id,
                    agent_id=route.target_id,
                )
                if latest is not None:
                    source_message_id = latest.message_id
            return await self.agent_runner.run(
                agent_id=route.target_id or "",
                action_id=route.action_id or "default",
                args=route.args,
                session_id=route.session_id,
                source_message_id=source_message_id,
                display_input=route.raw_input,
                attachments=attachments,
                invocation_route_kind=route.invocation_route_kind or "agent",
                intent_routing_metadata=intent_metadata,
                temporary_knowledge_base_ids=_intent_temporary_kb_ids(intent_metadata),
                knowledge_query_override=_intent_query_override(intent_metadata),
            )
        return RunResult(success=False, run_id="", error=f"Unsupported route kind: {route.kind.value}")

    async def rerun_user_message(self, session: Session, message) -> RunResult:
        invocation = (message.metadata or {}).get("invocation")
        if isinstance(invocation, dict):
            route_type = invocation.get("route_type")
            if route_type == "command":
                raw_command = text_from_parts(message.parts)
                route = self.router.route(session, raw_command)
                command_id = route.target_id if route.kind == RouteKind.COMMAND else str(invocation.get("command_id") or "")
                args = route.args if route.kind == RouteKind.COMMAND else raw_command
                return await self.command_runner.run(
                    command_id,
                    args,
                    session.session_id,
                    input_message_id=message.message_id,
                )
            if route_type == "agent":
                if self.agent_runner is None:
                    return RunResult(success=False, run_id="", error="Agent runner is not configured.")
                parsed_args = _agent_invocation_args(invocation, text_from_parts(message.parts))
                return await self.agent_runner.run(
                    agent_id=str(invocation.get("agent_id") or session.default_agent_id),
                    action_id=str(invocation.get("action_id") or "default"),
                    args=parsed_args,
                    session_id=session.session_id,
                    input_message_id=message.message_id,
                    create_user_message=False,
                )

        raw_input = text_from_parts(message.parts)
        route = self.router.route(session, raw_input)
        intent_metadata = await self._intent_routing_metadata(session, route)
        route = self._apply_intent_route(route, intent_metadata)
        if route.kind == RouteKind.ERROR:
            return RunResult(success=False, run_id="", error=route.error_message, error_code=route.error_code)
        if route.kind == RouteKind.COMMAND:
            return await self.command_runner.run(
                route.target_id or "",
                route.args,
                route.session_id,
                input_message_id=message.message_id,
                intent_routing_metadata=intent_metadata,
            )
        if route.kind == RouteKind.AGENT:
            if self.agent_runner is None:
                return RunResult(success=False, run_id="", error="Agent runner is not configured.")
            source_message_id = ""
            if (route.action_id or "default") != "default":
                latest = self.agent_runner.message_store.find_latest_assistant_message(
                    route.session_id,
                    agent_id=route.target_id,
                )
                if latest is not None:
                    source_message_id = latest.message_id
            return await self.agent_runner.run(
                agent_id=route.target_id or "",
                action_id=route.action_id or "default",
                args=route.args,
                session_id=route.session_id,
                source_message_id=source_message_id,
                input_message_id=message.message_id,
                create_user_message=False,
                invocation_route_kind=route.invocation_route_kind or "agent",
                intent_routing_metadata=intent_metadata,
                temporary_knowledge_base_ids=_intent_temporary_kb_ids(intent_metadata),
                knowledge_query_override=_intent_query_override(intent_metadata),
            )
        return RunResult(success=False, run_id="", error=f"Unsupported route kind: {route.kind.value}")

    def _create_intent_command_user_message(
        self,
        *,
        session_id: str,
        content: str,
        attachments: list[dict],
        intent_metadata: dict[str, Any],
    ) -> str:
        user_message = self.command_runner.message_store.add_message(
            session_id=session_id,
            role="user",
            content=content,
            metadata={
                "attachments": attachments,
                "input_source": "text",
                "intent_routing": {
                    "predicted_intent": intent_metadata.get("predicted_intent"),
                    "generated_command": intent_metadata.get("generated_command"),
                    "executed": intent_metadata.get("executed"),
                },
                "invocation": {
                    "route_type": "intent_auto_route",
                    "route_kind": "intent_auto_route",
                    "predicted_intent": intent_metadata.get("predicted_intent"),
                    "generated_command": intent_metadata.get("generated_command"),
                    "raw_text": content,
                },
            },
            speaker_type="user",
            speaker_id="local_user",
            speaker_name="User",
            origin="user_message",
        )
        return user_message.message_id

    async def retry_assistant_message(self, session: Session, message, source_user_message) -> RunResult:
        if self.agent_runner is None:
            return RunResult(success=False, run_id="", error="Agent runner is not configured.")
        agent_id = message.agent_id or ""
        action_id = message.action_id or "default"
        invocation = (source_user_message.metadata or {}).get("invocation")
        if isinstance(invocation, dict) and invocation.get("route_type") == "agent":
            args = _agent_invocation_args(invocation, text_from_parts(source_user_message.parts))
        else:
            args = text_from_parts(source_user_message.parts)
        return await self.agent_runner.run(
            agent_id=agent_id,
            action_id=action_id,
            args=args,
            session_id=session.session_id,
            input_message_id=source_user_message.message_id,
            create_user_message=False,
            enforce_callable=True,
        )

    def announce_model_change_if_needed(self, session_id: str) -> None:
        if self.agent_runner is None or self.agent_runner.session_store is None:
            return
        session = self.agent_runner.session_store.get_session(session_id)
        if session.llm_profile_id == session.last_announced_llm_profile_id:
            return

        profile = None
        label = "Default"
        profile_alias = None
        if session.llm_profile_id:
            if self.agent_runner.llm_profile_store is None:
                raise LLMConfigError("LLM_PROFILE_NOT_FOUND", f"LLM profile not found: {session.llm_profile_id}")
            try:
                profile = self.agent_runner.llm_profile_store.get(session.llm_profile_id)
            except KeyError as exc:
                raise LLMConfigError(
                    "LLM_PROFILE_NOT_FOUND",
                    f"LLM profile not found: {session.llm_profile_id}",
                ) from exc
            if not profile.enabled:
                raise LLMConfigError("LLM_PROFILE_DISABLED", f"LLM profile is disabled: {profile.alias}")
            label = profile.name or profile.alias or profile.model_id
            profile_alias = profile.alias

        self.agent_runner.message_store.add_message(
            session_id=session_id,
            role="system",
            content=f"Session model switched to {label}",
            content_version=2,
            metadata={
                "event_type": "model_changed",
                "profile_id": profile.id if profile else None,
                "profile_name": profile.name if profile else None,
                "profile_key": profile_alias,
                "is_default": profile is None,
            },
        )
        self.agent_runner.session_store.set_last_announced_llm_profile(session_id, session.llm_profile_id)

    async def _intent_routing_metadata(self, session: Session, route) -> dict[str, Any] | None:
        if self.agent_runner is None:
            return None
        return await build_intent_routing_metadata(
            session=session,
            route=route,
            agent_registry=self.agent_runner.agent_registry,
            agent_config_store=self.agent_runner.agent_config_store,
            app_settings_store=self.agent_runner.app_settings_store,
            utility_llm_service=getattr(self.agent_runner, "utility_llm_service", None),
            knowledge_store=getattr(self.agent_runner, "knowledge_store", None),
            knowledge_model_backend=getattr(self.agent_runner, "knowledge_model_backend", None),
            capability_registry=getattr(self.agent_runner, "capability_registry", None),
            capability_config_store=getattr(self.agent_runner, "capability_config_store", None),
            runtime_registry=getattr(self.agent_runner, "runtime_registry", None),
            command_registry=getattr(self.command_runner, "command_registry", None),
            semantic_router=getattr(self.agent_runner, "semantic_router", None),
        )

    def _apply_intent_route(self, route: RouteTarget, intent_metadata: dict[str, Any] | None) -> RouteTarget:
        if route.kind != RouteKind.AGENT or not isinstance(intent_metadata, dict):
            return route
        if intent_metadata.get("route_action") == "pet_command" and intent_metadata.get("executed"):
            generated = str(intent_metadata.get("generated_command") or "/pet status")
            parsed = self.router.route(
                type("SessionLike", (), {"session_id": route.session_id, "waiting_run_id": None, "default_agent_id": route.target_id})(),
                generated,
            )
            if parsed.kind == RouteKind.COMMAND and parsed.target_id == "/pet":
                return parsed.model_copy(update={"raw_input": route.raw_input})
            return route
        if intent_metadata.get("route_action") != "route_agent":
            return route
        target_agent_id = str(intent_metadata.get("target_agent_id") or "")
        target_action_id = str(intent_metadata.get("target_action_id") or "default")
        if not target_agent_id:
            return route
        return route.model_copy(
            update={
                "target_id": target_agent_id,
                "action_id": target_action_id,
                "invocation_route_kind": "intent_auto_route",
            }
        )

    async def invoke_action(
        self,
        session_id: str,
        agent_id: str,
        action_id: str,
        source_message_id: str = None,
        input_text: str = "",
        prefill=None,
        parent_message_id: str = None,
    ) -> RunResult:
        if self.agent_runner is None:
            return RunResult(success=False, run_id="", error="Agent runner is not configured.")

        request = ActionInvocationRequest(
            session_id=session_id,
            agent_id=agent_id,
            action_id=action_id,
            source_message_id=source_message_id,
            parent_message_id=parent_message_id,
            input_text=input_text,
            prefill=prefill or {},
        )
        return await self.agent_runner.run(
            agent_id=request.agent_id,
            action_id=request.action_id,
            args=request.input_text,
            session_id=request.session_id,
            source_message_id=request.source_message_id or "",
            parent_message_id=request.parent_message_id or "",
            prefill=request.prefill,
            create_user_message=False,
        )

def _agent_invocation_args(invocation: dict, fallback_content: str) -> str:
    action_id = str(invocation.get("action_id") or "default")
    raw_text = str(invocation.get("raw_text") or "")
    if action_id != "default" or raw_text.startswith("@"):
        return str(invocation.get("args") if invocation.get("args") is not None else fallback_content)
    return fallback_content


def _intent_temporary_kb_ids(intent_metadata: dict[str, Any] | None) -> list[str] | None:
    if not isinstance(intent_metadata, dict) or intent_metadata.get("route_action") != "knowledge_override":
        return None
    value = intent_metadata.get("temporary_knowledge_base_ids")
    if not isinstance(value, list):
        return None
    return [str(item) for item in value if str(item or "").strip()]


def _intent_query_override(intent_metadata: dict[str, Any] | None) -> str | None:
    if not isinstance(intent_metadata, dict) or intent_metadata.get("route_action") != "knowledge_override":
        return None
    value = intent_metadata.get("knowledge_query_override")
    return str(value) if isinstance(value, str) and value.strip() else None
