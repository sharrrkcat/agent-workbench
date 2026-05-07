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
from ai_workbench.core.agent_settings import resolved_agent_settings, resolved_model_lifecycle, resolved_runtime_override
from ai_workbench.core.attachments import read_attachment_as_data_url, read_attachment_bytes, read_attachment_text
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.llm_config import LLMConfigError, resolve_llm_config
from ai_workbench.core.provider_status import unload_model_for_profile
from ai_workbench.core.run_lifecycle import RunLifecycle
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.message import ImageGalleryPayload, ImagePayload, RichContentPayload
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
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ScriptSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    default_agent_id: str


class ScriptStep:
    def __init__(self, ctx: "AgentContext", name: str) -> None:
        self.ctx = ctx
        self.name = name

    async def __aenter__(self) -> "ScriptStep":
        self.step = self.ctx.run.start_step(self.name)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            self.ctx.run.complete_step(self.step.step_id)
        else:
            self.ctx.run.fail_step(self.step.step_id, error_message=str(exc) or "Script step failed.")
        return False


class ScriptRunLifecycleProxy:
    def __init__(self, lifecycle: RunLifecycle, run_id: str) -> None:
        self.lifecycle = lifecycle
        self.run_id = run_id

    def update_progress(self, message: str, current: int = None, total: int = None):
        return self.lifecycle.update_progress(self.run_id, message=message, current=current, total=total)

    def start_step(self, label: str, message: str = None):
        return self.lifecycle.start_step(self.run_id, label=label, message=message)

    def complete_step(self, step_id: str, message: str = None):
        return self.lifecycle.complete_step(step_id, message=message)

    def fail_step(self, step_id: str, error_code: str = None, error_message: str = None):
        return self.lifecycle.fail_step(step_id, error_code=error_code, error_message=error_message)


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
    def __init__(
        self,
        llm_runtime: Any,
        default_model_config: Optional[Dict[str, Any]] = None,
        provider_profile_store: Any = None,
        llm_profile_store: Any = None,
        default_llm_resolution: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.llm_runtime = llm_runtime
        self.default_model_config = default_model_config or {}
        self.provider_profile_store = provider_profile_store
        self.llm_profile_store = llm_profile_store
        self.default_llm_resolution = default_llm_resolution or {}
        self.used = False

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
        self.used = True
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
                    self.used = True
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

    async def unload_model(
        self,
        model_profile_id: Optional[str] = None,
        provider_profile_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> CapabilityCallResult:
        try:
            if self.provider_profile_store is None or self.llm_profile_store is None:
                data = {
                    "ok": False,
                    "provider": "",
                    "unloaded": [],
                    "errors": [{"code": "MODEL_UNLOAD_UNSUPPORTED", "message": "Provider stores are not available."}],
                }
            else:
                resolved_provider_id = provider_profile_id
                if not resolved_provider_id:
                    resolved_provider_id = (
                        self.default_llm_resolution.get("provider_profile_id")
                        or self.default_model_config.get("provider_profile_id")
                    )
                resolved_model_profile_id = model_profile_id or self.default_llm_resolution.get("profile_id")
                resolved_model_id = model_id or self.default_llm_resolution.get("model_id") or self.default_model_config.get("model_id") or self.default_model_config.get("model")
                data = unload_model_for_profile(
                    provider_profile_store=self.provider_profile_store,
                    llm_profile_store=self.llm_profile_store,
                    provider_profile_id=resolved_provider_id,
                    model_profile_id=resolved_model_profile_id,
                    model_id=resolved_model_id,
                    reason="script",
                )
            return CapabilityCallResult(success=bool(data.get("ok")), data=data, error=_first_unload_error(data))
        except Exception as exc:
            return CapabilityCallResult(
                success=False,
                data={"ok": False, "unloaded": [], "errors": [{"code": "MODEL_UNLOAD_FAILED", "message": str(exc) or "Model unload failed."}]},
                error=str(exc) or "Model unload failed.",
            )


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
        llm_resolution: Optional[Dict[str, Any]] = None,
        provider_profile_store: Any = None,
        llm_profile_store: Any = None,
        attachments: Optional[list[dict[str, Any]]] = None,
        run_lifecycle: RunLifecycle = None,
    ) -> None:
        self.agent = agent
        self.action_id = action_id
        self.run_id = run_id
        self.input = ScriptInput(
            text=input_text,
            source_message_id=source_message_id,
            prefill=prefill or {},
            attachments=list(attachments or []),
        )
        self.session = ScriptSession(session_id=session.session_id, default_agent_id=session.default_agent_id)
        self.config = config or {}
        self.run_store = run_store
        self.message_store = message_store
        self.session_store = session_store
        self.event_bus = event_bus
        self.runtime_registry = runtime_registry
        self.llm = LLMProxy(
            llm_runtime,
            default_model_config=llm_model_config,
            provider_profile_store=provider_profile_store,
            llm_profile_store=llm_profile_store,
            default_llm_resolution=llm_resolution,
        )
        self.llm_resolution = llm_resolution or {}
        self.parent_message_id = parent_message_id
        self.waiting = False
        self.run = ScriptRunLifecycleProxy(run_lifecycle, run_id) if run_lifecycle is not None else None

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
            metadata={"success": True, **({"llm_resolution": self.llm_resolution} if self.llm_resolution else {})},
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

    async def reply_image(self, url: str, alt: str = None, title: str = None, caption: str = None, actions=None):
        payload = ImagePayload(url=url, alt=alt, title=title, caption=caption)
        return await self.reply(payload.model_dump(exclude_none=True), output_type="image", actions=actions)

    async def reply_images(self, images: list, actions=None):
        payload = ImageGalleryPayload(images=[ImagePayload.model_validate(image) for image in images])
        return await self.reply(payload.model_dump(exclude_none=True), output_type="image_gallery", actions=actions)

    async def reply_file_content(
        self,
        content: str,
        filename: str = None,
        language: str = None,
        mime_type: str = None,
        size: int = None,
        truncated: bool = False,
        actions=None,
    ):
        payload = {
            "content": content,
            "filename": filename,
            "language": language,
            "mime_type": mime_type,
            "size": size,
            "truncated": truncated,
        }
        return await self.reply({key: value for key, value in payload.items() if value is not None}, output_type="file_content", actions=actions)

    async def reply_blocks(self, blocks: list, actions=None):
        payload = RichContentPayload.model_validate({"blocks": blocks})
        return await self.reply(payload.model_dump(exclude_none=True), output_type="rich_content", actions=actions)

    def read_attachment_bytes(self, attachment: dict[str, Any] | str) -> bytes:
        return read_attachment_bytes(self._attachment_for_read(attachment))

    def read_attachment_text(self, attachment: dict[str, Any] | str) -> dict[str, Any]:
        return read_attachment_text(self._attachment_for_read(attachment))

    def attachment_as_data_url(self, attachment: dict[str, Any] | str) -> str:
        return read_attachment_as_data_url(self._attachment_for_read(attachment))

    def _attachment_for_read(self, attachment: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(attachment, dict):
            return attachment
        for item in self.input.attachments:
            if item.get("id") == attachment:
                return item
        raise ValueError(f"Attachment not found: {attachment}")

    def step(self, name: str) -> ScriptStep:
        if self.run is None:
            raise RuntimeError("Run lifecycle is not configured.")
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
        llm_profile_store=None,
        provider_profile_store=None,
        llm_defaults_store=None,
        agent_config_store=None,
        run_lifecycle: RunLifecycle = None,
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
        self.llm_profile_store = llm_profile_store
        self.provider_profile_store = provider_profile_store
        self.llm_defaults_store = llm_defaults_store
        self.agent_config_store = agent_config_store
        self.run_lifecycle = run_lifecycle or RunLifecycle(run_store, event_bus)

    async def run(
        self,
        agent: AgentSchema,
        action_id: str,
        args: str,
        session_id: str,
        source_message_id: str = "",
        parent_message_id: str = "",
        prefill=None,
        input_message_id: str = "",
        create_user_message: bool = True,
        display_input: str = "",
        attachments: list[dict] = None,
    ) -> RunResult:
        attachments = attachments or []
        session = self.session_store.get_session(session_id)
        user_message = None
        if input_message_id and not create_user_message:
            user_message = self.message_store.get_message(input_message_id)
            attachments = list((user_message.metadata or {}).get("attachments") or [])
        elif create_user_message:
            raw_text = display_input or args
            user_message = self.message_store.add_message(
                session_id=session_id,
                role="user",
                content=raw_text,
                agent_id=agent.id,
                action_id=action_id,
                metadata={
                    "attachments": attachments,
                    "input_source": "script_agent",
                    "invocation": {
                        "route_type": "agent",
                        "agent_id": agent.id,
                        "action_id": action_id,
                        "raw_text": raw_text,
                        "args": args,
                    },
                },
            )
        parent_id = parent_message_id or source_message_id or (user_message.message_id if user_message is not None else "")
        run = self.run_store.create_run(
            kind="agent" if action_id == "default" else "action",
            target_id=agent.id,
            action_id=action_id,
            session_id=session_id,
            metadata={
                "args": args,
                "input_message_id": user_message.message_id if user_message is not None else None,
                "parent_message_id": parent_id or None,
                "source_message_id": source_message_id or None,
            },
        )
        agent_config = self.agent_config_store.get_config(agent.id) if self.agent_config_store is not None else {}
        lifecycle = resolved_model_lifecycle(agent, agent_config)
        if self.agent_config_store is not None:
            metadata = dict(run.metadata)
            metadata["resolved_runtime"] = resolved_agent_settings(agent, agent_config)["runtime"]
            run = self.run_store.update_metadata(run.run_id, metadata)
        self.event_bus.emit("run_started", session_id=session_id, run_id=run.run_id)
        self.run_lifecycle.start_run(run.run_id, stage="running")

        resolving_step = self.run_lifecycle.start_step(run.run_id, "Resolving agent")
        try:
            script_run = self._load_script_run(agent)
        except Exception as exc:
            self.run_lifecycle.fail_step(resolving_step.step_id, error_message=str(exc) or "Script loading failed.")
            return self._fail(run.run_id, session_id, str(exc) or "Script loading failed.")
        self.run_lifecycle.complete_step(resolving_step.step_id)

        llm_config = None
        if _agent_uses_llm(agent):
            model_step = self.run_lifecycle.start_step(run.run_id, "Resolving model")
            try:
                llm_config = self._resolve_llm_model_config(agent, session_id)
                self._record_llm_resolution(run.run_id, llm_config)
            except LLMConfigError as exc:
                self.run_lifecycle.fail_step(model_step.step_id, error_code=exc.code, error_message=exc.message)
                return self._fail(run.run_id, session_id, exc.message, error_code=exc.code)
            self.run_lifecycle.complete_step(model_step.step_id)

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
            llm_model_config=llm_config.values if llm_config is not None else {},
            llm_resolution=self.run_store.get_run(run.run_id).metadata.get("llm_resolution"),
            provider_profile_store=self.provider_profile_store,
            llm_profile_store=self.llm_profile_store,
            attachments=attachments,
            run_lifecycle=self.run_lifecycle,
        )

        starting_step = self.run_lifecycle.start_step(run.run_id, "Starting script")
        self.run_lifecycle.complete_step(starting_step.step_id)
        running_step = self.run_lifecycle.start_step(run.run_id, "Running script")
        try:
            await script_run(ctx)
        except Exception as exc:
            self.run_lifecycle.fail_step(running_step.step_id, error_message=str(exc) or "Script agent failed.")
            result = self._fail(run.run_id, session_id, str(exc) or "Script agent failed.")
            self._apply_model_lifecycle(ctx, lifecycle)
            return result
        self.run_lifecycle.complete_step(running_step.step_id)

        final_run = self.run_store.get_run(run.run_id)
        if final_run.status == RunStatus.WAITING_FOR_USER:
            return RunResult(success=False, run_id=run.run_id, error="Waiting for user input.")

        saving_step = self.run_lifecycle.start_step(run.run_id, "Saving response")
        self.run_lifecycle.complete_step(saving_step.step_id)
        cleanup_step = self.run_lifecycle.start_step(run.run_id, "Cleanup")
        self._apply_model_lifecycle(ctx, lifecycle)
        self.run_lifecycle.complete_step(cleanup_step.step_id)
        done_run = self.run_lifecycle.complete_run(run.run_id)
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

    def _resolve_llm_model_config(self, agent: AgentSchema, session_id: str):
        capability = None
        capability_config = {}
        if self.capability_registry is not None:
            try:
                capability = self.capability_registry.get("llm")
            except KeyError:
                capability = None
        if self.capability_config_store is not None:
            capability_config = self.capability_config_store.get_config("llm")
        session_llm_profile_id = self.session_store.get_session(session_id).llm_profile_id if _agent_uses_llm(agent) else None
        return resolve_llm_config(
            agent_schema=agent,
            capability_schema=capability,
            capability_config=capability_config,
            llm_profile_store=self.llm_profile_store,
            provider_profile_store=self.provider_profile_store,
            llm_defaults_store=self.llm_defaults_store,
            session_llm_profile_id=session_llm_profile_id,
            agent_runtime=resolved_runtime_override(self.agent_config_store.get_config(agent.id) if self.agent_config_store is not None else {}),
        )

    def _record_llm_resolution(self, run_id: str, llm_config) -> None:
        from ai_workbench.core.runner import _public_llm_resolution

        run = self.run_store.get_run(run_id)
        metadata = dict(run.metadata)
        metadata["llm_resolution"] = _public_llm_resolution(llm_config)
        self.run_store.update_metadata(run_id, metadata)

    def _fail(self, run_id: str, session_id: str, error: str, error_code: str = None) -> RunResult:
        failed_run = self.run_lifecycle.fail_run(run_id, error_code, error)
        payload = {"error": error}
        if error_code:
            payload["error_code"] = error_code
        return RunResult(success=False, run_id=failed_run.run_id, error=error, error_code=error_code)

    def _apply_model_lifecycle(self, ctx: AgentContext, lifecycle) -> None:
        if lifecycle.unload != "after_run" or not ctx.llm.used:
            return
        result = unload_model_for_profile(
            provider_profile_store=self.provider_profile_store,
            llm_profile_store=self.llm_profile_store,
            provider_profile_id=ctx.llm_resolution.get("provider_profile_id"),
            model_profile_id=ctx.llm_resolution.get("profile_id"),
            model_id=ctx.llm_resolution.get("model_id") or ctx.llm.default_model_config.get("model_id") or ctx.llm.default_model_config.get("model"),
            reason="after_run",
        )
        run = self.run_store.get_run(ctx.run_id)
        metadata = dict(run.metadata)
        metadata["llm_unload"] = {
            "policy": lifecycle.unload,
            "attempted": not bool(result.get("skipped")),
            "ok": bool(result.get("ok")),
            "provider": result.get("provider"),
            "provider_profile_id": result.get("provider_profile_id"),
            "model_id": result.get("model_id"),
            "unloaded_count": len(result.get("unloaded") or []),
            "skipped": bool(result.get("skipped")),
            "skip_reason": result.get("skip_reason"),
            "code": result.get("code"),
            "errors": result.get("errors") or [],
            "result": result,
        }
        if not result.get("ok") and lifecycle.unload_failure == "warn":
            warnings = list(metadata.get("warnings", []))
            warnings.append(_first_unload_error(result) or "Model unload failed or is unsupported.")
            metadata["warnings"] = warnings
            self.event_bus.emit(
                "run_warning",
                session_id=ctx.session.session_id,
                run_id=ctx.run_id,
                payload={"warning": warnings[-1]},
            )
        self.run_store.update_metadata(ctx.run_id, metadata)


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


def _first_unload_error(data: Dict[str, Any]) -> Optional[str]:
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("message") or first.get("code") or "Model unload failed.")
    return None


def _messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    return "\n\n".join(f"{message.get('role', 'user')}: {message.get('content', '')}" for message in messages)


def _agent_uses_llm(agent: AgentSchema) -> bool:
    return bool(agent.llm or agent.model or "llm" in (agent.capabilities or []))
