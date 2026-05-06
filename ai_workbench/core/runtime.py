import json
import re
from typing import Any, Optional

from ai_workbench.core.llm_config import LLMConfigError, require_llm_model, resolve_llm_config
from ai_workbench.core.router import Router
from ai_workbench.core.runner import AgentRunner, CommandRunner
from ai_workbench.core.schema.invocation import ActionInvocationRequest
from ai_workbench.core.schema.result import RunResult
from ai_workbench.core.schema.route import RouteKind
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.session import Session


TITLE_MAX_LENGTH = 40
TITLE_INPUT_MAX_CHARS = 1000


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
        if route.kind == RouteKind.ERROR:
            return RunResult(success=False, run_id="", error=route.error_message)
        if route.kind == RouteKind.COMMAND:
            result = await self.command_runner.run(route.target_id or "", route.args, route.session_id, input_message_id=input_message_id)
            self._maybe_generate_session_title(session.session_id, raw_input, result)
            return result
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
            result = await self.agent_runner.run(
                agent_id=route.target_id or "",
                action_id=route.action_id or "default",
                args=route.args,
                session_id=route.session_id,
                source_message_id=source_message_id,
                display_input=route.raw_input,
                attachments=attachments,
            )
            self._maybe_generate_session_title(session.session_id, route.args, result)
            return result
        return RunResult(success=False, run_id="", error=f"Unsupported route kind: {route.kind.value}")

    async def rerun_user_message(self, session: Session, message) -> RunResult:
        invocation = (message.metadata or {}).get("invocation")
        if isinstance(invocation, dict):
            route_type = invocation.get("route_type")
            if route_type == "command":
                raw_command = str(message.content)
                route = self.router.route(session, raw_command)
                command_id = route.target_id if route.kind == RouteKind.COMMAND else str(invocation.get("command_id") or "")
                args = route.args if route.kind == RouteKind.COMMAND else raw_command
                result = await self.command_runner.run(
                    command_id,
                    args,
                    session.session_id,
                    input_message_id=message.message_id,
                )
                self._maybe_generate_session_title(session.session_id, raw_command, result)
                return result
            if route_type == "agent":
                if self.agent_runner is None:
                    return RunResult(success=False, run_id="", error="Agent runner is not configured.")
                parsed_args = _agent_invocation_args(invocation, str(message.content))
                result = await self.agent_runner.run(
                    agent_id=str(invocation.get("agent_id") or session.default_agent_id),
                    action_id=str(invocation.get("action_id") or "default"),
                    args=parsed_args,
                    session_id=session.session_id,
                    input_message_id=message.message_id,
                    create_user_message=False,
                )
                self._maybe_generate_session_title(session.session_id, str(message.content), result)
                return result

        raw_input = str(message.content)
        route = self.router.route(session, raw_input)
        if route.kind == RouteKind.ERROR:
            return RunResult(success=False, run_id="", error=route.error_message, error_code=route.error_code)
        if route.kind == RouteKind.COMMAND:
            result = await self.command_runner.run(
                route.target_id or "",
                route.args,
                route.session_id,
                input_message_id=message.message_id,
            )
            self._maybe_generate_session_title(session.session_id, raw_input, result)
            return result
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
            result = await self.agent_runner.run(
                agent_id=route.target_id or "",
                action_id=route.action_id or "default",
                args=route.args,
                session_id=route.session_id,
                source_message_id=source_message_id,
                input_message_id=message.message_id,
                create_user_message=False,
            )
            self._maybe_generate_session_title(session.session_id, route.args, result)
            return result
        return RunResult(success=False, run_id="", error=f"Unsupported route kind: {route.kind.value}")

    async def retry_assistant_message(self, session: Session, message, source_user_message) -> RunResult:
        if self.agent_runner is None:
            return RunResult(success=False, run_id="", error="Agent runner is not configured.")
        agent_id = message.agent_id or ""
        action_id = message.action_id or "default"
        invocation = (source_user_message.metadata or {}).get("invocation")
        if isinstance(invocation, dict) and invocation.get("route_type") == "agent":
            args = _agent_invocation_args(invocation, str(source_user_message.content))
        else:
            args = str(source_user_message.content)
        result = await self.agent_runner.run(
            agent_id=agent_id,
            action_id=action_id,
            args=args,
            session_id=session.session_id,
            input_message_id=source_user_message.message_id,
            create_user_message=False,
        )
        self._maybe_generate_session_title(session.session_id, args, result)
        return result

    def _maybe_generate_session_title(self, session_id: str, user_text: str, result: RunResult) -> None:
        if not result.success or not result.run_id or self.agent_runner is None or self.agent_runner.session_store is None:
            return

        try:
            session = self.agent_runner.session_store.get_session(session_id)
        except KeyError:
            return
        if not is_default_session_title(session.title):
            return

        run = self.agent_runner.run_store.get_run(result.run_id)
        if run.status != RunStatus.DONE:
            return

        output = self._first_readable_run_output(session_id, run.run_id)
        if not str(user_text or "").strip() or output is None:
            return

        try:
            llm_config = self._resolve_title_llm_config(session, run)
            require_llm_model(llm_config)
            prompt = title_generation_prompt(user_text, output)
            title = self.agent_runner.llm_runtime.chat(
                messages=[{"role": "user", "content": prompt}],
                model_config=llm_config.values,
                stream=False,
            )
            cleaned = normalize_generated_title(str(title))
            if not cleaned or is_default_session_title(cleaned):
                return
            self.agent_runner.session_store.set_title(session_id, cleaned)
        except Exception as exc:
            self._record_title_warning(run.run_id, session_id, str(exc) or "Session title generation failed.")

    def _first_readable_run_output(self, session_id: str, run_id: str) -> Optional[str]:
        for message in self.agent_runner.message_store.list_messages(session_id):
            if message.run_id != run_id or message.role not in {"assistant", "agent", "command"}:
                continue
            if message.output_type in {"text", "markdown"}:
                return _truncate_text(str(message.content), TITLE_INPUT_MAX_CHARS)
            if message.output_type == "json":
                return _truncate_text(json.dumps(message.content, ensure_ascii=False, default=str), TITLE_INPUT_MAX_CHARS)
        return ""

    def _resolve_title_llm_config(self, session: Session, run) -> Any:
        capability = None
        capability_config = {}
        if self.agent_runner.capability_registry is not None:
            try:
                capability = self.agent_runner.capability_registry.get("llm")
            except KeyError:
                capability = None
        if self.agent_runner.capability_config_store is not None:
            capability_config = self.agent_runner.capability_config_store.get_config("llm")

        agent = None
        action = None
        if run.kind in {"agent", "action"}:
            try:
                agent = self.agent_runner.agent_registry.get(run.target_id)
                action_id = run.action_id or "default"
                action = next((item for item in agent.actions if item.id == action_id), None)
            except KeyError:
                agent = None
        if agent is not None and (run.metadata or {}).get("llm_resolution", {}).get("model_id"):
            return resolve_llm_config(
                agent_schema=agent,
                action_schema=action,
                capability_schema=capability,
                capability_config=capability_config,
                llm_profile_store=self.agent_runner.llm_profile_store,
                session_llm_profile_id=session.llm_profile_id,
            )

        default_agent = None
        default_action = None
        try:
            default_agent = self.agent_runner.agent_registry.get(session.default_agent_id)
            default_action = next((item for item in default_agent.actions if item.id == "default"), None)
        except KeyError:
            default_agent = None

        return resolve_llm_config(
            agent_schema=default_agent,
            action_schema=default_action,
            capability_schema=capability,
            capability_config=capability_config,
            llm_profile_store=self.agent_runner.llm_profile_store,
            session_llm_profile_id=session.llm_profile_id,
        )

    def _record_title_warning(self, run_id: str, session_id: str, warning: str) -> None:
        run = self.agent_runner.run_store.get_run(run_id)
        metadata = dict(run.metadata or {})
        warnings = list(metadata.get("warnings", []))
        warnings.append(f"Session title generation skipped: {warning}")
        metadata["warnings"] = warnings
        self.agent_runner.run_store.update_metadata(run_id, metadata)
        self.agent_runner.event_bus.emit(
            "run_warning",
            session_id=session_id,
            run_id=run_id,
            payload={"warning": warnings[-1]},
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
            create_user_message=False,
        )


def is_default_session_title(title: str) -> bool:
    value = str(title or "").strip()
    if not value:
        return True
    if value.lower() == "new chat":
        return True
    return re.fullmatch(r"session(?:\s+\d+|[\s-]+[0-9a-f]{6})?", value, flags=re.IGNORECASE) is not None


def title_generation_prompt(user_message: str, output: str) -> str:
    return (
        "Generate a short title for the conversation below.\n"
        "Requirements:\n"
        "- Use the user's language\n"
        "- No more than 12 words or 12 Chinese characters\n"
        "- Output only the title\n"
        "- Do not use quotes\n"
        "- Do not end with a period\n\n"
        f"User:\n{_truncate_text(str(user_message or '').strip(), TITLE_INPUT_MAX_CHARS)}\n\n"
        f"Reply:\n{_truncate_text(str(output or '').strip(), TITLE_INPUT_MAX_CHARS)}\n\n"
        "If the input is English, output a short English title.\n"
        "If the input is Chinese, output a short Chinese title."
    )


def normalize_generated_title(title: str) -> str:
    value = str(title or "").strip()
    value = re.sub(r"^[`\"'\s]+|[`\"'\s]+$", "", value)
    value = value.replace("\r", " ").replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"[.!?]+$", "", value).strip()
    return value[:TITLE_MAX_LENGTH].strip()


def _agent_invocation_args(invocation: dict, fallback_content: str) -> str:
    action_id = str(invocation.get("action_id") or "default")
    raw_text = str(invocation.get("raw_text") or "")
    if action_id != "default" or raw_text.startswith("@"):
        return str(invocation.get("args") if invocation.get("args") is not None else fallback_content)
    return fallback_content


def _truncate_text(value: str, limit: int) -> str:
    text = value or ""
    if len(text) <= limit:
        return text
    return text[:limit]
