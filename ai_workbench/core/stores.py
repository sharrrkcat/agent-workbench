from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.schema.run import RunSchema, RunStatus
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

    def list_sessions(self) -> List[Session]:
        return list(self._sessions.values())


class MessageStore:
    def __init__(self) -> None:
        self._messages: Dict[str, MessageSchema] = {}
        self._session_message_ids: Dict[str, List[str]] = {}

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
        return message

    def list_messages(self, session_id: str) -> List[MessageSchema]:
        return [self._messages[message_id] for message_id in self._session_message_ids.get(session_id, [])]

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
