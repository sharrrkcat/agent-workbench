import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.llm_config import resolve_llm_config
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.result import CapabilityCallResult, RunResult
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.session import Session
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore


class ScriptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    context: list = Field(default_factory=list)
    source_message_id: Optional[str] = None
    prefill: Dict[str, Any] = Field(default_factory=dict)


class ScriptSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    default_agent_id: str


class ScriptStep:
    def __init__(self, ctx: "AgentContext", name: str) -> None:
        self.ctx = ctx
        self.name = name

    async def __aenter__(self) -> "ScriptStep":
        self.ctx.run_store.update_status(self.ctx.run_id, RunStatus.RUNNING, current_step=self.name)
        self.ctx.event_bus.emit(
            "run_step",
            session_id=self.ctx.session.session_id,
            run_id=self.ctx.run_id,
            payload={"step": self.name},
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class CapabilityProxy:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def __getattr__(self, method_name: str):
        method = getattr(self.runtime, method_name)

        async def call(*args, **kwargs) -> CapabilityCallResult:
            try:
                data = method(*args, **kwargs)
                if inspect.isawaitable(data):
                    data = await data
                return CapabilityCallResult(success=True, data=data)
            except Exception as exc:
                return CapabilityCallResult(success=False, error=str(exc) or "Capability call failed.")

        return call


class LLMProxy:
    def __init__(self, llm_runtime: Any, default_model_config: Optional[Dict[str, Any]] = None) -> None:
        self.llm_runtime = llm_runtime
        self.default_model_config = default_model_config or {}

    async def text(self, system: str, user: str, **options) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return await self.chat(messages=messages, **options)

    async def json(self, system: str, user: str, **options) -> Dict[str, Any]:
        content = await self.text(system=system, user=user, **options)
        try:
            parsed = json.loads(_extract_json_text(content))
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM response did not contain valid JSON: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("LLM JSON response must be an object.")
        return parsed

    async def chat(self, messages: List[Dict[str, Any]], **options) -> str:
        chat = getattr(self.llm_runtime, "chat", None)
        model_config = options.pop("model_config", None) or self.default_model_config
        if callable(chat):
            data = chat(messages=messages, model_config=model_config, stream=options.pop("stream", False), **options)
        else:
            prompt = _messages_to_prompt(messages)
            generate = getattr(self.llm_runtime, "generate")
            data = generate(prompt=prompt, model_config=model_config, stream=options.pop("stream", False), **options)
        if inspect.isawaitable(data):
            data = await data
        return str(data)

    async def generate(
        self,
        prompt: Optional[str] = None,
        model_config: Optional[Dict[str, Any]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        user: Optional[str] = None,
        **options,
    ) -> CapabilityCallResult:
        try:
            if messages is not None:
                data = await self.chat(messages=messages, model_config=model_config, **options)
            elif system is not None or user is not None:
                data = await self.text(system=system or "", user=user or prompt or "", model_config=model_config, **options)
            else:
                generate = getattr(self.llm_runtime, "generate", None)
                resolved_prompt = prompt if prompt is not None else options.pop("prompt", "")
                if callable(generate):
                    data = generate(
                        prompt=resolved_prompt,
                        model_config=model_config or self.default_model_config,
                        stream=options.pop("stream", False),
                        **options,
                    )
                    if inspect.isawaitable(data):
                        data = await data
                else:
                    data = await self.chat(
                        messages=[{"role": "user", "content": resolved_prompt}],
                        model_config=model_config,
                        **options,
                    )
            return CapabilityCallResult(success=True, data=data)
        except Exception as exc:
            return CapabilityCallResult(success=False, error=str(exc) or "LLM generate failed.")

    async def unload(self, model_config: Optional[Dict[str, Any]] = None) -> CapabilityCallResult:
        try:
            unload = getattr(self.llm_runtime, "unload")
            data = unload(model_config=model_config or self.default_model_config)
            if inspect.isawaitable(data):
                data = await data
            return CapabilityCallResult(success=bool(data.get("success")), data=data, error=data.get("message"))
        except Exception as exc:
            return CapabilityCallResult(success=False, error=str(exc) or "LLM unload failed.")


class AgentContext:
    def __init__(
        self,
        agent: AgentSchema,
        action_id: str,
        session: Session,
        run_id: str,
        input_text: str,
        source_message_id: Optional[str],
        parent_message_id: Optional[str],
        prefill: Optional[Dict[str, Any]],
        config: Optional[Dict[str, Any]],
        run_store: RunStore,
        message_store: MessageStore,
        session_store: SessionStore,
        event_bus: EventBus,
        runtime_registry: CapabilityRuntimeRegistry,
        llm_runtime: Any,
        llm_model_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.agent = agent
        self.action_id = action_id
        self.run_id = run_id
        self.input = ScriptInput(
            text=input_text,
            source_message_id=source_message_id,
            prefill=prefill or {},
        )
        self.session = ScriptSession(session_id=session.session_id, default_agent_id=session.default_agent_id)
        self.config = config or {}
        self.run_store = run_store
        self.message_store = message_store
        self.session_store = session_store
        self.event_bus = event_bus
        self.runtime_registry = runtime_registry
        self.llm = LLMProxy(llm_runtime, default_model_config=llm_model_config)
        self.parent_message_id = parent_message_id
        self.waiting = False

    async def reply(self, content: Any, type: str = "text", output_type: Optional[str] = None, actions=None):
        resolved_output_type = output_type or type
        message = self.message_store.add_message(
            session_id=self.session.session_id,
            role="agent",
            content=content,
            agent_id=self.agent.id,
            action_id=self.action_id,
            run_id=self.run_id,
            output_type=resolved_output_type,
            parent_message_id=self.parent_message_id,
            available_actions=actions or [],
            metadata={"success": True},
        )
        self.event_bus.emit(
            "message_done",
            session_id=self.session.session_id,
            run_id=self.run_id,
            message_id=message.message_id,
            payload={"available_actions": message.available_actions},
        )
        return message

    async def reply_text(self, text: str, actions=None):
        return await self.reply(text, output_type="text", actions=actions)

    async def reply_markdown(self, markdown: str, actions=None):
        return await self.reply(markdown, output_type="markdown", actions=actions)

    async def reply_json(self, data: dict | list, actions=None):
        return await self.reply(data, output_type="json", actions=actions)

    def step(self, name: str) -> ScriptStep:
        return ScriptStep(self, name)

    def capability(self, name: str) -> CapabilityProxy:
        return CapabilityProxy(self.runtime_registry.get_runtime(name))

    async def ask(self, prompt: str, timeout: int = 120) -> CapabilityCallResult:
        await self.reply(prompt, type="text")
        self.run_store.update_status(
            self.run_id,
            RunStatus.WAITING_FOR_USER,
            current_step="waiting_for_user",
        )
        self.session_store.set_waiting_run(self.session.session_id, self.run_id)
        self.waiting = True
        self.event_bus.emit(
            "run_waiting_for_input",
            session_id=self.session.session_id,
            run_id=self.run_id,
            payload={"timeout": timeout},
        )
        return CapabilityCallResult(success=False, error="Waiting for user input.")


class ScriptAgentRunner:
    def __init__(
        self,
        agent_registry: AgentRegistry,
        run_store: RunStore,
        message_store: MessageStore,
        session_store: SessionStore,
        event_bus: EventBus,
        runtime_registry: CapabilityRuntimeRegistry,
        llm_runtime: Any,
        capability_registry: CapabilityRegistry = None,
        capability_config_store=None,
    ) -> None:
        self.agent_registry = agent_registry
        self.run_store = run_store
        self.message_store = message_store
        self.session_store = session_store
        self.event_bus = event_bus
        self.runtime_registry = runtime_registry
        self.llm_runtime = llm_runtime
        self.capability_registry = capability_registry
        self.capability_config_store = capability_config_store

    async def run(
        self,
        agent: AgentSchema,
        action_id: str,
        args: str,
        session_id: str,
        source_message_id: str = "",
        parent_message_id: str = "",
        prefill=None,
    ) -> RunResult:
        session = self.session_store.get_session(session_id)
        user_message = self.message_store.add_message(
            session_id=session_id,
            role="user",
            content=args,
            agent_id=agent.id,
            action_id=action_id,
            metadata={"input_source": "script_agent"},
        )
        parent_id = parent_message_id or source_message_id or user_message.message_id
        run = self.run_store.create_run(
            kind="agent" if action_id == "default" else "action",
            target_id=agent.id,
            action_id=action_id,
            session_id=session_id,
            metadata={"args": args, "source_message_id": source_message_id or None},
        )
        self.event_bus.emit("run_started", session_id=session_id, run_id=run.run_id)
        self.run_store.update_status(run.run_id, RunStatus.RUNNING, current_step="running")

        try:
            script_run = self._load_script_run(agent)
        except Exception as exc:
            return self._fail(run.run_id, session_id, str(exc) or "Script loading failed.")

        ctx = AgentContext(
            agent=agent,
            action_id=action_id,
            session=session,
            run_id=run.run_id,
            input_text=args,
            source_message_id=source_message_id or None,
            parent_message_id=parent_id,
            prefill=prefill or {},
            config={},
            run_store=self.run_store,
            message_store=self.message_store,
            session_store=self.session_store,
            event_bus=self.event_bus,
            runtime_registry=self.runtime_registry,
            llm_runtime=self.llm_runtime,
            llm_model_config=self._resolve_llm_model_config(agent),
        )

        try:
            await script_run(ctx)
        except Exception as exc:
            return self._fail(run.run_id, session_id, str(exc) or "Script agent failed.")

        final_run = self.run_store.get_run(run.run_id)
        if final_run.status == RunStatus.WAITING_FOR_USER:
            return RunResult(success=False, run_id=run.run_id, error="Waiting for user input.")

        done_run = self.run_store.update_status(run.run_id, RunStatus.DONE, current_step="done")
        self.event_bus.emit("run_done", session_id=session_id, run_id=done_run.run_id)
        return RunResult(success=True, run_id=done_run.run_id, data=None)

    def _load_script_run(self, agent: AgentSchema):
        if not agent.entry:
            raise ValueError("script agent requires an entry field")
        agent_dir = self.agent_registry.get_agent_dir(agent.id).resolve()
        entry_path = (agent_dir / agent.entry).resolve()
        try:
            entry_path.relative_to(agent_dir)
        except ValueError as exc:
            raise ValueError("script entry must stay inside the agent directory") from exc
        if not entry_path.is_file():
            raise ValueError(f"script entry not found: {agent.entry}")

        module = _load_module(entry_path, f"agent_workbench_script_{agent.id}")
        run_callable = getattr(module, "run", None)
        if not callable(run_callable) or not inspect.iscoroutinefunction(run_callable):
            raise ValueError("script entry must export async def run(ctx)")
        return run_callable

    def _resolve_llm_model_config(self, agent: AgentSchema) -> Dict[str, Any]:
        capability = None
        capability_config = {}
        if self.capability_registry is not None:
            try:
                capability = self.capability_registry.get("llm")
            except KeyError:
                capability = None
        if self.capability_config_store is not None:
            capability_config = self.capability_config_store.get_config("llm")
        return resolve_llm_config(
            agent_schema=agent,
            capability_schema=capability,
            capability_config=capability_config,
        ).values

    def _fail(self, run_id: str, session_id: str, error: str) -> RunResult:
        failed_run = self.run_store.update_status(run_id, RunStatus.FAILED, current_step="failed", error=error)
        self.event_bus.emit("run_failed", session_id=session_id, run_id=run_id, payload={"error": error})
        return RunResult(success=False, run_id=failed_run.run_id, error=error)


def _load_module(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError("could not load script module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _extract_json_text(content: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return content.strip()


def _messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    return "\n\n".join(f"{message.get('role', 'user')}: {message.get('content', '')}" for message in messages)
