from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ai_workbench.core.schema.message import MessageSchema, infer_speaker_identity
from ai_workbench.core.message_parts import make_text_part, validate_message_parts
from ai_workbench.core.schema.llm_profile import LLMProfileSchema, ProviderProfileSchema
from ai_workbench.core.schema.run import RunSchema, RunStatus, RunStepSchema, RunStepStatus
from ai_workbench.core.schema.run_event import RunEventSchema
from ai_workbench.core.multimodal_profiles import MultimodalEmbeddingModelProfile
from ai_workbench.core.vision_profiles import VisionModelProfile
from ai_workbench.core.session_titles import is_default_session_title
from ai_workbench.core.session import Session
from ai_workbench.core.time import utc_now


class SessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}

    def create_session(self, default_agent_id: str = "chat", title: str = "", context_mode: str = "single_assistant") -> Session:
        session = Session(
            session_id=str(uuid4()),
            title=title,
            default_agent_id=default_agent_id,
            context_mode=context_mode,
            title_generation_state="pending" if is_default_session_title(title) else "manual",
        )
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"unknown session id: {session_id}") from exc

    def set_default_agent(self, session_id: str, agent_id: str) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(update={"default_agent_id": agent_id, "updated_at": utc_now()})
        self._sessions[session_id] = updated
        return updated

    def set_context_mode(self, session_id: str, context_mode: str) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(update={"context_mode": context_mode, "updated_at": utc_now()})
        self._sessions[session_id] = updated
        return updated

    def set_title(self, session_id: str, title: str) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(update={"title": title, "title_generation_state": "manual", "updated_at": utc_now()})
        self._sessions[session_id] = updated
        return updated

    def set_generated_title(self, session_id: str, title: str, metadata: Optional[Dict[str, Any]] = None) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(
            update={
                "title": title,
                "title_generation_state": "done",
                "title_generation_metadata": metadata or {},
                "updated_at": utc_now(),
            }
        )
        self._sessions[session_id] = updated
        return updated

    def set_title_generation_state(self, session_id: str, state: str, metadata: Optional[Dict[str, Any]] = None) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(
            update={"title_generation_state": state, "title_generation_metadata": metadata or {}, "updated_at": utc_now()}
        )
        self._sessions[session_id] = updated
        return updated

    def set_waiting_run(self, session_id: str, run_id: Optional[str]) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(update={"waiting_run_id": run_id, "updated_at": utc_now()})
        self._sessions[session_id] = updated
        return updated

    def set_llm_profile(self, session_id: str, profile_id: Optional[str]) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(update={"llm_profile_id": profile_id, "updated_at": utc_now()})
        self._sessions[session_id] = updated
        return updated

    def set_last_announced_llm_profile(self, session_id: str, profile_id: Optional[str]) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(
            update={"last_announced_llm_profile_id": profile_id, "updated_at": utc_now()}
        )
        self._sessions[session_id] = updated
        return updated

    def delete_session(self, session_id: str) -> None:
        self.get_session(session_id)
        del self._sessions[session_id]

    def list_sessions(self) -> List[Session]:
        return sorted(
            self._sessions.values(),
            key=lambda session: (session.updated_at, session.created_at),
            reverse=True,
        )

    def touch_session(self, session_id: str) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(update={"updated_at": utc_now()})
        self._sessions[session_id] = updated
        return updated


class MessageStore:
    def __init__(self, session_store: Optional[SessionStore] = None) -> None:
        self._messages: Dict[str, MessageSchema] = {}
        self._session_message_ids: Dict[str, List[str]] = {}
        self._session_store = session_store

    def add_message(
        self,
        session_id: str,
        role: str,
        content: Any,
        agent_id: Optional[str] = None,
        command_name: Optional[str] = None,
        action_id: Optional[str] = None,
        run_id: Optional[str] = None,
        content_version: Optional[int] = None,
        parts: Optional[List[Dict[str, Any]]] = None,
        available_actions: Optional[List[Dict[str, Any]]] = None,
        parent_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        speaker_type: Optional[str] = None,
        speaker_id: Optional[str] = None,
        speaker_name: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> MessageSchema:
        speaker = infer_speaker_identity(
            role,
            agent_id=agent_id,
            command_name=command_name,
            metadata=metadata,
            speaker_type=speaker_type,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            origin=origin,
        )
        if parts is None and content not in (None, ""):
            text_format = "markdown" if role in {"assistant", "agent"} else "plain"
            parts = [make_text_part(str(content), format=text_format)]
        validated_parts = validate_message_parts(parts) if parts is not None else []
        resolved_content_version = content_version or 2
        message = MessageSchema(
            message_id=str(uuid4()),
            session_id=session_id,
            role=role,
            **speaker,
            agent_id=agent_id,
            command_name=command_name,
            action_id=action_id,
            run_id=run_id,
            content_version=resolved_content_version,
            parts=validated_parts,
            available_actions=available_actions or [],
            parent_message_id=parent_message_id,
            metadata=metadata or {},
        )
        self._messages[message.message_id] = message
        self._session_message_ids.setdefault(session_id, []).append(message.message_id)
        if self._session_store is not None:
            self._session_store.touch_session(session_id)
        return message

    def get_message(self, message_id: str) -> MessageSchema:
        try:
            return self._messages[message_id]
        except KeyError as exc:
            raise KeyError(f"unknown message id: {message_id}") from exc

    def update_message(self, message: MessageSchema) -> MessageSchema:
        if message.message_id not in self._messages:
            raise KeyError(f"unknown message id: {message.message_id}")
        self._messages[message.message_id] = message
        if self._session_store is not None:
            self._session_store.touch_session(message.session_id)
        return message

    def delete_message(self, message_id: str) -> MessageSchema:
        message = self.get_message(message_id)
        self._messages.pop(message_id, None)
        message_ids = self._session_message_ids.get(message.session_id, [])
        self._session_message_ids[message.session_id] = [item for item in message_ids if item != message_id]
        if self._session_store is not None:
            self._session_store.touch_session(message.session_id)
        return message

    def delete_messages_after(self, session_id: str, message_id: str, include_target: bool = False) -> List[MessageSchema]:
        messages = self.list_messages(session_id)
        index = next((idx for idx, message in enumerate(messages) if message.message_id == message_id), None)
        if index is None:
            raise KeyError(f"unknown message id: {message_id}")
        start = index if include_target else index + 1
        deleted = messages[start:]
        if not deleted:
            return []
        deleted_ids = {message.message_id for message in deleted}
        for deleted_id in deleted_ids:
            self._messages.pop(deleted_id, None)
        self._session_message_ids[session_id] = [
            item for item in self._session_message_ids.get(session_id, []) if item not in deleted_ids
        ]
        if self._session_store is not None:
            self._session_store.touch_session(session_id)
        return deleted

    def list_messages(self, session_id: str) -> List[MessageSchema]:
        return [self._messages[message_id] for message_id in self._session_message_ids.get(session_id, [])]

    def list_all_messages(self) -> List[MessageSchema]:
        return list(self._messages.values())

    def delete_session(self, session_id: str) -> None:
        message_ids = self._session_message_ids.pop(session_id, [])
        for message_id in message_ids:
            self._messages.pop(message_id, None)

    def find_latest_assistant_message(self, session_id: str, agent_id: Optional[str] = None) -> Optional[MessageSchema]:
        for message in reversed(self.list_messages(session_id)):
            if message.role != "assistant":
                continue
            if agent_id is not None and message.agent_id != agent_id:
                continue
            return message
        return None


class RunStore:
    def __init__(self) -> None:
        self._runs: Dict[str, RunSchema] = {}
        self._session_run_ids: Dict[str, List[str]] = {}
        self._steps: Dict[str, RunStepSchema] = {}
        self._run_step_ids: Dict[str, List[str]] = {}

    def create_run(
        self,
        kind: str,
        target_id: str,
        session_id: str,
        action_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RunSchema:
        run = RunSchema(
            run_id=str(uuid4()),
            kind=kind,
            target_id=target_id,
            session_id=session_id,
            action_id=action_id,
            metadata=metadata or {},
        )
        self._runs[run.run_id] = run
        self._session_run_ids.setdefault(session_id, []).append(run.run_id)
        return run

    def get_run(self, run_id: str) -> RunSchema:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"unknown run id: {run_id}") from exc

    def update_status(
        self,
        run_id: str,
        status: RunStatus,
        current_step: Optional[str] = None,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        cancel_requested: Optional[bool] = None,
    ) -> RunSchema:
        run = self.get_run(run_id)
        updates: Dict[str, Any] = {"status": status, "updated_at": utc_now()}
        if status == RunStatus.RUNNING and run.started_at is None:
            updates["started_at"] = updates["updated_at"]
        if status in {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}:
            updates["finished_at"] = updates["updated_at"]
        if current_step is not None:
            updates["current_step"] = current_step
            updates["stage"] = current_step
        if error is not None:
            updates["error"] = error
            updates["error_message"] = error
        if error_code is not None:
            updates["error_code"] = error_code
        if error_message is not None:
            updates["error_message"] = error_message
            updates["error"] = error_message
        if cancel_requested is not None:
            updates["cancel_requested"] = cancel_requested
        updated = run.model_copy(update=updates)
        self._runs[run_id] = updated
        return updated

    def update_progress(
        self,
        run_id: str,
        stage: Optional[str] = None,
        message: Optional[str] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
    ) -> RunSchema:
        run = self.get_run(run_id)
        updates: Dict[str, Any] = {"updated_at": utc_now()}
        if stage is not None:
            updates["stage"] = stage
            updates["current_step"] = stage
        if message is not None:
            updates["progress_message"] = message
        if current is not None:
            updates["progress_current"] = current
        if total is not None:
            updates["progress_total"] = total
        updated = run.model_copy(update=updates)
        self._runs[run_id] = updated
        return updated

    def update_metadata(self, run_id: str, metadata: Dict[str, Any]) -> RunSchema:
        run = self.get_run(run_id)
        updated = run.model_copy(update={"metadata": metadata, "updated_at": utc_now()})
        self._runs[run_id] = updated
        return updated

    def list_runs(self, session_id: str) -> List[RunSchema]:
        return [self._runs[run_id] for run_id in self._session_run_ids.get(session_id, [])]

    def list_all_runs(self) -> List[RunSchema]:
        return sorted(self._runs.values(), key=lambda run: run.created_at)

    def delete_session(self, session_id: str) -> None:
        run_ids = self._session_run_ids.pop(session_id, [])
        for run_id in run_ids:
            self._runs.pop(run_id, None)
            for step_id in self._run_step_ids.pop(run_id, []):
                self._steps.pop(step_id, None)

    def cancel_runs(self, run_ids: List[str], reason: str = "Messages were removed.") -> List[RunSchema]:
        cancelled: List[RunSchema] = []
        for run_id in run_ids:
            run = self._runs.get(run_id)
            if run is None or run.status in {RunStatus.CANCELLED, RunStatus.INTERRUPTED}:
                continue
            updated = run.model_copy(
                update={"status": RunStatus.CANCELLED, "current_step": "cancelled", "error": reason, "updated_at": utc_now()}
            )
            self._runs[run_id] = updated
            cancelled.append(updated)
        return cancelled

    def create_step(
        self,
        run_id: str,
        label: str,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: RunStepStatus = RunStepStatus.RUNNING,
        parent_step_id: Optional[str] = None,
    ) -> RunStepSchema:
        self.get_run(run_id)
        if parent_step_id is not None:
            parent = self.get_step(parent_step_id)
            if parent.run_id != run_id:
                raise ValueError("parent_step_id must belong to the same run")
        order = len(self._run_step_ids.get(run_id, []))
        now = utc_now()
        step = RunStepSchema(
            step_id=str(uuid4()),
            run_id=run_id,
            parent_step_id=parent_step_id,
            label=label,
            status=status,
            message=message or "",
            order=order,
            started_at=now if status == RunStepStatus.RUNNING else None,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self._steps[step.step_id] = step
        self._run_step_ids.setdefault(run_id, []).append(step.step_id)
        return step

    def update_step(
        self,
        step_id: str,
        status: Optional[RunStepStatus] = None,
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RunStepSchema:
        try:
            step = self._steps[step_id]
        except KeyError as exc:
            raise KeyError(f"unknown run step id: {step_id}") from exc
        now = utc_now()
        updates: Dict[str, Any] = {"updated_at": now}
        if status is not None:
            updates["status"] = status
            if status == RunStepStatus.RUNNING and step.started_at is None:
                updates["started_at"] = now
            if status in {RunStepStatus.COMPLETED, RunStepStatus.FAILED, RunStepStatus.SKIPPED}:
                updates["finished_at"] = now
        if message is not None:
            updates["message"] = message
        if error_code is not None:
            updates["error_code"] = error_code
        if error_message is not None:
            updates["error_message"] = error_message
        if metadata is not None:
            updates["metadata"] = {**step.metadata, **metadata}
        updated = step.model_copy(update=updates)
        self._steps[step_id] = updated
        return updated

    def get_step(self, step_id: str) -> RunStepSchema:
        try:
            return self._steps[step_id]
        except KeyError as exc:
            raise KeyError(f"unknown run step id: {step_id}") from exc

    def list_steps(self, run_id: str) -> List[RunStepSchema]:
        return [self._steps[step_id] for step_id in self._run_step_ids.get(run_id, [])]


class RunEventStore:
    def __init__(self) -> None:
        self._events: Dict[str, RunEventSchema] = {}
        self._run_event_ids: Dict[str, List[str]] = {}

    def add_event(
        self,
        run_id: str,
        session_id: str,
        type: str,
        message: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> RunEventSchema:
        event = RunEventSchema(
            event_id=str(uuid4()),
            run_id=run_id,
            session_id=session_id,
            type=type,
            message=message,
            payload=payload or {},
            created_at=utc_now(),
        )
        self._events[event.event_id] = event
        self._run_event_ids.setdefault(run_id, []).append(event.event_id)
        return event

    def list_events(self, run_id: str) -> List[RunEventSchema]:
        return [self._events[event_id] for event_id in self._run_event_ids.get(run_id, [])]

    def delete_session(self, session_id: str) -> None:
        deleted_event_ids = [
            event_id
            for event_id, event in self._events.items()
            if event.session_id == session_id
        ]
        for event_id in deleted_event_ids:
            event = self._events.pop(event_id, None)
            if event is None:
                continue
            run_event_ids = self._run_event_ids.get(event.run_id, [])
            self._run_event_ids[event.run_id] = [item for item in run_event_ids if item != event_id]


class ConfigStore:
    def __init__(self, id_field: str) -> None:
        self.id_field = id_field
        self._records: Dict[str, Dict[str, Any]] = {}

    def set_config(
        self,
        item_id: str,
        enabled: Optional[bool] = None,
        user_config: Optional[Dict[str, Any]] = None,
        display: Optional[Dict[str, Any]] = None,
        runtime: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        record = self._records.get(item_id)
        if record is None:
            record = {
                self.id_field: item_id,
                "enabled": True,
                "display": {},
                "runtime": {},
                "user_config": {},
                "created_at": now,
                "updated_at": now,
            }
        if enabled is not None:
            record["enabled"] = enabled
        if user_config is not None:
            record["user_config"] = user_config
        if display is not None:
            record["display"] = display
        if runtime is not None:
            record["runtime"] = runtime
        record["updated_at"] = now
        self._records[item_id] = record
        return dict(record)

    def get_config(self, item_id: str) -> Dict[str, Any]:
        if item_id not in self._records:
            return self.set_config(item_id)
        return dict(self._records[item_id])

    def list_configs(self) -> List[Dict[str, Any]]:
        return [dict(record) for record in self._records.values()]

    def is_enabled(self, item_id: str) -> bool:
        return bool(self.get_config(item_id)["enabled"])


class AgentConfigStore(ConfigStore):
    def __init__(self) -> None:
        super().__init__("agent_id")


class CapabilityConfigStore(ConfigStore):
    def __init__(self) -> None:
        super().__init__("capability_id")

    def set_config(
        self,
        item_id: str,
        enabled: Optional[bool] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return super().set_config(item_id=item_id, enabled=enabled, user_config=user_config)


class SessionAgentStateStore:
    def __init__(self) -> None:
        self._records: Dict[tuple[str, str, str], Any] = {}

    def get_state(self, session_id: str, agent_id: str, key: str) -> Any:
        return self._records.get((session_id, agent_id, key))

    def set_state(self, session_id: str, agent_id: str, key: str, value: Any) -> Any:
        self._records[(session_id, agent_id, key)] = value
        return value

    def delete_session(self, session_id: str) -> None:
        for record_key in [record_key for record_key in self._records if record_key[0] == session_id]:
            self._records.pop(record_key, None)


class LLMProfileStore:
    def __init__(self) -> None:
        self._records: Dict[str, LLMProfileSchema] = {}

    def create(self, profile: LLMProfileSchema) -> LLMProfileSchema:
        if profile.id in self._records:
            raise ValueError(f"LLM profile id already exists: {profile.id}")
        if self.find_by_alias(profile.alias) is not None:
            raise ValueError(f"LLM profile alias already exists: {profile.alias}")
        self._records[profile.id] = profile
        return profile

    def get(self, profile_id: str) -> LLMProfileSchema:
        try:
            return self._records[profile_id]
        except KeyError as exc:
            raise KeyError(f"unknown LLM profile id: {profile_id}") from exc

    def find_by_alias(self, alias: str) -> Optional[LLMProfileSchema]:
        for profile in self._records.values():
            if profile.alias == alias:
                return profile
        return None

    def get_by_id_or_alias(self, profile_id_or_alias: str) -> LLMProfileSchema:
        if profile_id_or_alias in self._records:
            return self._records[profile_id_or_alias]
        profile = self.find_by_alias(profile_id_or_alias)
        if profile is not None:
            return profile
        raise KeyError(f"unknown LLM profile: {profile_id_or_alias}")

    def update(self, profile_id_or_alias: str, values: Dict[str, Any]) -> LLMProfileSchema:
        existing = self.get_by_id_or_alias(profile_id_or_alias)
        alias = values.get("alias")
        if alias is not None:
            conflict = self.find_by_alias(str(alias))
            if conflict is not None and conflict.id != existing.id:
                raise ValueError(f"LLM profile alias already exists: {alias}")
        updated = existing.model_copy(update={**values, "updated_at": utc_now()})
        updated = LLMProfileSchema.model_validate(updated.model_dump())
        self._records[existing.id] = updated
        return updated

    def delete(self, profile_id_or_alias: str) -> LLMProfileSchema:
        existing = self.get_by_id_or_alias(profile_id_or_alias)
        del self._records[existing.id]
        return existing

    def list(self) -> List[LLMProfileSchema]:
        return sorted(self._records.values(), key=lambda item: (item.alias, item.created_at))


class ProviderProfileStore:
    def __init__(self) -> None:
        self._records: Dict[str, ProviderProfileSchema] = {}

    def create(self, profile: ProviderProfileSchema) -> ProviderProfileSchema:
        if profile.id in self._records:
            raise ValueError(f"Provider profile id already exists: {profile.id}")
        self._records[profile.id] = profile
        return profile

    def get(self, profile_id: str) -> ProviderProfileSchema:
        try:
            return self._records[profile_id]
        except KeyError as exc:
            raise KeyError(f"unknown provider profile id: {profile_id}") from exc

    def update(self, profile_id: str, values: Dict[str, Any]) -> ProviderProfileSchema:
        existing = self.get(profile_id)
        updated = existing.model_copy(update={**values, "updated_at": utc_now()})
        updated = ProviderProfileSchema.model_validate(updated.model_dump())
        self._records[existing.id] = updated
        return updated

    def delete(self, profile_id: str) -> ProviderProfileSchema:
        existing = self.get(profile_id)
        del self._records[existing.id]
        return existing

    def list(self) -> List[ProviderProfileSchema]:
        return sorted(self._records.values(), key=lambda item: (item.name.lower(), item.created_at))


class MultimodalEmbeddingProfileStore:
    def __init__(self) -> None:
        self._records: Dict[str, MultimodalEmbeddingModelProfile] = {}

    def create(self, profile: MultimodalEmbeddingModelProfile) -> MultimodalEmbeddingModelProfile:
        if profile.id in self._records:
            raise ValueError(f"Multimodal embedding profile id already exists: {profile.id}")
        if self.find_by_alias(profile.alias) is not None or profile.alias in self._records:
            raise ValueError("MULTIMODAL_EMBEDDING_ALIAS_EXISTS")
        self._records[profile.id] = profile
        return profile

    def get(self, profile_id: str) -> MultimodalEmbeddingModelProfile:
        try:
            return self._records[profile_id]
        except KeyError as exc:
            raise KeyError(f"unknown multimodal embedding profile id: {profile_id}") from exc

    def find_by_alias(self, alias: str) -> Optional[MultimodalEmbeddingModelProfile]:
        for profile in self._records.values():
            if profile.alias == alias:
                return profile
        return None

    def get_by_id_or_alias(self, profile_id_or_alias: str) -> MultimodalEmbeddingModelProfile:
        if profile_id_or_alias in self._records:
            return self._records[profile_id_or_alias]
        profile = self.find_by_alias(profile_id_or_alias)
        if profile is not None:
            return profile
        raise KeyError(f"unknown multimodal embedding profile: {profile_id_or_alias}")

    def update(self, profile_id: str, values: Dict[str, Any]) -> MultimodalEmbeddingModelProfile:
        existing = self.get_by_id_or_alias(profile_id)
        alias = values.get("alias")
        if alias is not None:
            conflict = self.find_by_alias(str(alias))
            if (conflict is not None and conflict.id != existing.id) or (str(alias) in self._records and str(alias) != existing.id):
                raise ValueError("MULTIMODAL_EMBEDDING_ALIAS_EXISTS")
        updated = existing.model_copy(update={**values, "updated_at": utc_now()})
        updated = MultimodalEmbeddingModelProfile.model_validate(updated.model_dump())
        self._records[existing.id] = updated
        return updated

    def delete(self, profile_id: str) -> MultimodalEmbeddingModelProfile:
        existing = self.get_by_id_or_alias(profile_id)
        del self._records[existing.id]
        return existing

    def list(self) -> List[MultimodalEmbeddingModelProfile]:
        return sorted(self._records.values(), key=lambda item: (item.alias, item.created_at))


class VisionProfileStore:
    def __init__(self) -> None:
        self._records: Dict[str, VisionModelProfile] = {}

    def create(self, profile: VisionModelProfile) -> VisionModelProfile:
        if profile.id in self._records:
            raise ValueError(f"Vision profile id already exists: {profile.id}")
        if self.find_by_alias(profile.alias) is not None or profile.alias in self._records:
            raise ValueError("VISION_MODEL_ALIAS_EXISTS")
        self._records[profile.id] = profile
        return profile

    def get(self, profile_id: str) -> VisionModelProfile:
        try:
            return self._records[profile_id]
        except KeyError as exc:
            raise KeyError(f"unknown vision profile id: {profile_id}") from exc

    def find_by_alias(self, alias: str) -> Optional[VisionModelProfile]:
        for profile in self._records.values():
            if profile.alias == alias:
                return profile
        return None

    def get_by_id_or_alias(self, profile_id_or_alias: str) -> VisionModelProfile:
        if profile_id_or_alias in self._records:
            return self._records[profile_id_or_alias]
        profile = self.find_by_alias(profile_id_or_alias)
        if profile is not None:
            return profile
        raise KeyError(f"unknown vision profile: {profile_id_or_alias}")

    def update(self, profile_id: str, values: Dict[str, Any]) -> VisionModelProfile:
        existing = self.get_by_id_or_alias(profile_id)
        alias = values.get("alias")
        if alias is not None:
            conflict = self.find_by_alias(str(alias))
            if (conflict is not None and conflict.id != existing.id) or (str(alias) in self._records and str(alias) != existing.id):
                raise ValueError("VISION_MODEL_ALIAS_EXISTS")
        updated = existing.model_copy(update={**values, "updated_at": utc_now()})
        updated = VisionModelProfile.model_validate(updated.model_dump())
        self._records[existing.id] = updated
        return updated

    def delete(self, profile_id: str) -> VisionModelProfile:
        existing = self.get_by_id_or_alias(profile_id)
        del self._records[existing.id]
        return existing

    def list(self) -> List[VisionModelProfile]:
        return sorted(self._records.values(), key=lambda item: (item.alias, item.created_at))


class LLMDefaultsStore:
    def __init__(self) -> None:
        self.default_model_profile_id: Optional[str] = None

    def get(self) -> Dict[str, Optional[str]]:
        return {"default_model_profile_id": self.default_model_profile_id}

    def patch(self, values: Dict[str, Any]) -> Dict[str, Optional[str]]:
        if "default_model_profile_id" in values:
            value = values.get("default_model_profile_id")
            self.default_model_profile_id = str(value) if value else None
        return self.get()
