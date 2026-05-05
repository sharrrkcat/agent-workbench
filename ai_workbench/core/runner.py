from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.context import ContextBuilder
from ai_workbench.core.events import EventBus
from ai_workbench.core.schema.result import CommandResult, RunResult
from ai_workbench.core.schema.run import RunSchema, RunStatus
from ai_workbench.core.script import ScriptAgentRunner
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore


class AgentRunner:
    def __init__(
        self,
        agent_registry: AgentRegistry,
        run_store: RunStore,
        message_store: MessageStore,
        event_bus: EventBus,
        llm_runtime: object,
        session_store: SessionStore = None,
        runtime_registry: CapabilityRuntimeRegistry = None,
        agent_config_store=None,
    ) -> None:
        self.agent_registry = agent_registry
        self.run_store = run_store
        self.message_store = message_store
        self.event_bus = event_bus
        self.llm_runtime = llm_runtime
        self.context_builder = ContextBuilder(message_store)
        self.session_store = session_store
        self.runtime_registry = runtime_registry
        self.agent_config_store = agent_config_store
        self.script_runner = None
        if session_store is not None and runtime_registry is not None:
            self.script_runner = ScriptAgentRunner(
                agent_registry=agent_registry,
                run_store=run_store,
                message_store=message_store,
                session_store=session_store,
                event_bus=event_bus,
                runtime_registry=runtime_registry,
                llm_runtime=llm_runtime,
            )

    async def run(
        self,
        agent_id: str,
        action_id: str,
        args: str,
        session_id: str,
        source_message_id: str = "",
        parent_message_id: str = "",
        prefill=None,
    ) -> RunResult:
        try:
            agent = self.agent_registry.get(agent_id)
        except KeyError:
            return RunResult(success=False, run_id="", error=f"Unknown agent: {agent_id}", error_code="AGENT_NOT_FOUND")

        if self.agent_config_store is not None and not self.agent_config_store.is_enabled(agent_id):
            return RunResult(
                success=False,
                run_id="",
                error=f"Agent is disabled: {agent_id}",
                error_code="AGENT_DISABLED",
            )

        if action_id not in {action.id for action in agent.actions}:
            return RunResult(
                success=False,
                run_id="",
                error=f"Unknown action '{action_id}' for agent '{agent_id}'.",
                error_code="ACTION_NOT_FOUND",
            )

        if agent.type == "script":
            if self.script_runner is None:
                return RunResult(success=False, run_id="", error="Script agent runner is not configured.")
            return await self.script_runner.run(
                agent=agent,
                action_id=action_id,
                args=args,
                session_id=session_id,
                source_message_id=source_message_id,
                parent_message_id=parent_message_id,
                prefill=prefill or {},
            )

        if agent.type != "prompt":
            return RunResult(success=False, run_id="", error=f"Unsupported agent type: {agent.type}")

        action = next(item for item in agent.actions if item.id == action_id)
        parent_id = parent_message_id or source_message_id or ""
        current_user_message_id = ""
        if action_id == "default":
            user_message = self.message_store.add_message(
                session_id=session_id,
                role="user",
                content=args,
                agent_id=agent_id,
                action_id=action_id,
                metadata={"input_source": "text"},
            )
            current_user_message_id = user_message.message_id
            parent_id = user_message.message_id

        kind = "agent" if action_id == "default" else "action"
        run = self.run_store.create_run(
            kind=kind,
            target_id=agent_id,
            action_id=action_id,
            session_id=session_id,
            metadata={"args": args, "source_message_id": source_message_id or None, "prefill": prefill or {}},
        )
        self.event_bus.emit("run_started", session_id=session_id, run_id=run.run_id)
        if action_id != "default":
            self.event_bus.emit(
                "action_invoked",
                session_id=session_id,
                run_id=run.run_id,
                payload={
                    "agent_id": agent_id,
                    "action_id": action_id,
                    "source_message_id": source_message_id or None,
                    "prefill": prefill or {},
                },
            )
        self.run_store.update_status(run.run_id, RunStatus.RUNNING, current_step="running")

        context_policy = action.context_policy or agent.context_policy
        try:
            context = self.context_builder.build(
                session_id=session_id,
                args=args,
                policy=context_policy,
                source_message_id=source_message_id or None,
                current_message_id=current_user_message_id or None,
            )
        except KeyError as exc:
            error = str(exc)
            failed_run = self.run_store.update_status(
                run.run_id,
                RunStatus.FAILED,
                current_step="failed",
                error=error,
            )
            self.event_bus.emit(
                "run_failed",
                session_id=session_id,
                run_id=failed_run.run_id,
                payload={"error": error},
            )
            return RunResult(success=False, run_id=failed_run.run_id, error=error)

        messages = []
        if agent.prompt:
            prompt = agent.prompt
            if action.instruction:
                prompt = f"{prompt.rstrip()}\n\n{action.instruction}"
            messages.append({"role": "system", "content": prompt})
        messages.extend(context.messages)

        try:
            content = self.llm_runtime.chat(messages=messages, model_config=agent.model or {}, stream=False)
        except Exception as exc:
            error = str(exc) or "Prompt agent failed."
            failed_run = self.run_store.update_status(
                run.run_id,
                RunStatus.FAILED,
                current_step="failed",
                error=error,
            )
            self.event_bus.emit(
                "run_failed",
                session_id=session_id,
                run_id=failed_run.run_id,
                payload={"error": error},
            )
            return RunResult(success=False, run_id=failed_run.run_id, error=error)

        original_user_message_id = self._find_original_user_message_id(source_message_id)
        metadata = {
            "success": True,
            "context_warnings": context.warnings,
            "original_user_message_id": original_user_message_id,
            "prefill": prefill or {},
        }
        message = self.message_store.add_message(
            session_id=session_id,
            role="assistant",
            content=content,
            agent_id=agent_id,
            action_id=action_id,
            run_id=run.run_id,
            output_type="text",
            parent_message_id=parent_id or None,
            available_actions=self._available_actions(agent, source_message_id=""),
            metadata=metadata,
        )
        message_actions = self._available_actions(agent, source_message_id=message.message_id)
        if message_actions:
            message = message.model_copy(update={"available_actions": message_actions})
            self.message_store.update_message(message)
        done_run = self.run_store.update_status(
            run.run_id,
            RunStatus.DONE,
            current_step="done",
        )
        self.event_bus.emit("run_done", session_id=session_id, run_id=done_run.run_id)
        self.event_bus.emit(
            "message_done",
            session_id=session_id,
            run_id=done_run.run_id,
            message_id=message.message_id,
            payload={"available_actions": message.available_actions},
        )

        lifecycle_result = self._apply_model_lifecycle(agent.model_lifecycle, agent.model or {}, done_run.run_id, session_id)
        if lifecycle_result:
            done_run = self.run_store.get_run(done_run.run_id)
            if done_run.status == RunStatus.FAILED:
                return RunResult(success=False, run_id=done_run.run_id, data=content, error=done_run.error)

        return RunResult(success=True, run_id=done_run.run_id, data=content)

    def _available_actions(self, agent, source_message_id: str):
        actions = []
        for action in agent.actions:
            if action.id == "default" or not action.callable or not action.label:
                continue
            actions.append(
                {
                    "agent_id": agent.id,
                    "action_id": action.id,
                    "label": action.label,
                    "source_message_id": source_message_id,
                    "prefill": {},
                }
            )
        return actions

    def _find_original_user_message_id(self, source_message_id: str):
        if not source_message_id:
            return None
        try:
            source = self.message_store.get_message(source_message_id)
        except KeyError:
            return None
        return source.parent_message_id

    def _apply_model_lifecycle(self, lifecycle, model_config, run_id: str, session_id: str) -> bool:
        if lifecycle.unload != "after_run":
            return False

        unload = getattr(self.llm_runtime, "unload", None)
        if not callable(unload):
            result = {"success": False, "unsupported": True, "message": "LLM runtime does not support unload."}
        else:
            try:
                result = unload(model_config=model_config)
            except Exception as exc:
                result = {"success": False, "unsupported": False, "message": str(exc) or "Unload failed."}

        if result.get("success"):
            return True

        message = result.get("message") or "LLM unload failed or is unsupported."
        if lifecycle.unload_failure == "ignore":
            return True
        if lifecycle.unload_failure == "warn":
            run = self.run_store.get_run(run_id)
            metadata = dict(run.metadata)
            warnings = list(metadata.get("warnings", []))
            warnings.append(message)
            metadata["warnings"] = warnings
            self.run_store.update_metadata(run_id, metadata)
            self.event_bus.emit(
                "run_warning",
                session_id=session_id,
                run_id=run_id,
                payload={"warning": message},
            )
            return True

        self.run_store.update_status(run_id, RunStatus.FAILED, current_step="unload_failed", error=message)
        self.event_bus.emit("run_failed", session_id=session_id, run_id=run_id, payload={"error": message})
        return True


class CommandRunner:
    def __init__(
        self,
        command_registry: CommandRegistry,
        runtime_registry: CapabilityRuntimeRegistry,
        run_store: RunStore,
        message_store: MessageStore,
        event_bus: EventBus,
        capability_config_store=None,
    ) -> None:
        self.command_registry = command_registry
        self.runtime_registry = runtime_registry
        self.run_store = run_store
        self.message_store = message_store
        self.event_bus = event_bus
        self.capability_config_store = capability_config_store

    async def run(self, command_name: str, args: str, session_id: str) -> CommandResult:
        try:
            command = self.command_registry.get(command_name)
        except KeyError:
            return CommandResult(
                success=False,
                run_id="",
                error=f"Unknown command: {command_name}",
                error_code="COMMAND_NOT_FOUND",
            )

        if self.capability_config_store is not None and not self.capability_config_store.is_enabled(command.capability_id):
            return CommandResult(
                success=False,
                run_id="",
                error=f"Capability is disabled: {command.capability_id}",
                error_code="CAPABILITY_DISABLED",
            )

        run = self.run_store.create_run(
            kind="command",
            target_id=command_name,
            session_id=session_id,
            metadata={"args": args},
        )
        self.event_bus.emit("run_started", session_id=session_id, run_id=run.run_id)
        self.run_store.update_status(run.run_id, RunStatus.RUNNING, current_step="running")

        try:
            method = self.runtime_registry.get_method(command.capability_id, command.method)
            data = method(args)
        except Exception as exc:
            error = str(exc) or "Command failed."
            failed_run = self.run_store.update_status(
                run.run_id,
                RunStatus.FAILED,
                current_step="failed",
                error=error,
            )
            message = self.message_store.add_message(
                session_id=session_id,
                role="command",
                content=error,
                command_name=command_name,
                run_id=failed_run.run_id,
                output_type="text",
                metadata={"success": False},
            )
            self.event_bus.emit(
                "run_failed",
                session_id=session_id,
                run_id=failed_run.run_id,
                payload={"error": error},
            )
            self.event_bus.emit(
                "message_done",
                session_id=session_id,
                run_id=failed_run.run_id,
                message_id=message.message_id,
            )
            return CommandResult(success=False, run_id=failed_run.run_id, error=error)

        done_run = self.run_store.update_status(run.run_id, RunStatus.DONE, current_step="done")
        message = self.message_store.add_message(
            session_id=session_id,
            role="command",
            content=data,
            command_name=command_name,
            run_id=done_run.run_id,
            output_type="text",
            metadata={"success": True},
        )
        self.event_bus.emit("run_done", session_id=session_id, run_id=done_run.run_id)
        self.event_bus.emit(
            "message_done",
            session_id=session_id,
            run_id=done_run.run_id,
            message_id=message.message_id,
        )
        return CommandResult(success=True, run_id=done_run.run_id, data=data)
