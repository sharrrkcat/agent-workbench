from ai_workbench.core.router import Router
from ai_workbench.core.runner import AgentRunner, CommandRunner
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
