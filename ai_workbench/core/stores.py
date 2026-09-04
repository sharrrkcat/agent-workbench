"""Small explicit in-memory stores used by the core services.

The SQL stores mirror these methods.  Keeping the two implementations close
to one another makes the memory application used by tests behave like the
SQLite application without any extension registry machinery.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Iterable, Optional, TypeVar
from uuid import uuid4

from ai_workbench.core.message_parts import make_text_part, validate_message_parts
from ai_workbench.core.schema.llm_profile import LLMProfileSchema, ProviderProfileSchema
from ai_workbench.core.multimodal_profiles import MultimodalEmbeddingModelProfile
from ai_workbench.core.vision_profiles import VisionModelProfile
from ai_workbench.core.schema.message import MessageSchema, infer_speaker_identity
from ai_workbench.core.schema.run import RunSchema, RunStatus, RunStepSchema, RunStepKind, RunStepStatus
from ai_workbench.core.schema.run_event import RunEventSchema
from ai_workbench.core.session import Session
from ai_workbench.core.time import utc_now


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create_session(self, title: str = "", context_mode: str = "single_assistant") -> Session:
        session = Session(
            session_id=str(uuid4()),
            title=title,
            context_mode=context_mode,
            title_generation_state="pending" if not title.strip() or title.strip() == "New session" else "manual",
        )
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"unknown session id: {session_id}") from exc

    def set_context_mode(self, session_id: str, context_mode: str) -> Session:
        return self._replace(session_id, context_mode=context_mode)

    def set_title(self, session_id: str, title: str) -> Session:
        return self._replace(session_id, title=title, title_generation_state="manual")

    def set_generated_title(self, session_id: str, title: str, metadata: Optional[dict[str, Any]] = None) -> Session:
        return self._replace(session_id, title=title, title_generation_state="done", title_generation_metadata=metadata or {})

    def set_title_generation_state(self, session_id: str, state: str, metadata: Optional[dict[str, Any]] = None) -> Session:
        return self._replace(session_id, title_generation_state=state, title_generation_metadata=metadata or {})

    def set_waiting_run(self, session_id: str, run_id: Optional[str]) -> Session:
        return self._replace(session_id, waiting_run_id=run_id)

    def set_llm_profile(self, session_id: str, profile_id: Optional[str]) -> Session:
        return self._replace(session_id, llm_profile_id=profile_id)

    def set_last_announced_llm_profile(self, session_id: str, profile_id: Optional[str]) -> Session:
        return self._replace(session_id, last_announced_llm_profile_id=profile_id)

    def clear_interrupted_waiting_runs(self, run_ids: list[str]) -> None:
        ids = set(run_ids)
        for session_id, session in list(self._sessions.items()):
            if session.waiting_run_id in ids:
                self._sessions[session_id] = session.model_copy(update={"waiting_run_id": None, "updated_at": utc_now()})

    def delete_session(self, session_id: str) -> None:
        self.get_session(session_id)
        del self._sessions[session_id]

    def list_sessions(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda item: (item.updated_at, item.created_at), reverse=True)

    def touch_session(self, session_id: str) -> Session:
        return self._replace(session_id)

    def _replace(self, session_id: str, **updates: Any) -> Session:
        current = self.get_session(session_id)
        updated = current.model_copy(update={**updates, "updated_at": utc_now()})
        self._sessions[session_id] = updated
        return updated


class MessageStore:
    def __init__(self, session_store: SessionStore | None = None) -> None:
        self._messages: dict[str, MessageSchema] = {}
        self._session_ids: dict[str, list[str]] = {}
        self.session_store = session_store

    def add_message(
        self,
        session_id: str,
        role: str,
        content: Any = None,
        *,
        parts: list[dict[str, Any]] | None = None,
        run_id: str | None = None,
        parent_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        speaker_type: str | None = None,
        speaker_id: str | None = None,
        speaker_name: str | None = None,
        origin: str | None = None,
    ) -> MessageSchema:
        metadata = dict(metadata or {})
        speaker = infer_speaker_identity(
            role,
            metadata=metadata,
            speaker_type=speaker_type,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            origin=origin,
        )
        if parts is None:
            if content not in (None, ""):
                parts = [make_text_part(str(content), format="markdown" if role == "assistant" else "plain")]
            else:
                parts = []
        validated = validate_message_parts(parts)
        message = MessageSchema(
            message_id=str(uuid4()),
            session_id=session_id,
            role=role,
            **speaker,
            run_id=run_id,
            parts=validated,
            parent_message_id=parent_message_id,
            metadata=metadata,
        )
        self._messages[message.message_id] = message
        self._session_ids.setdefault(session_id, []).append(message.message_id)
        if self.session_store is not None:
            self.session_store.touch_session(session_id)
        return message

    def get_message(self, message_id: str) -> MessageSchema:
        try:
            return self._messages[message_id]
        except KeyError as exc:
            raise KeyError(f"unknown message id: {message_id}") from exc

    def update_message(self, message: MessageSchema) -> MessageSchema:
        self.get_message(message.message_id)
        self._messages[message.message_id] = MessageSchema.model_validate(message.model_dump())
        if self.session_store is not None:
            self.session_store.touch_session(message.session_id)
        return self._messages[message.message_id]

    def delete_message(self, message_id: str) -> MessageSchema:
        message = self.get_message(message_id)
        self._messages.pop(message_id, None)
        self._session_ids[message.session_id] = [item for item in self._session_ids.get(message.session_id, []) if item != message_id]
        if self.session_store is not None:
            self.session_store.touch_session(message.session_id)
        return message

    def delete_messages_after(self, session_id: str, message_id: str, include_target: bool = False) -> list[MessageSchema]:
        messages = self.list_messages(session_id)
        index = next((i for i, item in enumerate(messages) if item.message_id == message_id), None)
        if index is None:
            raise KeyError(f"unknown message id: {message_id}")
        deleted = messages[index if include_target else index + 1 :]
        for item in deleted:
            self._messages.pop(item.message_id, None)
        deleted_ids = {item.message_id for item in deleted}
        self._session_ids[session_id] = [item for item in self._session_ids.get(session_id, []) if item not in deleted_ids]
        if deleted and self.session_store is not None:
            self.session_store.touch_session(session_id)
        return deleted

    def list_messages(self, session_id: str) -> list[MessageSchema]:
        return [self._messages[item] for item in self._session_ids.get(session_id, []) if item in self._messages]

    def list_all_messages(self) -> list[MessageSchema]:
        return list(self._messages.values())

    def delete_session(self, session_id: str) -> None:
        for message_id in self._session_ids.pop(session_id, []):
            self._messages.pop(message_id, None)

    def find_latest_assistant_message(self, session_id: str) -> MessageSchema | None:
        for message in reversed(self.list_messages(session_id)):
            if message.role == "assistant":
                return message
        return None


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, RunSchema] = {}
        self._session_ids: dict[str, list[str]] = {}
        self._steps: dict[str, RunStepSchema] = {}
        self._step_ids: dict[str, list[str]] = {}

    def create_run(self, kind: str, target: str, session_id: str, metadata: dict[str, Any] | None = None) -> RunSchema:
        run = RunSchema(run_id=str(uuid4()), kind=kind, target=target, session_id=session_id, metadata=metadata or {})
        self._runs[run.run_id] = run
        self._session_ids.setdefault(session_id, []).append(run.run_id)
        return run

    def get_run(self, run_id: str) -> RunSchema:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"unknown run id: {run_id}") from exc

    def update_status(self, run_id: str, status: RunStatus, current_step: str | None = None, error: str | None = None, error_code: str | None = None, error_message: str | None = None, cancel_requested: bool | None = None) -> RunSchema:
        run = self.get_run(run_id)
        now = utc_now()
        updates: dict[str, Any] = {"status": status, "updated_at": now}
        if status == RunStatus.RUNNING and run.started_at is None:
            updates["started_at"] = now
        if status in {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}:
            updates["finished_at"] = now
        if current_step is not None:
            updates.update({"current_step": current_step, "stage": current_step})
        if error is not None:
            updates.update({"error": error, "error_message": error})
        if error_code is not None:
            updates["error_code"] = error_code
        if error_message is not None:
            updates.update({"error_message": error_message, "error": error_message})
        if cancel_requested is not None:
            updates["cancel_requested"] = cancel_requested
        updated = run.model_copy(update=updates)
        self._runs[run_id] = updated
        return updated

    def update_progress(self, run_id: str, stage: str | None = None, message: str | None = None, current: int | None = None, total: int | None = None) -> RunSchema:
        run = self.get_run(run_id)
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if stage is not None:
            updates.update({"stage": stage, "current_step": stage})
        if message is not None:
            updates["progress_message"] = message
        if current is not None:
            updates["progress_current"] = current
        if total is not None:
            updates["progress_total"] = total
        updated = run.model_copy(update=updates)
        self._runs[run_id] = updated
        return updated

    def update_metadata(self, run_id: str, metadata: dict[str, Any]) -> RunSchema:
        run = self.get_run(run_id)
        updated = run.model_copy(update={"metadata": dict(metadata), "updated_at": utc_now()})
        self._runs[run_id] = updated
        return updated

    def list_runs(self, session_id: str) -> list[RunSchema]:
        return [self._runs[item] for item in self._session_ids.get(session_id, []) if item in self._runs]

    def list_all_runs(self) -> list[RunSchema]:
        return sorted(self._runs.values(), key=lambda item: item.created_at)

    def delete_session(self, session_id: str) -> None:
        for run_id in self._session_ids.pop(session_id, []):
            self._runs.pop(run_id, None)
            for step_id in self._step_ids.pop(run_id, []):
                self._steps.pop(step_id, None)

    def cancel_runs(self, run_ids: list[str], reason: str = "Run was cancelled.") -> list[RunSchema]:
        result: list[RunSchema] = []
        for run_id in run_ids:
            if run_id not in self._runs:
                continue
            run = self._runs[run_id]
            if run.status in {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}:
                continue
            result.append(self.update_status(run_id, RunStatus.CANCELLED, current_step="cancelled", error=reason, error_code="RUN_CANCELLED", cancel_requested=True))
        return result

    def interrupt_unfinished_runs(self) -> list[str]:
        ids: list[str] = []
        for run_id, run in list(self._runs.items()):
            if run.status not in {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}:
                self._runs[run_id] = run.model_copy(update={"status": RunStatus.INTERRUPTED, "current_step": "interrupted", "finished_at": utc_now(), "updated_at": utc_now()})
                ids.append(run_id)
        return ids

    def create_step(self, run_id: str, kind: RunStepKind, label: str = "", message: str | None = None, metadata: dict[str, Any] | None = None, status: RunStepStatus = RunStepStatus.RUNNING, parent_step_id: str | None = None) -> RunStepSchema:
        self.get_run(run_id)
        if parent_step_id is not None and self.get_step(parent_step_id).run_id != run_id:
            raise ValueError("parent_step_id must belong to the same run")
        now = utc_now()
        step = RunStepSchema(step_id=str(uuid4()), run_id=run_id, kind=kind, parent_step_id=parent_step_id, label=label, status=status, message=message or "", order=len(self._step_ids.get(run_id, [])), started_at=now if status == RunStepStatus.RUNNING else None, metadata=metadata or {}, created_at=now, updated_at=now)
        self._steps[step.step_id] = step
        self._step_ids.setdefault(run_id, []).append(step.step_id)
        return step

    def update_step(self, step_id: str, status: RunStepStatus | None = None, message: str | None = None, error_code: str | None = None, error_message: str | None = None, metadata: dict[str, Any] | None = None) -> RunStepSchema:
        step = self.get_step(step_id)
        now = utc_now()
        updates: dict[str, Any] = {"updated_at": now}
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

    def list_steps(self, run_id: str) -> list[RunStepSchema]:
        return [self._steps[item] for item in self._step_ids.get(run_id, []) if item in self._steps]


class RunEventStore:
    def __init__(self) -> None:
        self._events: dict[str, RunEventSchema] = {}
        self._run_ids: dict[str, list[str]] = {}

    def add_event(self, run_id: str, session_id: str, type: str, message: str = "", payload: dict[str, Any] | None = None) -> RunEventSchema:
        event = RunEventSchema(event_id=str(uuid4()), run_id=run_id, session_id=session_id, type=type, message=message, payload=payload or {}, created_at=utc_now())
        self._events[event.event_id] = event
        self._run_ids.setdefault(run_id, []).append(event.event_id)
        return event

    def list_events(self, run_id: str) -> list[RunEventSchema]:
        return [self._events[item] for item in self._run_ids.get(run_id, []) if item in self._events]

    def delete_session(self, session_id: str) -> None:
        for event_id, event in list(self._events.items()):
            if event.session_id == session_id:
                self._events.pop(event_id, None)
                self._run_ids[event.run_id] = [item for item in self._run_ids.get(event.run_id, []) if item != event_id]


T = TypeVar("T")


class _ProfileStore(Generic[T]):
    schema_type: type[T]

    def __init__(self) -> None:
        self._records: dict[str, T] = {}

    def create(self, profile: T) -> T:
        profile_id = str(getattr(profile, "id"))
        if profile_id in self._records:
            raise ValueError(f"profile id already exists: {profile_id}")
        self._records[profile_id] = profile
        return profile

    def get(self, profile_id: str) -> T:
        try:
            return self._records[profile_id]
        except KeyError as exc:
            raise KeyError(f"unknown profile id: {profile_id}") from exc

    def find_by_alias(self, alias: str) -> T | None:
        key = str(alias).casefold()
        return next((item for item in self._records.values() if str(getattr(item, "alias", "")).casefold() == key), None)

    def get_by_id_or_alias(self, value: str) -> T:
        try:
            return self.get(value)
        except KeyError:
            found = self.find_by_alias(value)
            if found is None:
                raise KeyError(f"unknown profile: {value}")
            return found

    def update(self, value: str, updates: dict[str, Any]) -> T:
        current = self.get_by_id_or_alias(value)
        data = current.model_dump()
        data.update(updates)
        updated = type(current).model_validate(data)
        self._records[str(getattr(current, "id"))] = updated
        return updated

    def delete(self, value: str) -> T:
        current = self.get_by_id_or_alias(value)
        return self._records.pop(str(getattr(current, "id")))

    def list(self) -> list[T]:
        return sorted(self._records.values(), key=lambda item: (str(getattr(item, "name", "")), str(getattr(item, "id", ""))))


class LLMProfileStore(_ProfileStore[LLMProfileSchema]):
    pass


class ProviderProfileStore(_ProfileStore[ProviderProfileSchema]):
    pass


class MultimodalEmbeddingProfileStore(_ProfileStore[MultimodalEmbeddingModelProfile]):
    pass


class VisionProfileStore(_ProfileStore[VisionModelProfile]):
    pass


class LLMDefaultsStore:
    def __init__(self) -> None:
        self._values: dict[str, Optional[str]] = {"default_model_profile_id": None}

    def get(self) -> dict[str, Optional[str]]:
        return dict(self._values)

    def patch(self, values: dict[str, Any]) -> dict[str, Optional[str]]:
        if "default_model_profile_id" in values:
            value = values.get("default_model_profile_id")
            self._values["default_model_profile_id"] = str(value) if value else None
        return self.get()
