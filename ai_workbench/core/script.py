import importlib.util
import inspect
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.agent_settings import resolved_agent_settings, resolved_knowledge_context_mode, resolved_model_lifecycle, resolved_runtime_override
from ai_workbench.core.attachments import (
    read_attachment_as_data_url,
    read_attachment_bytes,
    read_attachment_text,
    save_generated_attachment_base64,
    save_generated_attachment_bytes,
)
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.config_schema import resolve_config
from ai_workbench.core.events import EventBus
from ai_workbench.core.forms import validate_action_form_block
from ai_workbench.core.llm_config import LLMConfigError, resolve_llm_config
from ai_workbench.core.message_parts import (
    blocks_to_parts,
    capability_output_to_parts,
    make_file_part,
    make_error_part,
    make_image_part,
    make_json_part,
    make_media_group_part,
    make_text_part,
    validate_message_parts,
)
from ai_workbench.core.knowledge_context import append_knowledge_to_system, build_session_knowledge_context, knowledge_step_metadata
from ai_workbench.core.memory_context import append_system_context, build_core_memory_context, context_metadata_for_step
from ai_workbench.core.provider_status import refresh_provider_status_for_profile, unload_model_for_profile
from ai_workbench.core.run_lifecycle import RunLifecycle
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.result import CapabilityCallResult, RunResult
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.session_titles import apply_deferred_title_model_unload, maybe_generate_session_title_before_llm_call
from ai_workbench.core.session import Session
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore
from ai_workbench.core.time import isoformat_utc
from ai_workbench.core.worldbook_context import build_session_worldbook_context, worldbook_step_metadata


@dataclass
class ScriptLLMStreamChunk:
    text: str = ""
    raw: Any = None
    finish_reason: Optional[str] = None
    model: Optional[str] = None


class ScriptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    action_id: Optional[str] = None
    form_id: Optional[str] = None
    is_silent_submission: bool = False
    context: list = Field(default_factory=list)
    source_message_id: Optional[str] = None
    prefill: Dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ScriptSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    default_agent_id: str
    context_mode: str = "single_assistant"


class ScriptStep:
    def __init__(self, ctx: "AgentContext", name: str, parent_step_id: Optional[str] = None) -> None:
        self.ctx = ctx
        self.name = name
        self.parent_step_id = parent_step_id

    async def __aenter__(self) -> "ScriptStep":
        self.step = self.ctx.run.start_step(self.name, parent_step_id=self.parent_step_id)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            self.ctx.run.complete_step(self.step.step_id)
        else:
            self.ctx.run.fail_step(self.step.step_id, error_message=str(exc) or "Script step failed.")
        return False


class ScriptRunLifecycleProxy:
    def __init__(self, lifecycle: RunLifecycle, run_id: str, default_parent_step_id: Optional[str] = None) -> None:
        self.lifecycle = lifecycle
        self.run_id = run_id
        self.default_parent_step_id = default_parent_step_id

    def update_progress(self, message: str, current: int = None, total: int = None):
        return self.lifecycle.update_progress(self.run_id, message=message, current=current, total=total)

    def start_step(self, label: str, message: str = None, metadata: Optional[dict[str, Any]] = None, parent_step_id: Optional[str] = None):
        return self.lifecycle.start_step(
            self.run_id,
            label=label,
            message=message,
            metadata=metadata,
            parent_step_id=parent_step_id if parent_step_id is not None else self.default_parent_step_id,
        )

    def complete_step(self, step_id: str, message: str = None):
        return self.lifecycle.complete_step(step_id, message=message)

    def update_step(self, step_id: str, message: str = None, metadata: Optional[dict[str, Any]] = None):
        step = self.lifecycle.run_store.update_step(step_id, message=message, metadata=metadata)
        self.lifecycle._emit_step("run_step_updated", step)
        return step

    def fail_step(self, step_id: str, error_code: str = None, error_message: str = None):
        return self.lifecycle.fail_step(step_id, error_code=error_code, error_message=error_message)


class ScriptStateProxy:
    def __init__(self, store: Any, session_id: str, agent_id: str) -> None:
        self.store = store
        self.session_id = session_id
        self.agent_id = agent_id

    def get(self, key: str, default: Any = None) -> Any:
        if self.store is None:
            return default
        value = self.store.get_state(self.session_id, self.agent_id, key)
        return default if value is None else value

    def set(self, key: str, value: Any) -> Any:
        if self.store is None:
            return value
        return self.store.set_state(self.session_id, self.agent_id, key, value)


class CapabilityProxy:
    def __init__(self, runtime: Any, context: Optional[dict[str, Any]] = None) -> None:
        self.runtime = runtime
        self.context = context or {}

    def __getattr__(self, method_name: str):
        method = getattr(self.runtime, method_name)

        async def call(*args, **kwargs) -> CapabilityCallResult:
            try:
                if "context" not in kwargs:
                    parameters = inspect.signature(method).parameters
                    if "context" in parameters:
                        kwargs["context"] = self.context
                data = method(*args, **kwargs)
                if inspect.isawaitable(data):
                    data = await data
                return CapabilityCallResult(success=True, data=data)
            except Exception as exc:
                return CapabilityCallResult(success=False, error=str(exc) or "Capability call failed.")

        return call


class ScriptOutputProxy:
    def __init__(self, message_store: MessageStore, event_bus: EventBus, session_id: str, run_id: str, message_id: Optional[str], suppress_output: bool = False) -> None:
        self.message_store = message_store
        self.event_bus = event_bus
        self.session_id = session_id
        self.run_id = run_id
        self.message_id = message_id
        self.suppress_output = suppress_output
        self.completed = False
        self._content = ""
        self._seq = 0

    @property
    def has_content(self) -> bool:
        return bool(self._content)

    async def write_delta(self, text: str) -> None:
        if self.suppress_output:
            return
        if not text:
            return
        self._content += text
        self._seq += 1
        self.event_bus.emit(
            "message_delta",
            session_id=self.session_id,
            run_id=self.run_id,
            message_id=self.message_id,
            payload={"seq": self._seq, "delta": text, "reasoning_delta": None},
        )

    async def finish(
        self,
        final_content: Any = None,
        parts: Optional[list[dict[str, Any]]] = None,
        actions=None,
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        action_id: Optional[str] = None,
        parent_message_id: Optional[str] = None,
    ):
        if self.suppress_output:
            self.completed = True
            if final_content is not None:
                self._content = final_content if isinstance(final_content, str) else final_content
            return None
        resolved_parts = validate_message_parts(parts) if parts is not None else None
        if resolved_parts is None and final_content is not None:
            resolved_parts = capability_output_to_parts({"part_type": "text", "format": "plain"}, final_content)
        if self.completed:
            if final_content is None and actions is None and metadata is None:
                return self.message_store.get_message(self.message_id)
            message = self.message_store.add_message(
                session_id=self.session_id,
                role="agent",
                content="",
                agent_id=agent_id,
                action_id=action_id,
                run_id=self.run_id,
                content_version=2,
                parts=resolved_parts,
                parent_message_id=parent_message_id,
                available_actions=actions or [],
                metadata=metadata or {"success": True},
                speaker_type="agent",
                speaker_id=agent_id,
                speaker_name=None,
                origin="agent_reply",
            )
            self.event_bus.emit(
                "message_done",
                session_id=self.session_id,
                run_id=self.run_id,
                message_id=message.message_id,
                payload={"available_actions": message.available_actions},
            )
            return message
        if final_content is not None:
            self._content = final_content if isinstance(final_content, str) else final_content
        if resolved_parts is None:
            resolved_parts = capability_output_to_parts({"part_type": "text", "format": "plain"}, self._content)
        if not self.message_id:
            raise RuntimeError("Output message is not configured.")
        message = self.message_store.get_message(self.message_id)
        next_metadata = {**(message.metadata or {}), **(metadata or {}), "streaming": False, "placeholder": False}
        message = message.model_copy(
            update={
                "content_version": 2,
                "parts": resolved_parts,
                "available_actions": actions or message.available_actions,
                "metadata": next_metadata,
                "agent_id": agent_id or message.agent_id,
                "action_id": action_id or message.action_id,
                "parent_message_id": parent_message_id or message.parent_message_id,
            }
        )
        message = self.message_store.update_message(message)
        self.completed = True
        self._seq += 1
        self.event_bus.emit(
            "message_completed",
            session_id=self.session_id,
            run_id=self.run_id,
            message_id=message.message_id,
            payload={"seq": self._seq, "message": message.model_dump(mode="json"), "draft_message_id": message.message_id},
        )
        self.event_bus.emit(
            "message_done",
            session_id=self.session_id,
            run_id=self.run_id,
            message_id=message.message_id,
            payload={"available_actions": message.available_actions},
        )
        return message


class LLMProxy:
    def __init__(
        self,
        llm_runtime: Any,
        default_model_config: Optional[Dict[str, Any]] = None,
        provider_profile_store: Any = None,
        llm_profile_store: Any = None,
        default_llm_resolution: Optional[Dict[str, Any]] = None,
        output: Any = None,
        event_bus: EventBus = None,
        session_id: str = "",
        run_id: str = "",
        run_store: RunStore = None,
        run_lifecycle: RunLifecycle = None,
        parent_step_id: str = "",
        title_generation_context: Optional[Dict[str, Any]] = None,
        knowledge_context: Optional[Dict[str, Any]] = None,
        memory_context: Optional[Dict[str, Any]] = None,
        worldbook_context: Optional[Dict[str, Any]] = None,
        utility_llm_service: Any = None,
        agent_registry: Any = None,
        agent_config_store: Any = None,
        llm_defaults_store: Any = None,
        title_unload_callback: Any = None,
    ) -> None:
        self.llm_runtime = llm_runtime
        self.default_model_config = default_model_config or {}
        self.provider_profile_store = provider_profile_store
        self.llm_profile_store = llm_profile_store
        self.default_llm_resolution = default_llm_resolution or {}
        self.output = output
        self.event_bus = event_bus
        self.session_id = session_id
        self.run_id = run_id
        self.run_store = run_store
        self.run_lifecycle = run_lifecycle
        self.parent_step_id = parent_step_id
        self.used = False
        self.last_raw: Dict[str, Any] | None = None
        self._title_generation_context = title_generation_context or {}
        self._title_generation_checked = False
        self._knowledge_context = knowledge_context or {}
        self._memory_context = memory_context or {}
        self._worldbook_context = worldbook_context or {}
        self._utility_llm_service = utility_llm_service

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
        await self._maybe_generate_session_title()
        self.used = True
        from ai_workbench.core.context import validate_llm_context_messages

        context_already_injected = bool(options.pop("_runtime_context_injected", False) or options.pop("_knowledge_injected", False))
        messages = messages if context_already_injected else self._inject_runtime_context(messages)
        messages = validate_llm_context_messages(messages)
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
        if isinstance(data, dict):
            self.last_raw = data
            try:
                from ai_workbench.core.runner import _extract_content

                return _extract_content(data)
            except Exception:
                return str(data)
        return str(data)

    async def stream(
        self,
        system: Optional[str] = None,
        user: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Any] = None,
        **options,
    ):
        await self._maybe_generate_session_title()
        self.used = True
        resolved_messages = _resolve_llm_messages(system=system, user=user, messages=messages)
        from ai_workbench.core.context import validate_llm_context_messages

        resolved_messages = self._inject_runtime_context(resolved_messages)
        resolved_messages = validate_llm_context_messages(resolved_messages)
        model_config = options.pop("model_config", None) or self.default_model_config
        if response_format is not None:
            options["response_format"] = response_format
        if model_config.get("supports_streaming") is False:
            text = await self.chat(messages=resolved_messages, model_config=model_config, _runtime_context_injected=True, **options)
            yield ScriptLLMStreamChunk(text=text, raw=None, model=_model_from_config(model_config))
            return
        try:
            from ai_workbench.core.runner import _call_chat_stream, _normalize_stream_chunk
            from ai_workbench.core.runner import _merge_stream_metadata

            async for chunk in _call_chat_stream(self.llm_runtime, resolved_messages, model_config):
                normalized = _normalize_stream_chunk(chunk)
                if normalized.raw:
                    self.last_raw = _merge_stream_metadata(self.last_raw, normalized.raw)
                yield ScriptLLMStreamChunk(
                    text=normalized.content_delta or "",
                    raw=normalized.raw,
                    finish_reason=normalized.finish_reason,
                    model=_model_from_config(model_config),
                )
        except Exception:
            raise

    async def stream_to_output(
        self,
        system: Optional[str] = None,
        user: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        format: str = "markdown",
        **options,
    ) -> str:
        if self.output is None:
            raise RuntimeError("Output streaming is not configured.")
        parts: list[str] = []
        async for chunk in self.stream(system=system, user=user, messages=messages, **options):
            if not chunk.text:
                continue
            parts.append(chunk.text)
            await self.output.write_delta(chunk.text)
        text = "".join(parts)
        await self.output.finish(parts=[make_text_part(text, format="markdown" if format == "markdown" else "plain")], metadata=self.message_metadata())
        self.record_run_llm_metadata()
        return text

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
                    await self._maybe_generate_session_title()
                    self.used = True
                    context_prompt = self._runtime_context_block_for_generate_prompt()
                    if context_prompt:
                        resolved_prompt = f"{context_prompt}\n\n{resolved_prompt}" if resolved_prompt else context_prompt
                    data = generate(
                        prompt=resolved_prompt,
                        model_config=model_config or self.default_model_config,
                        stream=options.pop("stream", False),
                        **options,
                    )
                    if inspect.isawaitable(data):
                        data = await data
                    if isinstance(data, dict):
                        self.last_raw = data
                else:
                    data = await self.chat(
                        messages=[{"role": "user", "content": resolved_prompt}],
                        model_config=model_config,
                        **options,
                    )
            self.record_run_llm_metadata()
            return CapabilityCallResult(success=True, data=data)
        except Exception as exc:
            return CapabilityCallResult(success=False, error=str(exc) or "LLM generate failed.")

    def _inject_runtime_context(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        messages = self._inject_core_memory(messages)
        messages = self._inject_worldbook(messages)
        return self._inject_knowledge(messages)

    def _inject_core_memory(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        context = self._memory_context
        if not context:
            return messages
        result = build_core_memory_context(
            app_settings_store=context.get("app_settings_store"),
            source="script_agent",
        )
        self._record_named_context("core_memory_context", result.metadata, context_metadata_for_step(result.metadata))
        if result.rendered_text:
            return append_system_context(messages, result.rendered_text)
        return messages

    def _inject_worldbook(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        context = self._worldbook_context
        if not context:
            return messages
        result = build_session_worldbook_context(
            worldbook_store=context.get("worldbook_store"),
            session_id=context.get("session_id") or self.session_id,
            user_text=context.get("user_text") or "",
            source="script_agent",
        )
        self._record_named_context("worldbook_context", result.metadata, worldbook_step_metadata(result.metadata))
        if result.rendered_text:
            return append_system_context(messages, result.rendered_text)
        return messages

    def _inject_knowledge(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        context = self._knowledge_context
        if not context:
            return messages
        result = build_session_knowledge_context(
            knowledge_store=context.get("knowledge_store"),
            model_backend=context.get("knowledge_model_backend"),
            query=context.get("query") or "",
            session_id=context.get("session_id") or self.session_id,
            source="script_agent",
            effective_mode=context.get("effective_mode") or "disabled",
            llm_runtime=self.llm_runtime,
            llm_model_config=self.default_model_config,
        )
        self._record_knowledge_context(result.metadata)
        if result.rendered_text:
            return append_knowledge_to_system(messages, result.rendered_text)
        return messages

    def _runtime_context_block_for_generate_prompt(self) -> str:
        blocks: list[str] = []
        memory_context = self._memory_context
        if memory_context:
            result = build_core_memory_context(
                app_settings_store=memory_context.get("app_settings_store"),
                source="script_agent",
            )
            self._record_named_context("core_memory_context", result.metadata, context_metadata_for_step(result.metadata))
            if result.rendered_text:
                blocks.append(result.rendered_text)
        worldbook_context = self._worldbook_context
        if worldbook_context:
            result = build_session_worldbook_context(
                worldbook_store=worldbook_context.get("worldbook_store"),
                session_id=worldbook_context.get("session_id") or self.session_id,
                user_text=worldbook_context.get("user_text") or "",
                source="script_agent",
            )
            self._record_named_context("worldbook_context", result.metadata, worldbook_step_metadata(result.metadata))
            if result.rendered_text:
                blocks.append(result.rendered_text)
        knowledge_block = self._knowledge_block_for_generate_prompt()
        if knowledge_block:
            blocks.append(knowledge_block)
        return "\n\n".join(blocks)

    def _knowledge_block_for_generate_prompt(self) -> str:
        context = self._knowledge_context
        if not context:
            return ""
        result = build_session_knowledge_context(
            knowledge_store=context.get("knowledge_store"),
            model_backend=context.get("knowledge_model_backend"),
            query=context.get("query") or "",
            session_id=context.get("session_id") or self.session_id,
            source="script_agent",
            effective_mode=context.get("effective_mode") or "disabled",
            llm_runtime=self.llm_runtime,
            llm_model_config=self.default_model_config,
        )
        self._record_knowledge_context(result.metadata)
        return result.rendered_text

    def _record_knowledge_context(self, knowledge_context: dict[str, Any]) -> None:
        self._record_named_context("knowledge_context", knowledge_context, knowledge_step_metadata(knowledge_context))

    def _record_named_context(self, key: str, context_metadata: dict[str, Any], step_metadata_item: dict[str, Any]) -> None:
        if self.run_store is None or not self.run_id:
            return
        metadata = dict(self.run_store.get_run(self.run_id).metadata)
        metadata[key] = context_metadata
        warnings = context_metadata.get("warnings") if isinstance(context_metadata, dict) else None
        if warnings:
            existing = list(metadata.get("warnings", []))
            existing.extend(str(item) for item in warnings)
            metadata["warnings"] = existing
        self.run_store.update_metadata(self.run_id, metadata)
        self._record_context_step_metadata(key, step_metadata_item)

    def _record_context_step_metadata(self, key: str, compact: dict[str, Any]) -> None:
        if self.run_lifecycle is None or not self.parent_step_id:
            return
        if not compact:
            return
        step = self.run_store.get_step(self.parent_step_id)
        step_metadata = dict(step.metadata or {})
        contexts_key = f"{key}s"
        contexts = list(step_metadata.get(contexts_key) or [])
        contexts.append(compact)
        step_metadata[contexts_key] = contexts
        updated = self.run_store.update_step(self.parent_step_id, metadata=step_metadata)
        self.run_lifecycle._emit_step("run_step_updated", updated)

    async def _maybe_generate_session_title(self) -> None:
        if self._title_generation_checked:
            return
        self._title_generation_checked = True
        context = self._title_generation_context
        if not context:
            return
        await maybe_generate_session_title_before_llm_call(
            session_id=context.get("session_id") or self.session_id,
            source_message_id=context.get("source_message_id") or "",
            fallback_user_text=context.get("fallback_user_text") or "",
            run_id=self.run_id,
            session_store=context.get("session_store"),
            message_store=context.get("message_store"),
            run_store=self.run_store,
            event_bus=self.event_bus,
            llm_runtime=self.llm_runtime,
            llm_model_config=self.default_model_config,
            llm_resolution=self.default_llm_resolution,
            app_settings_store=context.get("app_settings_store"),
            utility_llm_service=self._utility_llm_service or context.get("utility_llm_service"),
            agent_registry=context.get("agent_registry"),
            agent_config_store=context.get("agent_config_store"),
            llm_profile_store=self.llm_profile_store,
            provider_profile_store=self.provider_profile_store,
            capability_registry=context.get("capability_registry"),
            capability_config_store=context.get("capability_config_store"),
            llm_defaults_store=context.get("llm_defaults_store"),
            invoked_agent_id=context.get("invoked_agent_id") or "",
            invoked_action_id=context.get("invoked_action_id") or "",
            unload_model_callback=context.get("unload_model_callback"),
            current_response_llm_resolution=self.default_llm_resolution,
        )

    async def unload(self, model_config: Optional[Dict[str, Any]] = None) -> CapabilityCallResult:
        try:
            unload = getattr(self.llm_runtime, "unload", None)
            if callable(unload):
                data = unload(model_config=model_config or self.default_model_config)
                if inspect.isawaitable(data):
                    data = await data
            else:
                data = {"success": False, "unsupported": True, "message": "LLM runtime does not support unload."}
            self._refresh_provider_status_after_unload(data)
            self._record_unload_result(data, legacy=True)
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
                _enrich_script_unload_result(data, self.default_llm_resolution, self.default_model_config)
                self._refresh_provider_status_after_unload(data)
            self._record_unload_result(data)
            return CapabilityCallResult(success=bool(data.get("ok")), data=data, error=_first_unload_error(data))
        except Exception as exc:
            return CapabilityCallResult(
                success=False,
                data={"ok": False, "unloaded": [], "errors": [{"code": "MODEL_UNLOAD_FAILED", "message": str(exc) or "Model unload failed."}]},
                error=str(exc) or "Model unload failed.",
            )

    def message_metadata(self) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        if self.run_store is not None and self.run_id:
            knowledge_context = self.run_store.get_run(self.run_id).metadata.get("knowledge_context")
            if isinstance(knowledge_context, dict) and knowledge_context.get("snippet_refs"):
                metadata["knowledge_context"] = knowledge_context
        if not self.default_llm_resolution:
            return metadata
        try:
            from ai_workbench.core.runner import _llm_message_metadata

            llm_config = SimpleNamespace(values=self.default_model_config, metadata=_resolution_as_config_metadata(self.default_llm_resolution))
            metadata.update({"llm_resolution": self.default_llm_resolution, "llm": _llm_message_metadata(llm_config, self.last_raw)})
            return metadata
        except Exception:
            return {**metadata, "llm_resolution": self.default_llm_resolution}

    def record_run_llm_metadata(self) -> None:
        if self.run_store is None or not self.run_id or not self.default_llm_resolution:
            return
        metadata = dict(self.run_store.get_run(self.run_id).metadata)
        metadata.update(self.message_metadata())
        self.run_store.update_metadata(self.run_id, metadata)

    def _record_unload_result(self, data: Dict[str, Any], legacy: bool = False) -> None:
        if self.run_store is None or not self.run_id:
            return
        try:
            from ai_workbench.core.runner import _llm_unload_message

            result = data if not legacy else _legacy_unload_result(data, self.default_llm_resolution, self.default_model_config)
            run = self.run_store.get_run(self.run_id)
            metadata = dict(run.metadata)
            status_refresh = result.get("status_refresh") if isinstance(result.get("status_refresh"), dict) else {}
            metadata["llm_unload"] = {
                "policy": "script",
                "attempted": not bool(result.get("skipped")),
                "ok": bool(result.get("ok")),
                "status_refresh_attempted": bool(status_refresh.get("attempted")),
                "status_refresh_ok": bool(status_refresh.get("ok")),
                "status_refresh_error": status_refresh.get("error"),
                "provider": result.get("provider"),
                "provider_profile_id": result.get("provider_profile_id"),
                "provider_profile_name": result.get("provider_profile_name"),
                "model_profile_id": result.get("model_profile_id"),
                "model_profile_name": result.get("model_profile_name"),
                "requested_model_id": result.get("requested_model_id") or result.get("model_id"),
                "actual_model_id": result.get("actual_model_id"),
                "model_id": result.get("model_id"),
                "unloaded_count": len(result.get("unloaded") or []),
                "skipped": bool(result.get("skipped")),
                "skip_reason": result.get("skip_reason"),
                "code": result.get("code"),
                "errors": result.get("errors") or [],
                "result": result,
            }
            self.run_store.update_metadata(self.run_id, metadata)
            message = _llm_unload_message(result)
            if message and self.run_lifecycle is not None:
                step = self.run_lifecycle.start_step(self.run_id, "Unload model", parent_step_id=self.parent_step_id, metadata={"llm_unload": result})
                self.run_lifecycle.complete_step(step.step_id, message=message, metadata={"llm_unload": result})
        except Exception:
            return

    def _refresh_provider_status_after_unload(self, data: Dict[str, Any]) -> None:
        provider_profile_id = str(
            data.get("provider_profile_id")
            or self.default_llm_resolution.get("provider_profile_id")
            or self.default_model_config.get("provider_profile_id")
            or ""
        )
        status_refresh = {
            "attempted": False,
            "ok": False,
            "provider_profile_id": provider_profile_id,
        }
        data["status_refresh"] = status_refresh
        if not provider_profile_id or self.provider_profile_store is None or self.llm_profile_store is None:
            status_refresh["error"] = "Provider stores are not available."
            return
        try:
            status = refresh_provider_status_for_profile(self.provider_profile_store, self.llm_profile_store, provider_profile_id)
            status_refresh.update({"attempted": True, "ok": True, "status": status})
            if self.event_bus is not None and self.session_id:
                self.event_bus.emit(
                    "llm_provider_status_updated",
                    session_id=self.session_id,
                    run_id=self.run_id or None,
                    payload={"provider": status},
                )
        except Exception as exc:
            status_refresh.update({"attempted": True, "ok": False, "error": str(exc) or "Provider status refresh failed."})


class AgentContext:
    def __init__(
        self,
        agent: AgentSchema,
        action_id: str,
        session: Session,
        run_id: str,
        input_text: str,
        source_message_id: Optional[str],
        form_id: Optional[str],
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
        output_message_id: Optional[str] = None,
        current_parent_step_id: Optional[str] = None,
        input_message_id: Optional[str] = None,
        app_settings_store: Any = None,
        capability_registry: CapabilityRegistry = None,
        capability_config_store: Any = None,
        session_agent_state_store: Any = None,
        is_silent_submission: bool = False,
        suppress_output: bool = False,
        agent_registry: Any = None,
        agent_config_store: Any = None,
        llm_defaults_store: Any = None,
        title_unload_callback: Any = None,
        knowledge_context: Optional[Dict[str, Any]] = None,
        memory_context: Optional[Dict[str, Any]] = None,
        worldbook_context: Optional[Dict[str, Any]] = None,
        utility_llm_service: Any = None,
    ) -> None:
        self.agent = agent
        self.action_id = action_id
        self.run_id = run_id
        self.input = ScriptInput(
            text=input_text,
            action_id=action_id,
            form_id=form_id,
            is_silent_submission=is_silent_submission,
            source_message_id=source_message_id,
            prefill=prefill or {},
            attachments=list(attachments or []),
        )
        self.session = ScriptSession(session_id=session.session_id, default_agent_id=session.default_agent_id, context_mode=session.context_mode)
        self.config = config or {}
        self.run_store = run_store
        self.message_store = message_store
        self.session_store = session_store
        self.event_bus = event_bus
        self.runtime_registry = runtime_registry
        self.capability_registry = capability_registry
        self.capability_config_store = capability_config_store
        self.state = ScriptStateProxy(session_agent_state_store, session.session_id, agent.id)
        self.output = ScriptOutputProxy(
            message_store=message_store,
            event_bus=event_bus,
            session_id=session.session_id,
            run_id=run_id,
            message_id=output_message_id,
            suppress_output=suppress_output,
        )
        self.llm = LLMProxy(
            llm_runtime,
            default_model_config=llm_model_config,
            provider_profile_store=provider_profile_store,
            llm_profile_store=llm_profile_store,
            default_llm_resolution=llm_resolution,
            output=self.output,
            event_bus=event_bus,
            session_id=session.session_id,
            run_id=run_id,
            run_store=run_store,
            run_lifecycle=run_lifecycle,
            parent_step_id=current_parent_step_id or "",
            title_generation_context={
                "session_id": session.session_id,
                "source_message_id": input_message_id or "",
                "fallback_user_text": input_text,
                "session_store": session_store,
                "message_store": message_store,
                "app_settings_store": app_settings_store,
                "utility_llm_service": utility_llm_service,
                "agent_registry": agent_registry,
                "agent_config_store": agent_config_store,
                "capability_registry": capability_registry,
                "capability_config_store": capability_config_store,
                "llm_defaults_store": llm_defaults_store,
                "invoked_agent_id": agent.id,
                "invoked_action_id": action_id,
                "unload_model_callback": title_unload_callback,
            },
            knowledge_context=knowledge_context,
            memory_context=memory_context,
            worldbook_context=worldbook_context,
            utility_llm_service=utility_llm_service,
        )
        self.llm_resolution = llm_resolution or {}
        self.parent_message_id = parent_message_id
        self.waiting = False
        self.current_parent_step_id = current_parent_step_id
        self.run = ScriptRunLifecycleProxy(run_lifecycle, run_id, default_parent_step_id=current_parent_step_id) if run_lifecycle is not None else None

    async def reply(self, content: Any, type: str = "text", actions=None, metadata: Optional[Dict[str, Any]] = None):
        declaration = _reply_type_to_output(type)
        parts = capability_output_to_parts(declaration, content)
        return await self.reply_parts(parts, actions=actions, metadata=metadata)

    async def reply_parts(self, parts: list[dict[str, Any]], actions=None, metadata: Optional[Dict[str, Any]] = None):
        message_parts = validate_message_parts(parts)
        message_metadata = {"success": True, **self.llm.message_metadata(), **(metadata or {})}
        self.llm.record_run_llm_metadata()
        message = await self.output.finish(
            final_content=None,
            parts=message_parts,
            actions=actions or [],
            metadata=message_metadata,
            agent_id=self.agent.id,
            action_id=self.action_id,
            parent_message_id=self.parent_message_id,
        )
        return message

    async def reply_text(self, text: str, actions=None, metadata: Optional[Dict[str, Any]] = None):
        return await self.reply_parts([make_text_part(text, format="plain")], actions=actions, metadata=metadata)

    async def reply_markdown(self, markdown: str, actions=None, metadata: Optional[Dict[str, Any]] = None):
        return await self.reply_parts([make_text_part(markdown, format="markdown")], actions=actions, metadata=metadata)

    async def reply_json(self, data: dict | list, actions=None, metadata: Optional[Dict[str, Any]] = None):
        return await self.reply_parts([make_json_part(data)], actions=actions, metadata=metadata)

    async def reply_image(self, url: str, alt: str = None, title: str = None, caption: str = None, actions=None, metadata: Optional[Dict[str, Any]] = None):
        return await self.reply_parts([make_image_part(url=url, alt=alt, title=title, caption=caption)], actions=actions, metadata=metadata)

    async def reply_images(self, images: list, actions=None, metadata: Optional[Dict[str, Any]] = None):
        items = [{"type": "image", **dict(image)} for image in images]
        return await self.reply_parts([make_media_group_part(items)], actions=actions, metadata=metadata)

    async def reply_file_content(
        self,
        content: str,
        filename: str = None,
        language: str = None,
        mime_type: str = None,
        size: int = None,
        truncated: bool = False,
        actions=None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        part = make_file_part(
            content,
            filename=filename,
            language=language,
            mime_type=mime_type,
            size=size,
            truncated=truncated,
        )
        return await self.reply_parts([part], actions=actions, metadata=metadata)

    async def reply_blocks(self, blocks: list, actions=None, metadata: Optional[Dict[str, Any]] = None):
        return await self.reply_parts(blocks_to_parts(blocks), actions=actions, metadata=metadata)

    async def reply_form(self, form: dict, title: str = None, actions=None, metadata: Optional[Dict[str, Any]] = None):
        block = dict(form or {})
        if title is not None:
            block["title"] = title
        block = validate_action_form_block(block)
        return await self.reply_blocks([block], actions=actions, metadata=metadata)

    async def reply_action_form(self, form: dict, actions=None, metadata: Optional[Dict[str, Any]] = None):
        return await self.reply_form(form, actions=actions, metadata=metadata)

    def read_attachment_bytes(self, attachment: dict[str, Any] | str) -> bytes:
        return read_attachment_bytes(self._attachment_for_read(attachment))

    def read_attachment_text(self, attachment: dict[str, Any] | str) -> dict[str, Any]:
        return read_attachment_text(self._attachment_for_read(attachment))

    def attachment_as_data_url(self, attachment: dict[str, Any] | str) -> str:
        return read_attachment_as_data_url(self._attachment_for_read(attachment))

    async def save_attachment_bytes(
        self,
        data: bytes,
        filename: str,
        mime_type: str,
        kind: str = "file",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attachment = save_generated_attachment_bytes(
            data=data,
            filename=filename,
            mime_type=mime_type,
            kind=kind,
            metadata=metadata,
        )
        self._link_generated_attachment(attachment)
        return attachment

    async def save_attachment_base64(
        self,
        data_base64: str,
        filename: str,
        mime_type: str,
        kind: str = "file",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attachment = save_generated_attachment_base64(
            data_base64=data_base64,
            filename=filename,
            mime_type=mime_type,
            kind=kind,
            metadata=metadata,
        )
        self._link_generated_attachment(attachment)
        return attachment

    def _attachment_for_read(self, attachment: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(attachment, dict):
            return attachment
        for item in self.input.attachments:
            if item.get("id") == attachment:
                return item
        raise ValueError(f"Attachment not found: {attachment}")

    def _link_generated_attachment(self, attachment: dict[str, Any]) -> None:
        message_id = self.output.message_id
        if message_id:
            message = self.message_store.get_message(message_id)
            metadata = dict(message.metadata or {})
            attachments = list(metadata.get("attachments") or [])
            attachments.append(attachment)
            metadata["attachments"] = attachments
            metadata["generated_attachments"] = attachments
            self.message_store.update_message(message.model_copy(update={"metadata": metadata}))
        run = self.run_store.get_run(self.run_id)
        run_metadata = dict(run.metadata or {})
        generated = list(run_metadata.get("generated_attachments") or [])
        generated.append(attachment)
        run_metadata["generated_attachments"] = generated
        self.run_store.update_metadata(self.run_id, run_metadata)

    def step(self, name: str, parent_step_id: Optional[str] = None) -> ScriptStep:
        if self.run is None:
            raise RuntimeError("Run lifecycle is not configured.")
        return ScriptStep(self, name, parent_step_id=parent_step_id)

    def capability(self, name: str) -> CapabilityProxy:
        return CapabilityProxy(self.runtime_registry.get_runtime(name), context=self._capability_context(name))

    def _capability_context(self, capability_id: str) -> dict[str, Any]:
        capability_config = {}
        if self.capability_registry is not None and self.capability_config_store is not None:
            try:
                capability = self.capability_registry.get(capability_id)
                stored = self.capability_config_store.get_config(capability_id)
                capability_config = resolve_config(capability.config_schema, stored.get("user_config") or {})
            except Exception:
                capability_config = {}
        return {
            "session_id": self.session.session_id,
            "capability_id": capability_id,
            "capability_config": capability_config,
            "attachments": list(self.input.attachments or []),
        }

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
        session_agent_state_store=None,
        app_settings_store=None,
        run_lifecycle: RunLifecycle = None,
        knowledge_store=None,
        knowledge_model_backend=None,
        worldbook_store=None,
        utility_llm_service=None,
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
        self.session_agent_state_store = session_agent_state_store
        self.app_settings_store = app_settings_store
        self.run_lifecycle = run_lifecycle or RunLifecycle(run_store, event_bus)
        self.knowledge_store = knowledge_store
        self.knowledge_model_backend = knowledge_model_backend
        self.worldbook_store = worldbook_store
        self.utility_llm_service = utility_llm_service

    async def run(
        self,
        agent: AgentSchema,
        action_id: str,
        args: str,
        session_id: str,
        source_message_id: str = "",
        parent_message_id: str = "",
        prefill=None,
        form_id: str = "",
        input_message_id: str = "",
        create_user_message: bool = True,
        display_input: str = "",
        attachments: list[dict] = None,
        suppress_output: bool = False,
        is_silent_submission: bool = False,
        invocation_route_kind: str = "agent",
        intent_routing_metadata: dict[str, Any] | None = None,
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
                        "route_kind": invocation_route_kind,
                        "agent_id": agent.id,
                        "action_id": action_id,
                        "raw_text": raw_text,
                        "args": args,
                        "resolved_agent_id": agent.id,
                        "resolved_action_id": action_id,
                    },
                },
                speaker_type="user",
                speaker_id="local_user",
                speaker_name="User",
                origin="user_message",
            )
        parent_id = parent_message_id or source_message_id or (user_message.message_id if user_message is not None else "")
        run_metadata = {
            "args": args,
            "input_message_id": user_message.message_id if user_message is not None else None,
            "parent_message_id": parent_id or None,
            "source_message_id": source_message_id or None,
            "prefill": prefill or {},
            "form_id": form_id or None,
            "silent": bool(suppress_output),
            "route_kind": invocation_route_kind,
            "resolved_agent_id": agent.id,
            "resolved_action_id": action_id,
        }
        if intent_routing_metadata is not None:
            run_metadata["intent_routing"] = intent_routing_metadata
        run = self.run_store.create_run(
            kind="agent" if action_id == "default" else "action",
            target_id=agent.id,
            action_id=action_id,
            session_id=session_id,
            metadata=run_metadata,
        )
        output_message = None
        if not suppress_output:
            output_message = self.message_store.add_message(
                session_id=session_id,
                role="assistant",
                content="",
                agent_id=agent.id,
                action_id=action_id,
                run_id=run.run_id,
                content_version=2,
                parts=[],
                parent_message_id=parent_id or None,
                metadata={"success": True, "streaming": True, "placeholder": True},
                speaker_type="agent",
                speaker_id=agent.id,
                speaker_name=agent.name,
                origin="agent_reply",
            )
            run = self.run_store.update_metadata(run.run_id, {**run.metadata, "message_id": output_message.message_id})
            self.event_bus.emit(
                "message_started",
                session_id=session_id,
                run_id=run.run_id,
                message_id=output_message.message_id,
                payload={
                    "message_id": output_message.message_id,
                    "role": "assistant",
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "action_id": action_id,
                    "parent_message_id": parent_id or None,
                    "created_at": isoformat_utc(output_message.created_at),
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
                if agent.id == "comfyui_agent":
                    metadata = dict(self.run_store.get_run(run.run_id).metadata or {})
                    metadata["comfyui_prompt_enhancer_error"] = {
                        "code": "COMFYUI_PROMPT_ENHANCER_FAILED",
                        "inner_code": exc.code,
                        "inner_message": exc.message,
                        "stage": "resolve_llm",
                        "agent_id": agent.id,
                        "action_id": action_id,
                        "llm_profile_id": None,
                        "provider_profile_id": None,
                        "provider": None,
                        "model_id": None,
                        "reached_provider": False,
                    }
                    self.run_store.update_metadata(run.run_id, metadata)
                self.run_lifecycle.fail_step(model_step.step_id, error_code=exc.code, error_message=exc.message)
                return self._fail(run.run_id, session_id, exc.message, error_code=exc.code)
            self.run_lifecycle.complete_step(model_step.step_id)
        else:
            try:
                llm_config = self._resolve_llm_model_config(agent, session_id)
            except LLMConfigError:
                llm_config = None

        starting_step = self.run_lifecycle.start_step(run.run_id, "Starting script")
        self.run_lifecycle.complete_step(starting_step.step_id)
        running_step = self.run_lifecycle.start_step(run.run_id, "Running script")

        agent_user_config = {}
        if self.agent_config_store is not None:
            try:
                agent_user_config = resolve_config(agent.config_schema, agent_config.get("user_config") or {})
            except Exception:
                agent_user_config = agent_config.get("user_config") or {}
        runtime_context_text = "" if is_silent_submission else self._knowledge_query(args, user_message, input_message_id)

        ctx = AgentContext(
            agent=agent,
            action_id=action_id,
            session=session,
            run_id=run.run_id,
            input_text=args,
            source_message_id=source_message_id or None,
            form_id=form_id or None,
            parent_message_id=parent_id,
            prefill=prefill or {},
            config=agent_user_config,
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
            output_message_id=output_message.message_id if output_message is not None else None,
            current_parent_step_id=running_step.step_id,
            input_message_id=user_message.message_id if user_message is not None else input_message_id,
            app_settings_store=self.app_settings_store,
            capability_registry=self.capability_registry,
            capability_config_store=self.capability_config_store,
            session_agent_state_store=self.session_agent_state_store,
            is_silent_submission=is_silent_submission,
            suppress_output=suppress_output,
            agent_registry=self.agent_registry,
            agent_config_store=self.agent_config_store,
            llm_defaults_store=self.llm_defaults_store,
            title_unload_callback=self._unload_model_for_title_generation,
            knowledge_context={
                "knowledge_store": self.knowledge_store,
                "knowledge_model_backend": self.knowledge_model_backend,
                "session_id": session_id,
                "query": runtime_context_text,
                "effective_mode": str(resolved_knowledge_context_mode(agent, agent_config)["effective_mode"]),
            },
            memory_context={"app_settings_store": self.app_settings_store},
            worldbook_context={
                "worldbook_store": self.worldbook_store,
                "session_id": session_id,
                "user_text": runtime_context_text,
            },
            utility_llm_service=self.utility_llm_service,
        )

        try:
            script_result = await script_run(ctx)
        except Exception as exc:
            self.run_lifecycle.fail_step(running_step.step_id, error_message=str(exc) or "Script agent failed.")
            if ctx.output.has_content:
                final_content = None
                parts = None
            else:
                final_content = {"code": "RUN_FAILED", "message": str(exc) or "Script agent failed."}
                parts = [make_error_part(str(exc) or "Script agent failed.", code="RUN_FAILED")]
            await ctx.output.finish(
                final_content=final_content,
                parts=parts,
                metadata={"success": False, "error": str(exc) or "Script agent failed."},
                agent_id=agent.id,
                action_id=action_id,
                parent_message_id=parent_id,
            )
            result = self._fail(run.run_id, session_id, str(exc) or "Script agent failed.")
            self._apply_model_lifecycle(ctx, lifecycle)
            apply_deferred_title_model_unload(self.run_store, run.run_id, self._unload_model_for_title_generation, self.session_store)
            return result
        self.run_lifecycle.complete_step(running_step.step_id)

        final_run = self.run_store.get_run(run.run_id)
        if final_run.status == RunStatus.WAITING_FOR_USER:
            return RunResult(success=False, run_id=run.run_id, error="Waiting for user input.")

        saving_step = self.run_lifecycle.start_step(run.run_id, "Saving response")
        if not ctx.output.completed:
            await ctx.output.finish(
                final_content="" if script_result is None else script_result,
                metadata={"success": True, **ctx.llm.message_metadata()},
                agent_id=agent.id,
                action_id=action_id,
                parent_message_id=parent_id,
            )
        self.run_lifecycle.complete_step(saving_step.step_id)
        cleanup_step = self.run_lifecycle.start_step(run.run_id, "Cleanup")
        unload_result = self._apply_model_lifecycle(ctx, lifecycle)
        apply_deferred_title_model_unload(self.run_store, run.run_id, self._unload_model_for_title_generation, self.session_store)
        from ai_workbench.core.runner import _llm_unload_message

        unload_message = _llm_unload_message(unload_result) if unload_result else None
        self.run_lifecycle.complete_step(cleanup_step.step_id, message=unload_message, metadata={"llm_unload": unload_result} if unload_message else None)
        done_run = self.run_lifecycle.complete_run(run.run_id)
        self.event_bus.emit("run_done", session_id=session_id, run_id=done_run.run_id)
        result_data = script_result if isinstance(script_result, dict) else None
        return RunResult(success=True, run_id=done_run.run_id, data=result_data)

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
        session_llm_profile_id = self.session_store.get_session(session_id).llm_profile_id
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

    def _knowledge_query(self, args: str, user_message: Any = None, input_message_id: str = "") -> str:
        text = str(args or "").strip()
        if text:
            return text
        message = user_message
        if message is None and input_message_id:
            try:
                message = self.message_store.get_message(input_message_id)
            except KeyError:
                message = None
        from ai_workbench.core.message_parts import text_from_parts

        return text_from_parts(getattr(message, "parts", None)) if message is not None else ""

    def _fail(self, run_id: str, session_id: str, error: str, error_code: str = None) -> RunResult:
        failed_run = self.run_lifecycle.fail_run(run_id, error_code, error)
        self._persist_failed_output_message(run_id, session_id, error, error_code or "RUN_FAILED")
        return RunResult(success=False, run_id=failed_run.run_id, error=error, error_code=error_code)

    def _persist_failed_output_message(self, run_id: str, session_id: str, error: str, error_code: str) -> None:
        try:
            run = self.run_store.get_run(run_id)
        except KeyError:
            return
        message_id = (run.metadata or {}).get("message_id")
        if not message_id:
            return
        try:
            message = self.message_store.get_message(str(message_id))
        except KeyError:
            return
        if (message.metadata or {}).get("placeholder") is not True:
            return
        metadata = {
            **(message.metadata or {}),
            "success": False,
            "streaming": False,
            "placeholder": False,
            "error": {"code": error_code, "message": error},
        }
        updated = message.model_copy(
            update={
                "content_version": 2,
                "parts": [make_error_part(error, code=error_code)],
                "metadata": metadata,
            }
        )
        updated = self.message_store.update_message(updated)
        self.event_bus.emit(
            "message_completed",
            session_id=session_id,
            run_id=run_id,
            message_id=updated.message_id,
            payload={"seq": 1, "message": updated.model_dump(mode="json"), "draft_message_id": updated.message_id},
        )
        self.event_bus.emit(
            "message_done",
            session_id=session_id,
            run_id=run_id,
            message_id=updated.message_id,
            payload={"available_actions": updated.available_actions},
        )

    def _apply_model_lifecycle(self, ctx: AgentContext, lifecycle) -> dict | None:
        if lifecycle.unload != "after_run" or not ctx.llm.used:
            return None
        result = unload_model_for_profile(
            provider_profile_store=self.provider_profile_store,
            llm_profile_store=self.llm_profile_store,
            provider_profile_id=ctx.llm_resolution.get("provider_profile_id"),
            model_profile_id=ctx.llm_resolution.get("profile_id"),
            model_id=ctx.llm_resolution.get("model_id") or ctx.llm.default_model_config.get("model_id") or ctx.llm.default_model_config.get("model"),
            reason="after_run",
        )
        _enrich_script_unload_result(result, ctx.llm_resolution, ctx.llm.default_model_config)
        ctx.llm._refresh_provider_status_after_unload(result)
        run = self.run_store.get_run(ctx.run_id)
        metadata = dict(run.metadata)
        status_refresh = result.get("status_refresh") if isinstance(result.get("status_refresh"), dict) else {}
        metadata["llm_unload"] = {
            "policy": lifecycle.unload,
            "attempted": not bool(result.get("skipped")),
            "ok": bool(result.get("ok")),
            "status_refresh_attempted": bool(status_refresh.get("attempted")),
            "status_refresh_ok": bool(status_refresh.get("ok")),
            "status_refresh_error": status_refresh.get("error"),
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
        return result

    def _unload_model_for_title_generation(
        self,
        provider_profile_id: str | None = None,
        model_profile_id: str | None = None,
        model_id: str | None = None,
        reason: str = "session_title_generation",
    ) -> dict:
        if self.provider_profile_store is None or self.llm_profile_store is None:
            return {
                "ok": False,
                "code": "MODEL_UNLOAD_UNSUPPORTED",
                "provider_profile_id": provider_profile_id or "",
                "model_profile_id": model_profile_id,
                "model_id": model_id or "",
                "unloaded": [],
                "skipped": False,
                "skip_reason": None,
                "errors": [{"code": "MODEL_UNLOAD_UNSUPPORTED", "message": "Provider stores are not available."}],
                "reason": reason,
            }
        result = unload_model_for_profile(
            provider_profile_store=self.provider_profile_store,
            llm_profile_store=self.llm_profile_store,
            provider_profile_id=provider_profile_id,
            model_profile_id=model_profile_id,
            model_id=model_id,
            reason=reason,
        )
        provider_id = str(result.get("provider_profile_id") or provider_profile_id or "")
        if provider_id:
            try:
                status = refresh_provider_status_for_profile(self.provider_profile_store, self.llm_profile_store, provider_id)
                result["status_refresh"] = {"attempted": True, "ok": True, "provider_profile_id": provider_id, "status": status}
            except Exception as exc:
                result["status_refresh"] = {"attempted": True, "ok": False, "provider_profile_id": provider_id, "error": str(exc)}
        return result


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


def _reply_type_to_output(reply_type: str) -> dict[str, Any]:
    kind = (reply_type or "text").strip()
    if kind == "markdown":
        return {"part_type": "text", "format": "markdown"}
    if kind == "text":
        return {"part_type": "text", "format": "plain"}
    if kind == "json":
        return {"part_type": "json"}
    if kind == "image":
        return {"part_type": "image"}
    if kind == "file":
        return {"part_type": "file", "mode": "inline_text"}
    if kind == "media_group":
        return {"part_type": "media_group", "layout": "gallery"}
    if kind == "parts":
        return {"part_type": "parts"}
    raise ValueError(f"unsupported reply type: {kind}")


def _first_unload_error(data: Dict[str, Any]) -> Optional[str]:
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("message") or first.get("code") or "Model unload failed.")
    return None


def _resolution_as_config_metadata(resolution: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": resolution.get("source"),
        "profile_id": resolution.get("profile_id"),
        "profile_alias": resolution.get("profile_alias"),
        "profile_key": resolution.get("profile_key") or resolution.get("profile_alias"),
        "profile_name": resolution.get("profile_name"),
        "provider_profile_id": resolution.get("provider_profile_id"),
        "provider_profile_name": resolution.get("provider_profile_name"),
        "provider": resolution.get("provider"),
        "session_override_requested": resolution.get("session_override_requested"),
        "session_override_applied": resolution.get("session_override_applied"),
        "allow_session_override": resolution.get("allow_session_override"),
    }


def _legacy_unload_result(data: Dict[str, Any], resolution: Dict[str, Any], model_config: Dict[str, Any]) -> Dict[str, Any]:
    ok = bool(data.get("success"))
    model_id = str(resolution.get("model_id") or model_config.get("model_id") or model_config.get("model") or "")
    return {
        "ok": ok,
        "code": "MODEL_UNLOAD_UNSUPPORTED" if data.get("unsupported") else None,
        "provider": resolution.get("provider") or model_config.get("provider"),
        "provider_profile_id": resolution.get("provider_profile_id") or model_config.get("provider_profile_id"),
        "provider_profile_name": resolution.get("provider_profile_name") or model_config.get("provider_profile_name"),
        "model_profile_id": resolution.get("profile_id") or model_config.get("model_profile_id"),
        "model_profile_name": resolution.get("profile_name") or model_config.get("model_profile_name"),
        "requested_model_id": model_id,
        "model_id": model_id,
        "unloaded": data.get("unloaded") or [],
        "skipped": False,
        "skip_reason": None,
        "errors": [] if ok else [{"code": "MODEL_UNLOAD_UNSUPPORTED" if data.get("unsupported") else "MODEL_UNLOAD_FAILED", "message": data.get("message") or "Model unload failed."}],
        "status_refresh": data.get("status_refresh"),
        "result": data,
    }


def _enrich_script_unload_result(result: Dict[str, Any], resolution: Dict[str, Any], model_config: Dict[str, Any]) -> Dict[str, Any]:
    model_id = str(resolution.get("model_id") or model_config.get("model_id") or model_config.get("model") or result.get("model_id") or "")
    result.setdefault("provider", resolution.get("provider") or model_config.get("provider"))
    result.setdefault("provider_profile_id", resolution.get("provider_profile_id") or model_config.get("provider_profile_id"))
    result.setdefault("provider_profile_name", resolution.get("provider_profile_name") or model_config.get("provider_profile_name"))
    result.setdefault("model_profile_id", resolution.get("profile_id") or model_config.get("model_profile_id"))
    result.setdefault("model_profile_name", resolution.get("profile_name") or model_config.get("model_profile_name"))
    result.setdefault("requested_model_id", model_id)
    result.setdefault("model_id", model_id)
    return result


def _messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    return "\n\n".join(f"{message.get('role', 'user')}: {message.get('content', '')}" for message in messages)


def _resolve_llm_messages(
    system: Optional[str] = None,
    user: Optional[str] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if messages is not None:
        return messages
    resolved: List[Dict[str, Any]] = []
    if system is not None:
        resolved.append({"role": "system", "content": system})
    if user is not None:
        resolved.append({"role": "user", "content": user})
    return resolved or [{"role": "user", "content": ""}]


def _model_from_config(model_config: Dict[str, Any]) -> Optional[str]:
    value = model_config.get("model_id") or model_config.get("model")
    return str(value) if value else None


def _agent_uses_llm(agent: AgentSchema) -> bool:
    return bool(agent.llm or agent.model or "llm" in (agent.capabilities or []))
