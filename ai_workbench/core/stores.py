from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.schema.llm_profile import LLMProfileSchema
from ai_workbench.core.schema.run import RunSchema, RunStatus
from ai_workbench.core.schema.run_event import RunEventSchema
from ai_workbench.core.session import Session


class SessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}

    def create_session(self, default_agent_id: str = "chat", title: str = "") -> Session:
        session = Session(
            session_id=str(uuid4()),
            title=title,
            default_agent_id=default_agent_id,
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
        updated = session.model_copy(update={"default_agent_id": agent_id, "updated_at": datetime.utcnow()})
        self._sessions[session_id] = updated
        return updated

    def set_title(self, session_id: str, title: str) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(update={"title": title, "updated_at": datetime.utcnow()})
        self._sessions[session_id] = updated
        return updated

    def set_waiting_run(self, session_id: str, run_id: Optional[str]) -> Session:
        session = self.get_session(session_id)
        updated = session.model_copy(update={"waiting_run_id": run_id, "updated_at": datetime.utcnow()})
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
        updated = session.model_copy(update={"updated_at": datetime.utcnow()})
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
        output_type: str = "text",
        available_actions: Optional[List[Dict[str, Any]]] = None,
        parent_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MessageSchema:
        message = MessageSchema(
            message_id=str(uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            agent_id=agent_id,
            command_name=command_name,
            action_id=action_id,
            run_id=run_id,
            output_type=output_type,
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

    def list_messages(self, session_id: str) -> List[MessageSchema]:
        return [self._messages[message_id] for message_id in self._session_message_ids.get(session_id, [])]

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
    ) -> RunSchema:
        run = self.get_run(run_id)
        updates: Dict[str, Any] = {"status": status, "updated_at": datetime.utcnow()}
        if current_step is not None:
            updates["current_step"] = current_step
        if error is not None:
            updates["error"] = error
        updated = run.model_copy(update=updates)
        self._runs[run_id] = updated
        return updated

    def update_metadata(self, run_id: str, metadata: Dict[str, Any]) -> RunSchema:
        run = self.get_run(run_id)
        updated = run.model_copy(update={"metadata": metadata, "updated_at": datetime.utcnow()})
        self._runs[run_id] = updated
        return updated

    def list_runs(self, session_id: str) -> List[RunSchema]:
        return [self._runs[run_id] for run_id in self._session_run_ids.get(session_id, [])]

    def delete_session(self, session_id: str) -> None:
        run_ids = self._session_run_ids.pop(session_id, [])
        for run_id in run_ids:
            self._runs.pop(run_id, None)


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
            created_at=datetime.utcnow(),
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
    ) -> Dict[str, Any]:
        now = datetime.utcnow()
        record = self._records.get(item_id)
        if record is None:
            record = {
                self.id_field: item_id,
                "enabled": True,
                "user_config": {},
                "created_at": now,
                "updated_at": now,
            }
        if enabled is not None:
            record["enabled"] = enabled
        if user_config is not None:
            record["user_config"] = user_config
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
        updated = existing.model_copy(update={**values, "updated_at": datetime.utcnow()})
        updated = LLMProfileSchema.model_validate(updated.model_dump())
        self._records[existing.id] = updated
        return updated

    def delete(self, profile_id_or_alias: str) -> LLMProfileSchema:
        existing = self.get_by_id_or_alias(profile_id_or_alias)
        del self._records[existing.id]
        return existing

    def list(self) -> List[LLMProfileSchema]:
        return sorted(self._records.values(), key=lambda item: (item.alias, item.created_at))
