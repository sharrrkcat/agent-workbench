import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlmodel import Session as DbSession
from sqlmodel import delete
from sqlmodel import select

from ai_workbench.core.schema.llm_profile import LLMProfileSchema
from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.schema.run import RunSchema, RunStatus
from ai_workbench.core.schema.run_event import RunEventSchema
from ai_workbench.core.session import Session
from ai_workbench.db.models import (
    AgentConfigRecord,
    AppMetadataRecord,
    CapabilityConfigRecord,
    LLMProfileRecord,
    MessageRecord,
    RunEventRecord,
    RunRecord,
    SessionRecord,
)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: str, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


class SqlSessionStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def create_session(self, default_agent_id: str = "chat", title: str = "") -> Session:
        record = SessionRecord(session_id=str(uuid4()), title=title, default_agent_id=default_agent_id)
        with DbSession(self.engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
        return _session_from_record(record)

    def get_session(self, session_id: str) -> Session:
        with DbSession(self.engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is None:
                raise KeyError(f"unknown session id: {session_id}")
            return _session_from_record(record)

    def set_default_agent(self, session_id: str, agent_id: str) -> Session:
        with DbSession(self.engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is None:
                raise KeyError(f"unknown session id: {session_id}")
            record.default_agent_id = agent_id
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _session_from_record(record)

    def set_title(self, session_id: str, title: str) -> Session:
        with DbSession(self.engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is None:
                raise KeyError(f"unknown session id: {session_id}")
            record.title = title
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _session_from_record(record)

    def set_waiting_run(self, session_id: str, run_id: Optional[str]) -> Session:
        with DbSession(self.engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is None:
                raise KeyError(f"unknown session id: {session_id}")
            record.waiting_run_id = run_id
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _session_from_record(record)

    def set_llm_profile(self, session_id: str, profile_id: Optional[str]) -> Session:
        with DbSession(self.engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is None:
                raise KeyError(f"unknown session id: {session_id}")
            record.llm_profile_id = profile_id
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _session_from_record(record)

    def set_last_announced_llm_profile(self, session_id: str, profile_id: Optional[str]) -> Session:
        with DbSession(self.engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is None:
                raise KeyError(f"unknown session id: {session_id}")
            record.last_announced_llm_profile_id = profile_id
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _session_from_record(record)

    def clear_interrupted_waiting_runs(self, interrupted_run_ids: List[str]) -> None:
        if not interrupted_run_ids:
            return
        with DbSession(self.engine) as session:
            records = session.exec(select(SessionRecord).where(SessionRecord.waiting_run_id.in_(interrupted_run_ids))).all()
            for record in records:
                record.waiting_run_id = None
                record.updated_at = datetime.utcnow()
                session.add(record)
            session.commit()

    def delete_session(self, session_id: str) -> None:
        with DbSession(self.engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is None:
                raise KeyError(f"unknown session id: {session_id}")
            session.delete(record)
            session.commit()

    def list_sessions(self) -> List[Session]:
        with DbSession(self.engine) as session:
            records = session.exec(
                select(SessionRecord).order_by(SessionRecord.updated_at.desc(), SessionRecord.created_at.desc())
            ).all()
            return [_session_from_record(record) for record in records]


class SqlMessageStore:
    def __init__(self, engine) -> None:
        self.engine = engine

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
        record = MessageRecord(
            message_id=str(uuid4()),
            session_id=session_id,
            role=role,
            content_json=_dumps(content),
            output_type=output_type,
            agent_id=agent_id,
            command_name=command_name,
            action_id=action_id,
            run_id=run_id,
            parent_message_id=parent_message_id,
            available_actions_json=_dumps(available_actions or []),
            metadata_json=_dumps(metadata or {}),
        )
        with DbSession(self.engine) as session:
            session.add(record)
            session_record = session.get(SessionRecord, session_id)
            if session_record is not None:
                session_record.updated_at = datetime.utcnow()
                session.add(session_record)
            session.commit()
            session.refresh(record)
        return _message_from_record(record)

    def get_message(self, message_id: str) -> MessageSchema:
        with DbSession(self.engine) as session:
            record = session.get(MessageRecord, message_id)
            if record is None:
                raise KeyError(f"unknown message id: {message_id}")
            return _message_from_record(record)

    def update_message(self, message: MessageSchema) -> MessageSchema:
        with DbSession(self.engine) as session:
            record = session.get(MessageRecord, message.message_id)
            if record is None:
                raise KeyError(f"unknown message id: {message.message_id}")
            record.content_json = _dumps(message.content)
            record.output_type = message.output_type
            record.agent_id = message.agent_id
            record.command_name = message.command_name
            record.action_id = message.action_id
            record.run_id = message.run_id
            record.parent_message_id = message.parent_message_id
            record.available_actions_json = _dumps(message.available_actions)
            record.metadata_json = _dumps(message.metadata)
            session.add(record)
            session_record = session.get(SessionRecord, message.session_id)
            if session_record is not None:
                session_record.updated_at = datetime.utcnow()
                session.add(session_record)
            session.commit()
            session.refresh(record)
            return _message_from_record(record)

    def list_messages(self, session_id: str) -> List[MessageSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(
                select(MessageRecord).where(MessageRecord.session_id == session_id).order_by(MessageRecord.created_at)
            ).all()
            return [_message_from_record(record) for record in records]

    def delete_session(self, session_id: str) -> None:
        with DbSession(self.engine) as session:
            session.exec(delete(MessageRecord).where(MessageRecord.session_id == session_id))
            session.commit()

    def find_latest_assistant_message(self, session_id: str, agent_id: Optional[str] = None) -> Optional[MessageSchema]:
        messages = self.list_messages(session_id)
        for message in reversed(messages):
            if message.role != "assistant":
                continue
            if agent_id is not None and message.agent_id != agent_id:
                continue
            return message
        return None


class SqlRunStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def create_run(
        self,
        kind: str,
        target_id: str,
        session_id: str,
        action_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RunSchema:
        record = RunRecord(
            run_id=str(uuid4()),
            kind=kind,
            target_id=target_id,
            action_id=action_id,
            session_id=session_id,
            status=RunStatus.PENDING.value,
            metadata_json=_dumps(metadata or {}),
        )
        with DbSession(self.engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
        return _run_from_record(record)

    def get_run(self, run_id: str) -> RunSchema:
        with DbSession(self.engine) as session:
            record = session.get(RunRecord, run_id)
            if record is None:
                raise KeyError(f"unknown run id: {run_id}")
            return _run_from_record(record)

    def update_status(
        self,
        run_id: str,
        status: RunStatus,
        current_step: Optional[str] = None,
        error: Optional[str] = None,
    ) -> RunSchema:
        with DbSession(self.engine) as session:
            record = session.get(RunRecord, run_id)
            if record is None:
                raise KeyError(f"unknown run id: {run_id}")
            record.status = status.value if isinstance(status, RunStatus) else str(status)
            if current_step is not None:
                record.current_step = current_step
            if error is not None:
                record.error = error
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _run_from_record(record)

    def update_metadata(self, run_id: str, metadata: Dict[str, Any]) -> RunSchema:
        with DbSession(self.engine) as session:
            record = session.get(RunRecord, run_id)
            if record is None:
                raise KeyError(f"unknown run id: {run_id}")
            record.metadata_json = _dumps(metadata)
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _run_from_record(record)

    def list_runs(self, session_id: str) -> List[RunSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(select(RunRecord).where(RunRecord.session_id == session_id).order_by(RunRecord.created_at)).all()
            return [_run_from_record(record) for record in records]

    def delete_session(self, session_id: str) -> None:
        with DbSession(self.engine) as session:
            session.exec(delete(RunRecord).where(RunRecord.session_id == session_id))
            session.commit()

    def interrupt_unfinished_runs(self) -> List[str]:
        interrupted: List[str] = []
        with DbSession(self.engine) as session:
            records = session.exec(
                select(RunRecord).where(RunRecord.status.in_([RunStatus.RUNNING.value, RunStatus.WAITING_FOR_USER.value]))
            ).all()
            for record in records:
                record.status = RunStatus.INTERRUPTED.value
                record.error = "Server restarted before this run completed."
                record.current_step = "interrupted"
                record.updated_at = datetime.utcnow()
                interrupted.append(record.run_id)
                session.add(record)
            session.commit()
        return interrupted


class SqlRunEventStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def add_event(
        self,
        run_id: str,
        session_id: str,
        type: str,
        message: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> RunEventSchema:
        record = RunEventRecord(
            event_id=str(uuid4()),
            run_id=run_id,
            session_id=session_id,
            type=type,
            message=message,
            payload_json=_dumps(payload or {}),
        )
        with DbSession(self.engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
        return _run_event_from_record(record)

    def list_events(self, run_id: str) -> List[RunEventSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(
                select(RunEventRecord).where(RunEventRecord.run_id == run_id).order_by(RunEventRecord.created_at)
            ).all()
            return [_run_event_from_record(record) for record in records]

    def delete_session(self, session_id: str) -> None:
        with DbSession(self.engine) as session:
            session.exec(delete(RunEventRecord).where(RunEventRecord.session_id == session_id))
            session.commit()


class SqlAgentConfigStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def set_config(
        self,
        agent_id: str,
        enabled: Optional[bool] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with DbSession(self.engine) as session:
            record = session.get(AgentConfigRecord, agent_id)
            if record is None:
                record = AgentConfigRecord(agent_id=agent_id)
            if enabled is not None:
                record.enabled = enabled
            if user_config is not None:
                record.user_config_json = _dumps(user_config)
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _agent_config_from_record(record)

    def get_config(self, agent_id: str) -> Dict[str, Any]:
        with DbSession(self.engine) as session:
            record = session.get(AgentConfigRecord, agent_id)
            if record is None:
                return self.set_config(agent_id)
            return _agent_config_from_record(record)

    def list_configs(self) -> List[Dict[str, Any]]:
        with DbSession(self.engine) as session:
            records = session.exec(select(AgentConfigRecord).order_by(AgentConfigRecord.agent_id)).all()
            return [_agent_config_from_record(record) for record in records]

    def is_enabled(self, agent_id: str) -> bool:
        return bool(self.get_config(agent_id)["enabled"])


class SqlCapabilityConfigStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def set_config(
        self,
        capability_id: str,
        enabled: Optional[bool] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with DbSession(self.engine) as session:
            record = session.get(CapabilityConfigRecord, capability_id)
            if record is None:
                record = CapabilityConfigRecord(capability_id=capability_id)
            if enabled is not None:
                record.enabled = enabled
            if user_config is not None:
                record.user_config_json = _dumps(user_config)
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _capability_config_from_record(record)

    def get_config(self, capability_id: str) -> Dict[str, Any]:
        with DbSession(self.engine) as session:
            record = session.get(CapabilityConfigRecord, capability_id)
            if record is None:
                return self.set_config(capability_id)
            return _capability_config_from_record(record)

    def list_configs(self) -> List[Dict[str, Any]]:
        with DbSession(self.engine) as session:
            records = session.exec(select(CapabilityConfigRecord).order_by(CapabilityConfigRecord.capability_id)).all()
            return [_capability_config_from_record(record) for record in records]

    def is_enabled(self, capability_id: str) -> bool:
        return bool(self.get_config(capability_id)["enabled"])


class SqlLLMProfileStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def create(self, profile: LLMProfileSchema) -> LLMProfileSchema:
        with DbSession(self.engine) as session:
            if session.get(LLMProfileRecord, profile.id) is not None:
                raise ValueError(f"LLM profile id already exists: {profile.id}")
            if _find_profile_record_by_alias(session, profile.alias) is not None:
                raise ValueError(f"LLM profile alias already exists: {profile.alias}")
            record = _profile_to_record(profile)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _profile_from_record(record)

    def get(self, profile_id: str) -> LLMProfileSchema:
        with DbSession(self.engine) as session:
            record = session.get(LLMProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown LLM profile id: {profile_id}")
            return _profile_from_record(record)

    def find_by_alias(self, alias: str) -> Optional[LLMProfileSchema]:
        with DbSession(self.engine) as session:
            record = _find_profile_record_by_alias(session, alias)
            return _profile_from_record(record) if record is not None else None

    def get_by_id_or_alias(self, profile_id_or_alias: str) -> LLMProfileSchema:
        with DbSession(self.engine) as session:
            record = session.get(LLMProfileRecord, profile_id_or_alias)
            if record is None:
                record = _find_profile_record_by_alias(session, profile_id_or_alias)
            if record is None:
                raise KeyError(f"unknown LLM profile: {profile_id_or_alias}")
            return _profile_from_record(record)

    def update(self, profile_id_or_alias: str, values: Dict[str, Any]) -> LLMProfileSchema:
        with DbSession(self.engine) as session:
            record = session.get(LLMProfileRecord, profile_id_or_alias)
            if record is None:
                record = _find_profile_record_by_alias(session, profile_id_or_alias)
            if record is None:
                raise KeyError(f"unknown LLM profile: {profile_id_or_alias}")
            alias = values.get("alias")
            if alias is not None:
                conflict = _find_profile_record_by_alias(session, str(alias))
                if conflict is not None and conflict.id != record.id:
                    raise ValueError(f"LLM profile alias already exists: {alias}")
            candidate = _profile_from_record(record).model_copy(update={**values, "updated_at": datetime.utcnow()})
            profile = LLMProfileSchema.model_validate(candidate.model_dump())
            _apply_profile_to_record(record, profile)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _profile_from_record(record)

    def delete(self, profile_id_or_alias: str) -> LLMProfileSchema:
        with DbSession(self.engine) as session:
            record = session.get(LLMProfileRecord, profile_id_or_alias)
            if record is None:
                record = _find_profile_record_by_alias(session, profile_id_or_alias)
            if record is None:
                raise KeyError(f"unknown LLM profile: {profile_id_or_alias}")
            profile = _profile_from_record(record)
            session.delete(record)
            session.commit()
            return profile

    def list(self) -> List[LLMProfileSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(select(LLMProfileRecord).order_by(LLMProfileRecord.alias)).all()
            return [_profile_from_record(record) for record in records]


class SqlAppMetadataStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def get(self, key: str) -> str:
        with DbSession(self.engine) as session:
            record = session.get(AppMetadataRecord, key)
            if record is None:
                raise KeyError(f"unknown app metadata key: {key}")
            return record.value


def _session_from_record(record: SessionRecord) -> Session:
    return Session(
        session_id=record.session_id,
        title=record.title,
        default_agent_id=record.default_agent_id,
        waiting_run_id=record.waiting_run_id,
        llm_profile_id=record.llm_profile_id,
        last_announced_llm_profile_id=record.last_announced_llm_profile_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _message_from_record(record: MessageRecord) -> MessageSchema:
    return MessageSchema(
        message_id=record.message_id,
        session_id=record.session_id,
        role=record.role,
        content=_loads(record.content_json, ""),
        output_type=record.output_type,
        agent_id=record.agent_id,
        command_name=record.command_name,
        action_id=record.action_id,
        run_id=record.run_id,
        parent_message_id=record.parent_message_id,
        available_actions=_loads(record.available_actions_json, []),
        metadata=_loads(record.metadata_json, {}),
        created_at=record.created_at,
    )


def _run_from_record(record: RunRecord) -> RunSchema:
    return RunSchema(
        run_id=record.run_id,
        kind=record.kind,
        target_id=record.target_id,
        action_id=record.action_id,
        session_id=record.session_id,
        status=RunStatus(record.status),
        current_step=record.current_step,
        error=record.error,
        metadata=_loads(record.metadata_json, {}),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _run_event_from_record(record: RunEventRecord) -> RunEventSchema:
    return RunEventSchema(
        event_id=record.event_id,
        run_id=record.run_id,
        session_id=record.session_id,
        type=record.type,
        message=record.message,
        payload=_loads(record.payload_json, {}),
        created_at=record.created_at,
    )


def _agent_config_from_record(record: AgentConfigRecord) -> Dict[str, Any]:
    return {
        "agent_id": record.agent_id,
        "enabled": record.enabled,
        "user_config": _loads(record.user_config_json, {}),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _capability_config_from_record(record: CapabilityConfigRecord) -> Dict[str, Any]:
    return {
        "capability_id": record.capability_id,
        "enabled": record.enabled,
        "user_config": _loads(record.user_config_json, {}),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _find_profile_record_by_alias(session: DbSession, alias: str) -> Optional[LLMProfileRecord]:
    return session.exec(select(LLMProfileRecord).where(LLMProfileRecord.alias == alias)).first()


def _profile_to_record(profile: LLMProfileSchema) -> LLMProfileRecord:
    return LLMProfileRecord(**profile.model_dump())


def _apply_profile_to_record(record: LLMProfileRecord, profile: LLMProfileSchema) -> None:
    for key, value in profile.model_dump().items():
        setattr(record, key, value)


def _profile_from_record(record: LLMProfileRecord) -> LLMProfileSchema:
    return LLMProfileSchema(
        id=record.id,
        alias=record.alias,
        name=record.name,
        provider=record.provider,
        base_url=record.base_url,
        api_key=record.api_key,
        model_id=record.model_id,
        enabled=record.enabled,
        temperature=record.temperature,
        top_p=record.top_p,
        top_k=record.top_k,
        max_tokens=record.max_tokens,
        timeout=record.timeout,
        supports_vision=record.supports_vision,
        supports_tools=record.supports_tools,
        supports_reasoning=record.supports_reasoning,
        supports_streaming=record.supports_streaming,
        supports_json_mode=record.supports_json_mode,
        notes=record.notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
