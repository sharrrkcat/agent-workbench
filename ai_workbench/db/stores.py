import json
from array import array
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlmodel import Session as DbSession
from sqlmodel import delete
from sqlmodel import select
from sqlmodel import update

from ai_workbench.core.schema.llm_profile import LLMProfileSchema, ProviderProfileSchema
from ai_workbench.core.schema.message import MessageSchema, infer_speaker_identity
from ai_workbench.core.schema.run import RunSchema, RunStatus, RunStepSchema, RunStepStatus
from ai_workbench.core.schema.run_event import RunEventSchema
from ai_workbench.core.session import Session
from ai_workbench.core.settings import AppSettings, AppSettingsPatch, app_settings_patch_updates
from ai_workbench.core.knowledge_settings import KnowledgeSettings, KnowledgeSettingsPatch, knowledge_settings_patch_updates
from ai_workbench.core.knowledge_store import (
    EmbeddingModelProfile,
    KnowledgeBase,
    KnowledgeSource,
    KnowledgeSourceIndexResult,
    SessionKnowledgeBinding,
)
from ai_workbench.core.time import ensure_utc, utc_now
from ai_workbench.core.session_titles import is_default_session_title
from ai_workbench.db.models import (
    AgentConfigRecord,
    AppMetadataRecord,
    CapabilityConfigRecord,
    EmbeddingModelProfileRecord,
    KnowledgeBaseRecord,
    KnowledgeChunkRecord,
    KnowledgeEmbeddingRecord,
    KnowledgeSettingsRecord,
    KnowledgeSourceRecord,
    LLMProfileRecord,
    MessageRecord,
    ProviderProfileRecord,
    RunEventRecord,
    RunRecord,
    RunStepRecord,
    SessionRecord,
    SessionAgentStateRecord,
    SessionKnowledgeBindingRecord,
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

    def create_session(self, default_agent_id: str = "chat", title: str = "", context_mode: str = "single_assistant") -> Session:
        record = SessionRecord(
            session_id=str(uuid4()),
            title=title,
            default_agent_id=default_agent_id,
            context_mode=context_mode,
            title_generation_state="pending" if is_default_session_title(title) else "manual",
        )
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
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _session_from_record(record)

    def set_context_mode(self, session_id: str, context_mode: str) -> Session:
        with DbSession(self.engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is None:
                raise KeyError(f"unknown session id: {session_id}")
            record.context_mode = context_mode
            record.updated_at = utc_now()
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
            record.title_generation_state = "manual"
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _session_from_record(record)

    def set_generated_title(self, session_id: str, title: str, metadata: Optional[Dict[str, Any]] = None) -> Session:
        with DbSession(self.engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is None:
                raise KeyError(f"unknown session id: {session_id}")
            record.title = title
            record.title_generation_state = "done"
            record.title_generation_metadata_json = _dumps(metadata or {})
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _session_from_record(record)

    def set_title_generation_state(self, session_id: str, state: str, metadata: Optional[Dict[str, Any]] = None) -> Session:
        with DbSession(self.engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is None:
                raise KeyError(f"unknown session id: {session_id}")
            record.title_generation_state = state
            record.title_generation_metadata_json = _dumps(metadata or {})
            record.updated_at = utc_now()
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
            record.updated_at = utc_now()
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
            record.updated_at = utc_now()
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
            record.updated_at = utc_now()
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
                record.updated_at = utc_now()
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
        record = MessageRecord(
            message_id=str(uuid4()),
            session_id=session_id,
            role=role,
            content_json=_dumps(content),
            speaker_type=speaker["speaker_type"],
            speaker_id=speaker["speaker_id"],
            speaker_name=speaker["speaker_name"],
            origin=speaker["origin"],
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
                session_record.updated_at = utc_now()
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
            record.speaker_type = message.speaker_type
            record.speaker_id = message.speaker_id
            record.speaker_name = message.speaker_name
            record.origin = message.origin
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
                session_record.updated_at = utc_now()
                session.add(session_record)
            session.commit()
            session.refresh(record)
            return _message_from_record(record)

    def delete_message(self, message_id: str) -> MessageSchema:
        with DbSession(self.engine) as session:
            record = session.get(MessageRecord, message_id)
            if record is None:
                raise KeyError(f"unknown message id: {message_id}")
            message = _message_from_record(record)
            session.delete(record)
            session_record = session.get(SessionRecord, message.session_id)
            if session_record is not None:
                session_record.updated_at = utc_now()
                session.add(session_record)
            session.commit()
            return message

    def delete_messages_after(self, session_id: str, message_id: str, include_target: bool = False) -> List[MessageSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(
                select(MessageRecord).where(MessageRecord.session_id == session_id).order_by(MessageRecord.created_at)
            ).all()
            index = next((idx for idx, record in enumerate(records) if record.message_id == message_id), None)
            if index is None:
                raise KeyError(f"unknown message id: {message_id}")
            start = index if include_target else index + 1
            deleted_records = records[start:]
            deleted = [_message_from_record(record) for record in deleted_records]
            for record in deleted_records:
                session.delete(record)
            if deleted_records:
                session_record = session.get(SessionRecord, session_id)
                if session_record is not None:
                    session_record.updated_at = utc_now()
                    session.add(session_record)
            session.commit()
            return deleted

    def list_messages(self, session_id: str) -> List[MessageSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(
                select(MessageRecord).where(MessageRecord.session_id == session_id).order_by(MessageRecord.created_at)
            ).all()
            return [_message_from_record(record) for record in records]

    def list_all_messages(self) -> List[MessageSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(select(MessageRecord).order_by(MessageRecord.created_at)).all()
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
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        cancel_requested: Optional[bool] = None,
    ) -> RunSchema:
        with DbSession(self.engine) as session:
            record = session.get(RunRecord, run_id)
            if record is None:
                raise KeyError(f"unknown run id: {run_id}")
            record.status = status.value if isinstance(status, RunStatus) else str(status)
            now = utc_now()
            if record.status == RunStatus.RUNNING.value and record.started_at is None:
                record.started_at = now
            if record.status in {RunStatus.DONE.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value, RunStatus.INTERRUPTED.value}:
                record.finished_at = now
            if current_step is not None:
                record.current_step = current_step
                record.stage = current_step
            if error is not None:
                record.error = error
                record.error_message = error
            if error_code is not None:
                record.error_code = error_code
            if error_message is not None:
                record.error_message = error_message
                record.error = error_message
            if cancel_requested is not None:
                record.cancel_requested = cancel_requested
            record.updated_at = now
            session.add(record)
            session.commit()
            session.refresh(record)
            return _run_from_record(record)

    def update_progress(
        self,
        run_id: str,
        stage: Optional[str] = None,
        message: Optional[str] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
    ) -> RunSchema:
        with DbSession(self.engine) as session:
            record = session.get(RunRecord, run_id)
            if record is None:
                raise KeyError(f"unknown run id: {run_id}")
            if stage is not None:
                record.stage = stage
                record.current_step = stage
            if message is not None:
                record.progress_message = message
            if current is not None:
                record.progress_current = current
            if total is not None:
                record.progress_total = total
            record.updated_at = utc_now()
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
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _run_from_record(record)

    def list_runs(self, session_id: str) -> List[RunSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(select(RunRecord).where(RunRecord.session_id == session_id).order_by(RunRecord.created_at)).all()
            return [_run_from_record(record) for record in records]

    def list_all_runs(self) -> List[RunSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(select(RunRecord).order_by(RunRecord.created_at)).all()
            return [_run_from_record(record) for record in records]

    def delete_session(self, session_id: str) -> None:
        with DbSession(self.engine) as session:
            run_ids = [record.run_id for record in session.exec(select(RunRecord).where(RunRecord.session_id == session_id)).all()]
            if run_ids:
                session.exec(delete(RunStepRecord).where(RunStepRecord.run_id.in_(run_ids)))
            session.exec(delete(RunRecord).where(RunRecord.session_id == session_id))
            session.commit()

    def cancel_runs(self, run_ids: List[str], reason: str = "Messages were removed.") -> List[RunSchema]:
        if not run_ids:
            return []
        cancelled: List[RunSchema] = []
        with DbSession(self.engine) as session:
            records = session.exec(select(RunRecord).where(RunRecord.run_id.in_(run_ids))).all()
            for record in records:
                if record.status in {RunStatus.CANCELLED.value, RunStatus.INTERRUPTED.value}:
                    continue
                record.status = RunStatus.CANCELLED.value
                record.current_step = "cancelled"
                record.error = reason
                record.updated_at = utc_now()
                session.add(record)
                cancelled.append(_run_from_record(record))
            session.commit()
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
        now = utc_now()
        status_value = status.value if isinstance(status, RunStepStatus) else str(status)
        with DbSession(self.engine) as session:
            if session.get(RunRecord, run_id) is None:
                raise KeyError(f"unknown run id: {run_id}")
            if parent_step_id is not None:
                parent = session.get(RunStepRecord, parent_step_id)
                if parent is None:
                    raise KeyError(f"unknown parent run step id: {parent_step_id}")
                if parent.run_id != run_id:
                    raise ValueError("parent_step_id must belong to the same run")
            order = len(session.exec(select(RunStepRecord).where(RunStepRecord.run_id == run_id)).all())
            record = RunStepRecord(
                step_id=str(uuid4()),
                run_id=run_id,
                parent_step_id=parent_step_id,
                label=label,
                status=status_value,
                message=message or "",
                order=order,
                started_at=now if status_value == RunStepStatus.RUNNING.value else None,
                metadata_json=_dumps(metadata or {}),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return _run_step_from_record(record)

    def update_step(
        self,
        step_id: str,
        status: Optional[RunStepStatus] = None,
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RunStepSchema:
        with DbSession(self.engine) as session:
            record = session.get(RunStepRecord, step_id)
            if record is None:
                raise KeyError(f"unknown run step id: {step_id}")
            now = utc_now()
            if status is not None:
                record.status = status.value if isinstance(status, RunStepStatus) else str(status)
                if record.status == RunStepStatus.RUNNING.value and record.started_at is None:
                    record.started_at = now
                if record.status in {RunStepStatus.COMPLETED.value, RunStepStatus.FAILED.value, RunStepStatus.SKIPPED.value}:
                    record.finished_at = now
            if message is not None:
                record.message = message
            if error_code is not None:
                record.error_code = error_code
            if error_message is not None:
                record.error_message = error_message
            if metadata is not None:
                record.metadata_json = _dumps({**_loads(record.metadata_json, {}), **metadata})
            record.updated_at = now
            session.add(record)
            session.commit()
            session.refresh(record)
            return _run_step_from_record(record)

    def get_step(self, step_id: str) -> RunStepSchema:
        with DbSession(self.engine) as session:
            record = session.get(RunStepRecord, step_id)
            if record is None:
                raise KeyError(f"unknown run step id: {step_id}")
            return _run_step_from_record(record)

    def list_steps(self, run_id: str) -> List[RunStepSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(select(RunStepRecord).where(RunStepRecord.run_id == run_id).order_by(RunStepRecord.order, RunStepRecord.created_at)).all()
            return [_run_step_from_record(record) for record in records]

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
                record.updated_at = utc_now()
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
        display: Optional[Dict[str, Any]] = None,
        runtime: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with DbSession(self.engine) as session:
            record = session.get(AgentConfigRecord, agent_id)
            if record is None:
                record = AgentConfigRecord(agent_id=agent_id)
            if enabled is not None:
                record.enabled = enabled
            if user_config is not None:
                record.user_config_json = _dumps(user_config)
            if display is not None:
                record.display_json = _dumps(display)
            if runtime is not None:
                record.runtime_json = _dumps(runtime)
            record.updated_at = utc_now()
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
            record.updated_at = utc_now()
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


class SqlSessionAgentStateStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def get_state(self, session_id: str, agent_id: str, key: str) -> Any:
        with DbSession(self.engine) as session:
            record = session.exec(
                select(SessionAgentStateRecord).where(
                    SessionAgentStateRecord.session_id == session_id,
                    SessionAgentStateRecord.agent_id == agent_id,
                    SessionAgentStateRecord.key == key,
                )
            ).first()
            if record is None:
                return None
            return _loads(record.value_json, None)

    def set_state(self, session_id: str, agent_id: str, key: str, value: Any) -> Any:
        with DbSession(self.engine) as session:
            record = session.exec(
                select(SessionAgentStateRecord).where(
                    SessionAgentStateRecord.session_id == session_id,
                    SessionAgentStateRecord.agent_id == agent_id,
                    SessionAgentStateRecord.key == key,
                )
            ).first()
            if record is None:
                record = SessionAgentStateRecord(session_id=session_id, agent_id=agent_id, key=key)
            record.value_json = _dumps(value)
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            return _loads(record.value_json, None)

    def delete_session(self, session_id: str) -> None:
        with DbSession(self.engine) as session:
            session.exec(delete(SessionAgentStateRecord).where(SessionAgentStateRecord.session_id == session_id))
            session.commit()


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
            candidate = _profile_from_record(record).model_copy(update={**values, "updated_at": utc_now()})
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


class SqlProviderProfileStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def create(self, profile: ProviderProfileSchema) -> ProviderProfileSchema:
        with DbSession(self.engine) as session:
            if session.get(ProviderProfileRecord, profile.id) is not None:
                raise ValueError(f"Provider profile id already exists: {profile.id}")
            record = _provider_to_record(profile)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _provider_from_record(record)

    def get(self, profile_id: str) -> ProviderProfileSchema:
        with DbSession(self.engine) as session:
            record = session.get(ProviderProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown provider profile id: {profile_id}")
            return _provider_from_record(record)

    def update(self, profile_id: str, values: Dict[str, Any]) -> ProviderProfileSchema:
        with DbSession(self.engine) as session:
            record = session.get(ProviderProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown provider profile id: {profile_id}")
            candidate = _provider_from_record(record).model_copy(update={**values, "updated_at": utc_now()})
            profile = ProviderProfileSchema.model_validate(candidate.model_dump())
            _apply_provider_to_record(record, profile)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _provider_from_record(record)

    def delete(self, profile_id: str) -> ProviderProfileSchema:
        with DbSession(self.engine) as session:
            record = session.get(ProviderProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown provider profile id: {profile_id}")
            profile = _provider_from_record(record)
            session.delete(record)
            session.commit()
            return profile

    def list(self) -> List[ProviderProfileSchema]:
        with DbSession(self.engine) as session:
            records = session.exec(select(ProviderProfileRecord).order_by(ProviderProfileRecord.name)).all()
            return [_provider_from_record(record) for record in records]


class SqlAppMetadataStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def get(self, key: str) -> str:
        with DbSession(self.engine) as session:
            record = session.get(AppMetadataRecord, key)
            if record is None:
                raise KeyError(f"unknown app metadata key: {key}")
            return record.value


class SqlAppSettingsStore:
    SETTINGS_KEY = "app_settings"

    def __init__(self, engine) -> None:
        self.engine = engine

    def get(self) -> AppSettings:
        with DbSession(self.engine) as session:
            record = session.get(AppMetadataRecord, self.SETTINGS_KEY)
            if record is None:
                return AppSettings()
            return AppSettings.model_validate(_loads(record.value, {}))

    def patch(self, values: Dict[str, Any]) -> AppSettings:
        patch = AppSettingsPatch.model_validate(values)
        updates = app_settings_patch_updates(patch)
        with DbSession(self.engine) as session:
            record = session.get(AppMetadataRecord, self.SETTINGS_KEY)
            current = AppSettings()
            if record is not None:
                current = AppSettings.model_validate(_loads(record.value, {}))
            next_settings = AppSettings.model_validate({**current.model_dump(), **updates})
            if record is None:
                record = AppMetadataRecord(key=self.SETTINGS_KEY, value=_dumps(next_settings.model_dump()))
            else:
                record.value = _dumps(next_settings.model_dump())
                record.updated_at = utc_now()
            session.add(record)
            session.commit()
            return next_settings


class SqlLLMDefaultsStore:
    SETTINGS_KEY = "llm_defaults"

    def __init__(self, engine) -> None:
        self.engine = engine

    def get(self) -> Dict[str, Optional[str]]:
        with DbSession(self.engine) as session:
            record = session.get(AppMetadataRecord, self.SETTINGS_KEY)
            if record is None:
                return {"default_model_profile_id": None}
            payload = _loads(record.value, {})
            return {"default_model_profile_id": payload.get("default_model_profile_id") or None}

    def patch(self, values: Dict[str, Any]) -> Dict[str, Optional[str]]:
        allowed = {"default_model_profile_id"}
        extra = set(values) - allowed
        if extra:
            raise ValueError(f"unknown LLM defaults field: {sorted(extra)[0]}")
        next_values = self.get()
        if "default_model_profile_id" in values:
            value = values.get("default_model_profile_id")
            next_values["default_model_profile_id"] = str(value) if value else None
        with DbSession(self.engine) as session:
            record = session.get(AppMetadataRecord, self.SETTINGS_KEY)
            if record is None:
                record = AppMetadataRecord(key=self.SETTINGS_KEY, value=_dumps(next_values))
            else:
                record.value = _dumps(next_values)
                record.updated_at = utc_now()
            session.add(record)
            session.commit()
        return next_values


class SqlKnowledgeStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def get_settings(self) -> KnowledgeSettings:
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeSettingsRecord, 1)
            if record is None:
                record = KnowledgeSettingsRecord(id=1)
                session.add(record)
                session.commit()
                session.refresh(record)
            return _knowledge_settings_from_record(record)

    def patch_settings(self, values: Dict[str, Any]) -> KnowledgeSettings:
        patch = KnowledgeSettingsPatch.model_validate(values)
        updates = knowledge_settings_patch_updates(patch)
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeSettingsRecord, 1)
            if record is None:
                record = KnowledgeSettingsRecord(id=1)
            current = _knowledge_settings_from_record(record)
            chunk_defaults_changed = any(
                key in updates and getattr(current, key) != updates[key]
                for key in ("default_chunk_size", "default_chunk_overlap")
            )
            next_settings = KnowledgeSettings.model_validate({**current.model_dump(), **updates})
            _apply_knowledge_settings_to_record(record, next_settings)
            record.updated_at = utc_now()
            session.add(record)
            if chunk_defaults_changed:
                _mark_kbs_using_default_chunking_needs_reindex(session)
            session.commit()
            session.refresh(record)
            return _knowledge_settings_from_record(record)

    def list_embedding_profiles(self) -> List[EmbeddingModelProfile]:
        with DbSession(self.engine) as session:
            records = session.exec(select(EmbeddingModelProfileRecord).order_by(EmbeddingModelProfileRecord.alias)).all()
            return [_embedding_profile_from_record(record) for record in records]

    def create_embedding_profile(self, profile: EmbeddingModelProfile) -> EmbeddingModelProfile:
        with DbSession(self.engine) as session:
            if session.get(EmbeddingModelProfileRecord, profile.id) is not None:
                raise ValueError("KNOWLEDGE_EMBEDDING_ID_EXISTS")
            if _find_embedding_profile_by_alias(session, profile.alias) is not None:
                raise ValueError("KNOWLEDGE_EMBEDDING_ALIAS_EXISTS")
            record = EmbeddingModelProfileRecord(**profile.model_dump())
            session.add(record)
            session.commit()
            session.refresh(record)
            return _embedding_profile_from_record(record)

    def get_embedding_profile(self, profile_id: str) -> EmbeddingModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(EmbeddingModelProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown embedding model profile: {profile_id}")
            return _embedding_profile_from_record(record)

    def update_embedding_profile(self, profile_id: str, values: Dict[str, Any]) -> EmbeddingModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(EmbeddingModelProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown embedding model profile: {profile_id}")
            alias = values.get("alias")
            if alias is not None:
                conflict = _find_embedding_profile_by_alias(session, str(alias))
                if conflict is not None and conflict.id != record.id:
                    raise ValueError("KNOWLEDGE_EMBEDDING_ALIAS_EXISTS")
            stale_keys = {"model_path", "dimension", "normalize", "document_instruction"}
            needs_reindex = any(key in values and getattr(record, key) != values[key] for key in stale_keys)
            candidate = _embedding_profile_from_record(record).model_copy(update={**values, "updated_at": utc_now()})
            profile = EmbeddingModelProfile.model_validate(candidate.model_dump())
            for key, value in profile.model_dump().items():
                setattr(record, key, value)
            session.add(record)
            if needs_reindex:
                _mark_kbs_for_profile_needs_reindex(session, record.id)
            session.commit()
            session.refresh(record)
            return _embedding_profile_from_record(record)

    def delete_embedding_profile(self, profile_id: str) -> EmbeddingModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(EmbeddingModelProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown embedding model profile: {profile_id}")
            in_use = session.exec(
                select(KnowledgeBaseRecord).where(KnowledgeBaseRecord.embedding_model_profile_id == record.id)
            ).first()
            if in_use is not None:
                raise ValueError("KNOWLEDGE_EMBEDDING_MODEL_IN_USE")
            profile = _embedding_profile_from_record(record)
            session.delete(record)
            session.commit()
            return profile

    def list_knowledge_bases(self) -> List[KnowledgeBase]:
        with DbSession(self.engine) as session:
            records = session.exec(select(KnowledgeBaseRecord).order_by(KnowledgeBaseRecord.name)).all()
            return [_knowledge_base_from_record(record) for record in records]

    def create_knowledge_base(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        with DbSession(self.engine) as session:
            if session.get(KnowledgeBaseRecord, knowledge_base.id) is not None:
                raise ValueError("KNOWLEDGE_BASE_ID_EXISTS")
            record = KnowledgeBaseRecord(**knowledge_base.model_dump())
            session.add(record)
            session.commit()
            session.refresh(record)
            return _knowledge_base_from_record(record)

    def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeBaseRecord, knowledge_base_id)
            if record is None:
                raise KeyError(f"unknown knowledge base: {knowledge_base_id}")
            return _knowledge_base_from_record(record)

    def update_knowledge_base(self, knowledge_base_id: str, values: Dict[str, Any]) -> KnowledgeBase:
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeBaseRecord, knowledge_base_id)
            if record is None:
                raise KeyError(f"unknown knowledge base: {knowledge_base_id}")
            stale_keys = {"embedding_model_profile_id", "chunk_size_override", "chunk_overlap_override"}
            needs_reindex = any(key in values and getattr(record, key) != values[key] for key in stale_keys)
            candidate = _knowledge_base_from_record(record).model_copy(update={**values, "updated_at": utc_now()})
            knowledge_base = KnowledgeBase.model_validate(candidate.model_dump())
            for key, value in knowledge_base.model_dump().items():
                setattr(record, key, value)
            if needs_reindex:
                _mark_kb_needs_reindex(session, record.id)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _knowledge_base_from_record(record)

    def delete_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeBaseRecord, knowledge_base_id)
            if record is None:
                raise KeyError(f"unknown knowledge base: {knowledge_base_id}")
            knowledge_base = _knowledge_base_from_record(record)
            source_ids = [
                item.id
                for item in session.exec(
                    select(KnowledgeSourceRecord).where(KnowledgeSourceRecord.knowledge_base_id == record.id)
                ).all()
            ]
            for source_id in source_ids:
                _delete_source_index_rows(session, source_id)
            session.exec(delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.knowledge_base_id == record.id))
            session.exec(delete(SessionKnowledgeBindingRecord).where(SessionKnowledgeBindingRecord.knowledge_base_id == record.id))
            session.delete(record)
            session.commit()
            return knowledge_base

    def list_sources(self, knowledge_base_id: str) -> List[KnowledgeSource]:
        with DbSession(self.engine) as session:
            if session.get(KnowledgeBaseRecord, knowledge_base_id) is None:
                raise KeyError(f"unknown knowledge base: {knowledge_base_id}")
            records = session.exec(
                select(KnowledgeSourceRecord)
                .where(KnowledgeSourceRecord.knowledge_base_id == knowledge_base_id)
                .where(KnowledgeSourceRecord.status != "deleted")
                .order_by(KnowledgeSourceRecord.created_at)
            ).all()
            return [_knowledge_source_from_record(session, record) for record in records]

    def get_source(self, source_id: str) -> KnowledgeSource:
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeSourceRecord, source_id)
            if record is None or record.status == "deleted":
                raise KeyError(f"unknown knowledge source: {source_id}")
            return _knowledge_source_from_record(session, record)

    def upsert_indexed_source(
        self,
        *,
        source: KnowledgeSource,
        chunks: list[Any],
        vectors: list[list[float]],
        embedding_model_profile: EmbeddingModelProfile,
        embedding_dimension: int,
        search_texts: list[str],
    ) -> KnowledgeSourceIndexResult:
        with DbSession(self.engine) as session:
            kb_record = session.get(KnowledgeBaseRecord, source.knowledge_base_id)
            if kb_record is None:
                raise KeyError(f"unknown knowledge base: {source.knowledge_base_id}")
            now = utc_now()
            record = session.get(KnowledgeSourceRecord, source.id)
            if record is None:
                record = KnowledgeSourceRecord(id=source.id, knowledge_base_id=source.knowledge_base_id, source_type=source.source_type, content_hash=source.content_hash)
            record.knowledge_base_id = source.knowledge_base_id
            record.source_type = source.source_type
            record.uri = source.uri
            record.title = source.title
            record.mime_type = source.mime_type
            record.size_bytes = source.size_bytes
            record.content_hash = source.content_hash
            record.indexed_at = now
            record.status = "indexed"
            record.error = None
            record.metadata_json = _dumps(source.metadata)
            record.updated_at = now
            session.add(record)
            session.flush()

            _delete_source_index_rows(session, source.id)
            for chunk, vector, search_text in zip(chunks, vectors, search_texts):
                chunk_id = str(uuid4())
                session.add(
                    KnowledgeChunkRecord(
                        id=chunk_id,
                        knowledge_base_id=source.knowledge_base_id,
                        source_id=source.id,
                        chunk_index=chunk.chunk_index,
                        heading_path=chunk.heading_path,
                        content=chunk.content,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                        token_count=chunk.token_count,
                        content_hash=chunk.content_hash,
                    )
                )
                session.add(
                    KnowledgeEmbeddingRecord(
                        id=str(uuid4()),
                        knowledge_base_id=source.knowledge_base_id,
                        source_id=source.id,
                        chunk_id=chunk_id,
                        embedding_model_profile_id=embedding_model_profile.id,
                        embedding_model_id_snapshot=embedding_model_profile.model_path,
                        embedding_dimension=embedding_dimension,
                        embedding_normalize_snapshot=embedding_model_profile.normalize,
                        vector_blob=array("f", [float(value) for value in vector]).tobytes(),
                    )
                )
                session.connection().exec_driver_sql(
                    "INSERT INTO kb_chunk_fts (chunk_id, knowledge_base_id, source_id, title, heading_path, content, search_text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (chunk_id, source.knowledge_base_id, source.id, source.title, chunk.heading_path, chunk.content, search_text),
                )

            _refresh_kb_index_status(session, source.knowledge_base_id)
            session.commit()
            return KnowledgeSourceIndexResult(
                source_id=source.id,
                status="indexed",
                chunks=len(chunks),
                embedding_model_profile_id=embedding_model_profile.id,
                embedding_dimension=embedding_dimension,
                indexed_at=record.indexed_at,
            )

    def mark_source_failed(self, source: KnowledgeSource, error: str) -> KnowledgeSourceIndexResult:
        with DbSession(self.engine) as session:
            existing = session.get(KnowledgeSourceRecord, source.id)
            now = utc_now()
            if existing is None:
                existing = KnowledgeSourceRecord(
                    id=source.id,
                    knowledge_base_id=source.knowledge_base_id,
                    source_type=source.source_type,
                    uri=source.uri,
                    title=source.title,
                    mime_type=source.mime_type,
                    size_bytes=source.size_bytes,
                    content_hash=source.content_hash,
                    status="failed",
                    error=error,
                    metadata_json=_dumps(source.metadata),
                )
            else:
                if existing.status not in {"indexed", "needs_reindex"}:
                    existing.status = "failed"
                existing.error = error
                existing.updated_at = now
            session.add(existing)
            _refresh_kb_index_status(session, source.knowledge_base_id)
            session.commit()
            return KnowledgeSourceIndexResult(
                source_id=source.id,
                status="failed",
                chunks=_source_chunk_count(session, source.id),
                indexed_at=existing.indexed_at,
                error=error,
            )

    def delete_source(self, source_id: str) -> KnowledgeSource:
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeSourceRecord, source_id)
            if record is None or record.status == "deleted":
                raise KeyError(f"unknown knowledge source: {source_id}")
            source = _knowledge_source_from_record(session, record)
            _delete_source_index_rows(session, source_id)
            session.delete(record)
            _refresh_kb_index_status(session, source.knowledge_base_id)
            session.commit()
            return source

    def source_text_reference(self, source_id: str) -> Dict[str, Any]:
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeSourceRecord, source_id)
            if record is None:
                raise KeyError(f"unknown knowledge source: {source_id}")
            return {"source_type": record.source_type, "uri": record.uri, "title": record.title}

    def list_session_bindings(self, session_id: str) -> List[SessionKnowledgeBinding]:
        with DbSession(self.engine) as session:
            records = session.exec(
                select(SessionKnowledgeBindingRecord)
                .where(SessionKnowledgeBindingRecord.session_id == session_id)
                .order_by(SessionKnowledgeBindingRecord.created_at)
            ).all()
            bindings: List[SessionKnowledgeBinding] = []
            for record in records:
                kb_record = session.get(KnowledgeBaseRecord, record.knowledge_base_id)
                bindings.append(_session_knowledge_binding_from_record(record, kb_record))
            return bindings

    def replace_session_bindings(self, session_id: str, knowledge_base_ids: List[str]) -> List[SessionKnowledgeBinding]:
        with DbSession(self.engine) as session:
            seen: set[str] = set()
            validated_ids: list[str] = []
            for knowledge_base_id in knowledge_base_ids:
                if knowledge_base_id in seen:
                    continue
                if session.get(KnowledgeBaseRecord, knowledge_base_id) is None:
                    raise KeyError(f"unknown knowledge base: {knowledge_base_id}")
                seen.add(knowledge_base_id)
                validated_ids.append(knowledge_base_id)
            session.exec(delete(SessionKnowledgeBindingRecord).where(SessionKnowledgeBindingRecord.session_id == session_id))
            for knowledge_base_id in validated_ids:
                session.add(SessionKnowledgeBindingRecord(session_id=session_id, knowledge_base_id=knowledge_base_id, enabled=True))
            session.commit()
        return self.list_session_bindings(session_id)

    def delete_session_bindings(self, session_id: str) -> None:
        with DbSession(self.engine) as session:
            session.exec(delete(SessionKnowledgeBindingRecord).where(SessionKnowledgeBindingRecord.session_id == session_id))
            session.commit()


def _session_from_record(record: SessionRecord) -> Session:
    return Session(
        session_id=record.session_id,
        title=record.title,
        default_agent_id=record.default_agent_id,
        context_mode=getattr(record, "context_mode", None) or "single_assistant",
        waiting_run_id=record.waiting_run_id,
        llm_profile_id=record.llm_profile_id,
        last_announced_llm_profile_id=record.last_announced_llm_profile_id,
        title_generation_state=getattr(record, "title_generation_state", None) or "pending",
        title_generation_metadata=_loads(getattr(record, "title_generation_metadata_json", "{}"), {}),
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _message_from_record(record: MessageRecord) -> MessageSchema:
    return MessageSchema(
        message_id=record.message_id,
        session_id=record.session_id,
        role=record.role,
        content=_loads(record.content_json, ""),
        speaker_type=getattr(record, "speaker_type", None),
        speaker_id=getattr(record, "speaker_id", None),
        speaker_name=getattr(record, "speaker_name", None),
        origin=getattr(record, "origin", None),
        output_type=record.output_type,
        agent_id=record.agent_id,
        command_name=record.command_name,
        action_id=record.action_id,
        run_id=record.run_id,
        parent_message_id=record.parent_message_id,
        available_actions=_loads(record.available_actions_json, []),
        metadata=_loads(record.metadata_json, {}),
        created_at=ensure_utc(record.created_at),
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
        stage=getattr(record, "stage", "") or "",
        progress_message=getattr(record, "progress_message", "") or "",
        progress_current=getattr(record, "progress_current", None),
        progress_total=getattr(record, "progress_total", None),
        cancel_requested=bool(getattr(record, "cancel_requested", False)),
        started_at=ensure_utc(getattr(record, "started_at", None)),
        finished_at=ensure_utc(getattr(record, "finished_at", None)),
        error_code=getattr(record, "error_code", None),
        error_message=getattr(record, "error_message", None),
        error=record.error,
        metadata=_loads(record.metadata_json, {}),
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _run_step_from_record(record: RunStepRecord) -> RunStepSchema:
    return RunStepSchema(
        step_id=record.step_id,
        run_id=record.run_id,
        parent_step_id=getattr(record, "parent_step_id", None),
        label=record.label,
        status=RunStepStatus(record.status),
        message=record.message,
        order=record.order,
        started_at=ensure_utc(record.started_at),
        finished_at=ensure_utc(record.finished_at),
        error_code=record.error_code,
        error_message=record.error_message,
        metadata=_loads(record.metadata_json, {}),
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _run_event_from_record(record: RunEventRecord) -> RunEventSchema:
    return RunEventSchema(
        event_id=record.event_id,
        run_id=record.run_id,
        session_id=record.session_id,
        type=record.type,
        message=record.message,
        payload=_loads(record.payload_json, {}),
        created_at=ensure_utc(record.created_at),
    )


def _agent_config_from_record(record: AgentConfigRecord) -> Dict[str, Any]:
    return {
        "agent_id": record.agent_id,
        "enabled": record.enabled,
        "display": _loads(getattr(record, "display_json", "{}") or "{}", {}),
        "runtime": _loads(getattr(record, "runtime_json", "{}") or "{}", {}),
        "user_config": _loads(record.user_config_json, {}),
        "created_at": ensure_utc(record.created_at),
        "updated_at": ensure_utc(record.updated_at),
    }


def _capability_config_from_record(record: CapabilityConfigRecord) -> Dict[str, Any]:
    return {
        "capability_id": record.capability_id,
        "enabled": record.enabled,
        "user_config": _loads(record.user_config_json, {}),
        "created_at": ensure_utc(record.created_at),
        "updated_at": ensure_utc(record.updated_at),
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
        provider_profile_id=record.provider_profile_id,
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
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _provider_to_record(profile: ProviderProfileSchema) -> ProviderProfileRecord:
    data = profile.model_dump()
    data["metadata_json"] = _dumps(data.pop("metadata", {}))
    return ProviderProfileRecord(**data)


def _apply_provider_to_record(record: ProviderProfileRecord, profile: ProviderProfileSchema) -> None:
    data = profile.model_dump()
    metadata = data.pop("metadata", {})
    for key, value in data.items():
        setattr(record, key, value)
    record.metadata_json = _dumps(metadata)


def _provider_from_record(record: ProviderProfileRecord) -> ProviderProfileSchema:
    return ProviderProfileSchema(
        id=record.id,
        name=record.name,
        provider=record.provider,
        base_url=record.base_url,
        api_key=record.api_key,
        timeout_seconds=record.timeout_seconds,
        enabled=record.enabled,
        metadata=_loads(record.metadata_json, {}),
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _knowledge_settings_from_record(record: KnowledgeSettingsRecord) -> KnowledgeSettings:
    return KnowledgeSettings.model_validate(
        {key: getattr(record, key) for key in KnowledgeSettings.model_fields if hasattr(record, key)}
    )


def _apply_knowledge_settings_to_record(record: KnowledgeSettingsRecord, settings: KnowledgeSettings) -> None:
    for key, value in settings.model_dump().items():
        if key in {"id"}:
            continue
        setattr(record, key, value)


def _find_embedding_profile_by_alias(session: DbSession, alias: str) -> Optional[EmbeddingModelProfileRecord]:
    return session.exec(select(EmbeddingModelProfileRecord).where(EmbeddingModelProfileRecord.alias == alias)).first()


def _embedding_profile_from_record(record: EmbeddingModelProfileRecord) -> EmbeddingModelProfile:
    return EmbeddingModelProfile(
        id=record.id,
        name=record.name,
        alias=record.alias,
        model_path=record.model_path,
        dimension=record.dimension,
        normalize=record.normalize,
        document_instruction=record.document_instruction,
        query_instruction=record.query_instruction,
        enabled=record.enabled,
        notes=record.notes,
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _knowledge_base_from_record(record: KnowledgeBaseRecord) -> KnowledgeBase:
    return KnowledgeBase(
        id=record.id,
        name=record.name,
        description=record.description,
        embedding_model_profile_id=record.embedding_model_profile_id,
        enabled=record.enabled,
        index_status=record.index_status,
        index_error=record.index_error,
        chunk_size_override=record.chunk_size_override,
        chunk_overlap_override=record.chunk_overlap_override,
        vector_candidate_k_override=record.vector_candidate_k_override,
        keyword_candidate_k_override=record.keyword_candidate_k_override,
        final_top_k_override=record.final_top_k_override,
        max_context_chars_override=record.max_context_chars_override,
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _knowledge_source_from_record(session: DbSession, record: KnowledgeSourceRecord) -> KnowledgeSource:
    latest_embedding = session.exec(
        select(KnowledgeEmbeddingRecord)
        .where(KnowledgeEmbeddingRecord.source_id == record.id)
        .order_by(KnowledgeEmbeddingRecord.created_at.desc())
    ).first()
    return KnowledgeSource(
        id=record.id,
        knowledge_base_id=record.knowledge_base_id,
        source_type=record.source_type,
        uri=record.uri,
        title=record.title,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        content_hash=record.content_hash,
        indexed_at=ensure_utc(record.indexed_at),
        status=record.status,
        error=record.error,
        metadata=_loads(record.metadata_json, {}),
        chunks=_source_chunk_count(session, record.id),
        embedding_model_profile_id=latest_embedding.embedding_model_profile_id if latest_embedding is not None else None,
        embedding_dimension=latest_embedding.embedding_dimension if latest_embedding is not None else None,
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _source_chunk_count(session: DbSession, source_id: str) -> int:
    return len(session.exec(select(KnowledgeChunkRecord.id).where(KnowledgeChunkRecord.source_id == source_id)).all())


def _delete_source_index_rows(session: DbSession, source_id: str) -> None:
    session.exec(delete(KnowledgeEmbeddingRecord).where(KnowledgeEmbeddingRecord.source_id == source_id))
    session.exec(delete(KnowledgeChunkRecord).where(KnowledgeChunkRecord.source_id == source_id))
    session.connection().exec_driver_sql("DELETE FROM kb_chunk_fts WHERE source_id = ?", (source_id,))


def _mark_kbs_for_profile_needs_reindex(session: DbSession, profile_id: str) -> None:
    kb_records = session.exec(
        select(KnowledgeBaseRecord).where(KnowledgeBaseRecord.embedding_model_profile_id == profile_id)
    ).all()
    for kb_record in kb_records:
        _mark_kb_needs_reindex(session, kb_record.id)


def _mark_kbs_using_default_chunking_needs_reindex(session: DbSession) -> None:
    kb_records = session.exec(
        select(KnowledgeBaseRecord)
        .where(KnowledgeBaseRecord.chunk_size_override == None)  # noqa: E711
        .where(KnowledgeBaseRecord.chunk_overlap_override == None)  # noqa: E711
    ).all()
    for kb_record in kb_records:
        _mark_kb_needs_reindex(session, kb_record.id)


def _mark_kb_needs_reindex(session: DbSession, knowledge_base_id: str) -> None:
    kb_record = session.get(KnowledgeBaseRecord, knowledge_base_id)
    if kb_record is None:
        return
    has_indexed_data = session.exec(
        select(KnowledgeSourceRecord.id)
        .where(KnowledgeSourceRecord.knowledge_base_id == knowledge_base_id)
        .where(KnowledgeSourceRecord.status.in_(["indexed", "needs_reindex"]))
    ).first()
    if has_indexed_data is None and kb_record.index_status == "empty":
        return
    now = utc_now()
    session.exec(
        update(KnowledgeSourceRecord)
        .where(KnowledgeSourceRecord.knowledge_base_id == knowledge_base_id)
        .where(KnowledgeSourceRecord.status == "indexed")
        .values(status="needs_reindex", updated_at=now)
    )
    kb_record.index_status = "needs_reindex"
    kb_record.index_error = None
    kb_record.updated_at = now
    session.add(kb_record)


def _refresh_kb_index_status(session: DbSession, knowledge_base_id: str) -> None:
    kb_record = session.get(KnowledgeBaseRecord, knowledge_base_id)
    if kb_record is None:
        return
    needs_reindex = session.exec(
        select(KnowledgeSourceRecord.id)
        .where(KnowledgeSourceRecord.knowledge_base_id == knowledge_base_id)
        .where(KnowledgeSourceRecord.status == "needs_reindex")
    ).first()
    if needs_reindex is not None:
        kb_record.index_status = "needs_reindex"
        kb_record.index_error = None
        kb_record.updated_at = utc_now()
        session.add(kb_record)
        return
    indexed = session.exec(
        select(KnowledgeSourceRecord.id)
        .where(KnowledgeSourceRecord.knowledge_base_id == knowledge_base_id)
        .where(KnowledgeSourceRecord.status == "indexed")
    ).first()
    kb_record.index_status = "ready" if indexed is not None else "empty"
    kb_record.index_error = None
    kb_record.updated_at = utc_now()
    session.add(kb_record)


def _session_knowledge_binding_from_record(
    record: SessionKnowledgeBindingRecord,
    knowledge_base_record: KnowledgeBaseRecord | None = None,
) -> SessionKnowledgeBinding:
    return SessionKnowledgeBinding(
        id=record.id,
        session_id=record.session_id,
        knowledge_base_id=record.knowledge_base_id,
        enabled=record.enabled,
        created_at=ensure_utc(record.created_at),
        knowledge_base=_knowledge_base_from_record(knowledge_base_record) if knowledge_base_record is not None else None,
    )
