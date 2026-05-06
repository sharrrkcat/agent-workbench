from ai_workbench.core.router import Router
from ai_workbench.core.runner import AgentRunner, CommandRunner
from ai_workbench.core.llm_config import LLMConfigError
from ai_workbench.core.schema.invocation import ActionInvocationRequest
from ai_workbench.core.schema.result import RunResult
from ai_workbench.core.schema.route import RouteKind
from ai_workbench.core.session import Session


class WorkbenchRuntime:
    def __init__(self, router: Router, command_runner: CommandRunner, agent_runner: AgentRunner = None) -> None:
        self.router = router
        self.command_runner = command_runner
        self.agent_runner = agent_runner

    async def handle_input(self, session: Session, raw_input: str, input_message_id: str = "") -> RunResult:
        route = self.router.route(session, raw_input)
        if route.kind == RouteKind.ERROR:
            return RunResult(success=False, run_id="", error=route.error_message)
        if route.kind == RouteKind.COMMAND:
            return await self.command_runner.run(route.target_id or "", route.args, route.session_id, input_message_id=input_message_id)
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
            )
        return RunResult(success=False, run_id="", error=f"Unsupported route kind: {route.kind.value}")

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
            output_type="event",
            metadata={
                "event_type": "model_changed",
                "profile_id": profile.id if profile else None,
                "profile_name": profile.name if profile else None,
                "profile_key": profile_alias,
                "is_default": profile is None,
            },
        )
        self.agent_runner.session_store.set_last_announced_llm_profile(session_id, session.llm_profile_id)

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
        )
