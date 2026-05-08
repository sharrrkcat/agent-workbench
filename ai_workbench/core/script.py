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
from ai_workbench.core.agent_settings import resolved_agent_settings, resolved_model_lifecycle, resolved_runtime_override
from ai_workbench.core.attachments import (
    read_attachment_as_data_url,
    read_attachment_bytes,
    read_attachment_text,
    save_generated_attachment_base64,
    save_generated_attachment_bytes,
)
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.llm_config import LLMConfigError, resolve_llm_config
from ai_workbench.core.provider_status import refresh_provider_status_for_profile, unload_model_for_profile
from ai_workbench.core.run_lifecycle import RunLifecycle
from ai_workbench.core.schema.agent import AgentSchema
from ai_workbench.core.schema.message import ImageGalleryPayload, ImagePayload, RichContentPayload
from ai_workbench.core.schema.result import CapabilityCallResult, RunResult
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.session import Session
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore
from ai_workbench.core.time import isoformat_utc


@dataclass
class ScriptLLMStreamChunk:
    text: str = ""
    raw: Any = None
    finish_reason: Optional[str] = None
    model: Optional[str] = None


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


class ScriptOutputProxy:
    def __init__(self, message_store: MessageStore, event_bus: EventBus, session_id: str, run_id: str, message_id: Optional[str]) -> None:
        self.message_store = message_store
        self.event_bus = event_bus
        self.session_id = session_id
        self.run_id = run_id
        self.message_id = message_id
        self.completed = False
        self._content = ""
        self._output_type = "text"
        self._seq = 0

    @property
    def has_content(self) -> bool:
        return bool(self._content)

    async def set_output_type(self, output_type: str) -> None:
        self._output_type = output_type or self._output_type
        if not self.message_id:
            return
        message = self.message_store.get_message(self.message_id)
        self.message_store.update_message(message.model_copy(update={"output_type": self._output_type}))

    async def write_delta(self, text: str) -> None:
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
        output_type: Optional[str] = None,
        actions=None,
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        action_id: Optional[str] = None,
        parent_message_id: Optional[str] = None,
    ):
        if self.completed:
            if final_content is None and output_type is None and actions is None and metadata is None:
                return self.message_store.get_message(self.message_id)
            message = self.message_store.add_message(
                session_id=self.session_id,
                role="agent",
                content=final_content if final_content is not None else "",
                agent_id=agent_id,
                action_id=action_id,
                run_id=self.run_id,
                output_type=output_type or self._output_type,
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
        if output_type:
            self._output_type = output_type
        if final_content is not None:
            self._content = final_content if isinstance(final_content, str) else final_content
        if not self.message_id:
            raise RuntimeError("Output message is not configured.")
        message = self.message_store.get_message(self.message_id)
        next_metadata = {**(message.metadata or {}), **(metadata or {}), "streaming": False, "placeholder": False}
        message = message.model_copy(
            update={
                "content": self._content,
                "output_type": self._output_type,
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
        from ai_workbench.core.context import validate_llm_context_messages

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
        self.used = True
        resolved_messages = _resolve_llm_messages(system=system, user=user, messages=messages)
        from ai_workbench.core.context import validate_llm_context_messages

        resolved_messages = validate_llm_context_messages(resolved_messages)
        model_config = options.pop("model_config", None) or self.default_model_config
        if response_format is not None:
            options["response_format"] = response_format
        if model_config.get("supports_streaming") is False:
            text = await self.chat(messages=resolved_messages, model_config=model_config, **options)
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
        output_type: str = "markdown",
        **options,
    ) -> str:
        if self.output is None:
            raise RuntimeError("Output streaming is not configured.")
        await self.output.set_output_type(output_type)
        parts: list[str] = []
        async for chunk in self.stream(system=system, user=user, messages=messages, **options):
            if not chunk.text:
                continue
            parts.append(chunk.text)
            await self.output.write_delta(chunk.text)
        text = "".join(parts)
        await self.output.finish(metadata=self.message_metadata())
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
                    self.used = True
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
        if not self.default_llm_resolution:
            return {}
        try:
            from ai_workbench.core.runner import _llm_message_metadata

            llm_config = SimpleNamespace(values=self.default_model_config, metadata=_resolution_as_config_metadata(self.default_llm_resolution))
            return {
                "llm_resolution": self.default_llm_resolution,
                "llm": _llm_message_metadata(llm_config, self.last_raw),
            }
        except Exception:
            return {"llm_resolution": self.default_llm_resolution}

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
        self.session = ScriptSession(session_id=session.session_id, default_agent_id=session.default_agent_id, context_mode=session.context_mode)
        self.config = config or {}
        self.run_store = run_store
        self.message_store = message_store
        self.session_store = session_store
        self.event_bus = event_bus
        self.runtime_registry = runtime_registry
        self.output = ScriptOutputProxy(
            message_store=message_store,
            event_bus=event_bus,
            session_id=session.session_id,
            run_id=run_id,
            message_id=output_message_id,
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
        )
        self.llm_resolution = llm_resolution or {}
        self.parent_message_id = parent_message_id
        self.waiting = False
        self.current_parent_step_id = current_parent_step_id
        self.run = ScriptRunLifecycleProxy(run_lifecycle, run_id, default_parent_step_id=current_parent_step_id) if run_lifecycle is not None else None

    async def reply(self, content: Any, type: str = "text", output_type: Optional[str] = None, actions=None):
        resolved_output_type = output_type or type
        metadata = {"success": True, **self.llm.message_metadata()}
        self.llm.record_run_llm_metadata()
        message = await self.output.finish(
            final_content=content,
            output_type=resolved_output_type,
            actions=actions or [],
            metadata=metadata,
            agent_id=self.agent.id,
            action_id=self.action_id,
            parent_message_id=self.parent_message_id,
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
                speaker_type="user",
                speaker_id="local_user",
                speaker_name="User",
                origin="user_message",
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
        output_message = self.message_store.add_message(
            session_id=session_id,
            role="assistant",
            content="",
            agent_id=agent.id,
            action_id=action_id,
            run_id=run.run_id,
            output_type="text",
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
                self.run_lifecycle.fail_step(model_step.step_id, error_code=exc.code, error_message=exc.message)
                return self._fail(run.run_id, session_id, exc.message, error_code=exc.code)
            self.run_lifecycle.complete_step(model_step.step_id)

        starting_step = self.run_lifecycle.start_step(run.run_id, "Starting script")
        self.run_lifecycle.complete_step(starting_step.step_id)
        running_step = self.run_lifecycle.start_step(run.run_id, "Running script")

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
            output_message_id=output_message.message_id,
            current_parent_step_id=running_step.step_id,
        )

        try:
            script_result = await script_run(ctx)
        except Exception as exc:
            self.run_lifecycle.fail_step(running_step.step_id, error_message=str(exc) or "Script agent failed.")
            if ctx.output.has_content:
                final_content = None
                output_type = None
            else:
                final_content = {"code": "RUN_FAILED", "message": str(exc) or "Script agent failed."}
                output_type = "error"
            await ctx.output.finish(
                final_content=final_content,
                output_type=output_type,
                metadata={"success": False, "error": str(exc) or "Script agent failed."},
                agent_id=agent.id,
                action_id=action_id,
                parent_message_id=parent_id,
            )
            result = self._fail(run.run_id, session_id, str(exc) or "Script agent failed.")
            self._apply_model_lifecycle(ctx, lifecycle)
            return result
        self.run_lifecycle.complete_step(running_step.step_id)

        final_run = self.run_store.get_run(run.run_id)
        if final_run.status == RunStatus.WAITING_FOR_USER:
            return RunResult(success=False, run_id=run.run_id, error="Waiting for user input.")

        saving_step = self.run_lifecycle.start_step(run.run_id, "Saving response")
        if not ctx.output.completed:
            await ctx.output.finish(
                final_content="" if script_result is None else script_result,
                output_type="text",
                metadata={"success": True, **ctx.llm.message_metadata()},
                agent_id=agent.id,
                action_id=action_id,
                parent_message_id=parent_id,
            )
        self.run_lifecycle.complete_step(saving_step.step_id)
        cleanup_step = self.run_lifecycle.start_step(run.run_id, "Cleanup")
        unload_result = self._apply_model_lifecycle(ctx, lifecycle)
        from ai_workbench.core.runner import _llm_unload_message

        unload_message = _llm_unload_message(unload_result) if unload_result else None
        self.run_lifecycle.complete_step(cleanup_step.step_id, message=unload_message, metadata={"llm_unload": unload_result} if unload_message else None)
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
