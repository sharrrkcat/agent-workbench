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
from ai_workbench.core.multimodal_profiles import MultimodalEmbeddingModelProfile
from ai_workbench.core.vision_profiles import VisionModelProfile
from ai_workbench.core.schema.message import MessageSchema, infer_speaker_identity
from ai_workbench.core.message_parts import make_text_part, validate_message_parts
from ai_workbench.core.schema.run import RunSchema, RunStatus, RunStepSchema, RunStepStatus
from ai_workbench.core.schema.run_event import RunEventSchema
from ai_workbench.core.session import Session
from ai_workbench.core.settings import AppSettings, AppSettingsPatch, app_settings_patch_updates, sanitize_app_settings_payload
from ai_workbench.core.knowledge_settings import KnowledgeSettings, KnowledgeSettingsPatch, knowledge_settings_patch_updates
from ai_workbench.core.knowledge_store import (
    EmbeddingModelProfile,
    KnowledgeBase,
    KnowledgeOrigin,
    KnowledgeSource,
    KnowledgeSourceIndexResult,
    RerankerModelProfile,
    SessionKnowledgeBinding,
)
from ai_workbench.core.time import ensure_utc, utc_now
from ai_workbench.core.worldbook import (
    SessionWorldbookBinding,
    Worldbook,
    WorldbookEntry,
    WorldbookSettings,
    WorldbookSettingsPatch,
    sync_worldbook_settings_patch,
)
from ai_workbench.core.session_titles import is_default_session_title
from ai_workbench.db.models import (
    AgentConfigRecord,
    AppMetadataRecord,
    CapabilityConfigRecord,
    EmbeddingModelProfileRecord,
    KnowledgeBaseRecord,
    KnowledgeChunkRecord,
    KnowledgeEmbeddingRecord,
    KnowledgeOriginRecord,
    KnowledgeSettingsRecord,
    KnowledgeSourceRecord,
    MultimodalEmbeddingModelProfileRecord,
    RerankerModelProfileRecord,
    LLMProfileRecord,
    MessageRecord,
    ProviderProfileRecord,
    RunEventRecord,
    RunRecord,
    RunStepRecord,
    SessionRecord,
    SessionAgentStateRecord,
    SessionKnowledgeBindingRecord,
    SessionWorldbookBindingRecord,
    VisionModelProfileRecord,
    WorldbookEntryRecord,
    WorldbookRecord,
    WorldbookSettingsRecord,
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
        record = MessageRecord(
            message_id=str(uuid4()),
            session_id=session_id,
            role=role,
            speaker_type=speaker["speaker_type"],
            speaker_id=speaker["speaker_id"],
            speaker_name=speaker["speaker_name"],
            origin=speaker["origin"],
            content_version=resolved_content_version,
            parts_json=_dumps(validated_parts),
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
            record.speaker_type = message.speaker_type
            record.speaker_id = message.speaker_id
            record.speaker_name = message.speaker_name
            record.origin = message.origin
            record.content_version = message.content_version
            record.parts_json = _dumps(message.parts)
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
            return AppSettings.model_validate(sanitize_app_settings_payload(_loads(record.value, {})))

    def patch(self, values: Dict[str, Any]) -> AppSettings:
        patch = AppSettingsPatch.model_validate(values)
        updates = app_settings_patch_updates(patch)
        with DbSession(self.engine) as session:
            record = session.get(AppMetadataRecord, self.SETTINGS_KEY)
            current = AppSettings()
            if record is not None:
                current = AppSettings.model_validate(sanitize_app_settings_payload(_loads(record.value, {})))
            next_settings = AppSettings.model_validate({**current.model_dump(), **updates})
            if record is None:
                record = AppMetadataRecord(key=self.SETTINGS_KEY, value=_dumps(next_settings.model_dump()))
            else:
                record.value = _dumps(next_settings.model_dump())
                record.updated_at = utc_now()
            session.add(record)
            session.commit()
            return next_settings


class SqlMultimodalEmbeddingProfileStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def create(self, profile: MultimodalEmbeddingModelProfile) -> MultimodalEmbeddingModelProfile:
        with DbSession(self.engine) as session:
            if session.get(MultimodalEmbeddingModelProfileRecord, profile.id) is not None:
                raise ValueError("MULTIMODAL_EMBEDDING_ID_EXISTS")
            if (
                _find_multimodal_embedding_profile_by_alias(session, profile.alias) is not None
                or session.get(MultimodalEmbeddingModelProfileRecord, profile.alias) is not None
            ):
                raise ValueError("MULTIMODAL_EMBEDDING_ALIAS_EXISTS")
            record = _multimodal_embedding_profile_to_record(profile)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _multimodal_embedding_profile_from_record(record)

    def get(self, profile_id: str) -> MultimodalEmbeddingModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(MultimodalEmbeddingModelProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown multimodal embedding profile: {profile_id}")
            return _multimodal_embedding_profile_from_record(record)

    def find_by_alias(self, alias: str) -> Optional[MultimodalEmbeddingModelProfile]:
        with DbSession(self.engine) as session:
            record = _find_multimodal_embedding_profile_by_alias(session, alias)
            return _multimodal_embedding_profile_from_record(record) if record is not None else None

    def get_by_id_or_alias(self, profile_id_or_alias: str) -> MultimodalEmbeddingModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(MultimodalEmbeddingModelProfileRecord, profile_id_or_alias)
            if record is None:
                record = _find_multimodal_embedding_profile_by_alias(session, profile_id_or_alias)
            if record is None:
                raise KeyError(f"unknown multimodal embedding profile: {profile_id_or_alias}")
            return _multimodal_embedding_profile_from_record(record)

    def update(self, profile_id: str, values: Dict[str, Any]) -> MultimodalEmbeddingModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(MultimodalEmbeddingModelProfileRecord, profile_id)
            if record is None:
                record = _find_multimodal_embedding_profile_by_alias(session, profile_id)
            if record is None:
                raise KeyError(f"unknown multimodal embedding profile: {profile_id}")
            existing = _multimodal_embedding_profile_from_record(record)
            alias = values.get("alias")
            if alias is not None:
                conflict = _find_multimodal_embedding_profile_by_alias(session, str(alias))
                id_conflict = session.get(MultimodalEmbeddingModelProfileRecord, str(alias))
                if (conflict is not None and conflict.id != existing.id) or (id_conflict is not None and id_conflict.id != existing.id):
                    raise ValueError("MULTIMODAL_EMBEDDING_ALIAS_EXISTS")
            updated = MultimodalEmbeddingModelProfile.model_validate(
                existing.model_copy(update={**values, "updated_at": utc_now()}).model_dump()
            )
            _apply_multimodal_embedding_profile_to_record(record, updated)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _multimodal_embedding_profile_from_record(record)

    def delete(self, profile_id: str) -> MultimodalEmbeddingModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(MultimodalEmbeddingModelProfileRecord, profile_id)
            if record is None:
                record = _find_multimodal_embedding_profile_by_alias(session, profile_id)
            if record is None:
                raise KeyError(f"unknown multimodal embedding profile: {profile_id}")
            profile = _multimodal_embedding_profile_from_record(record)
            session.delete(record)
            session.commit()
            return profile

    def list(self) -> List[MultimodalEmbeddingModelProfile]:
        with DbSession(self.engine) as session:
            records = session.exec(
                select(MultimodalEmbeddingModelProfileRecord).order_by(
                    MultimodalEmbeddingModelProfileRecord.alias,
                    MultimodalEmbeddingModelProfileRecord.created_at,
                )
            ).all()
            return [_multimodal_embedding_profile_from_record(record) for record in records]


class SqlVisionProfileStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def create(self, profile: VisionModelProfile) -> VisionModelProfile:
        with DbSession(self.engine) as session:
            if session.get(VisionModelProfileRecord, profile.id) is not None:
                raise ValueError("VISION_MODEL_ID_EXISTS")
            if _find_vision_profile_by_alias(session, profile.alias) is not None or session.get(VisionModelProfileRecord, profile.alias) is not None:
                raise ValueError("VISION_MODEL_ALIAS_EXISTS")
            record = _vision_profile_to_record(profile)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _vision_profile_from_record(record)

    def get(self, profile_id: str) -> VisionModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(VisionModelProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown vision profile: {profile_id}")
            return _vision_profile_from_record(record)

    def find_by_alias(self, alias: str) -> Optional[VisionModelProfile]:
        with DbSession(self.engine) as session:
            record = _find_vision_profile_by_alias(session, alias)
            return _vision_profile_from_record(record) if record is not None else None

    def get_by_id_or_alias(self, profile_id_or_alias: str) -> VisionModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(VisionModelProfileRecord, profile_id_or_alias)
            if record is None:
                record = _find_vision_profile_by_alias(session, profile_id_or_alias)
            if record is None:
                raise KeyError(f"unknown vision profile: {profile_id_or_alias}")
            return _vision_profile_from_record(record)

    def update(self, profile_id: str, values: Dict[str, Any]) -> VisionModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(VisionModelProfileRecord, profile_id)
            if record is None:
                record = _find_vision_profile_by_alias(session, profile_id)
            if record is None:
                raise KeyError(f"unknown vision profile: {profile_id}")
            existing = _vision_profile_from_record(record)
            alias = values.get("alias")
            if alias is not None:
                conflict = _find_vision_profile_by_alias(session, str(alias))
                id_conflict = session.get(VisionModelProfileRecord, str(alias))
                if (conflict is not None and conflict.id != existing.id) or (id_conflict is not None and id_conflict.id != existing.id):
                    raise ValueError("VISION_MODEL_ALIAS_EXISTS")
            updated = VisionModelProfile.model_validate(
                existing.model_copy(update={**values, "updated_at": utc_now()}).model_dump()
            )
            _apply_vision_profile_to_record(record, updated)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _vision_profile_from_record(record)

    def delete(self, profile_id: str) -> VisionModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(VisionModelProfileRecord, profile_id)
            if record is None:
                record = _find_vision_profile_by_alias(session, profile_id)
            if record is None:
                raise KeyError(f"unknown vision profile: {profile_id}")
            profile = _vision_profile_from_record(record)
            session.delete(record)
            session.commit()
            return profile

    def list(self) -> List[VisionModelProfile]:
        with DbSession(self.engine) as session:
            records = session.exec(
                select(VisionModelProfileRecord).order_by(
                    VisionModelProfileRecord.alias,
                    VisionModelProfileRecord.created_at,
                )
            ).all()
            return [_vision_profile_from_record(record) for record in records]


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


class SqlWorldbookStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def get_settings(self) -> WorldbookSettings:
        with DbSession(self.engine) as session:
            record = session.get(WorldbookSettingsRecord, 1)
            if record is None:
                record = WorldbookSettingsRecord(id=1)
                session.add(record)
                session.commit()
                session.refresh(record)
            return _worldbook_settings_from_record(record)

    def patch_settings(self, values: Dict[str, Any]) -> WorldbookSettings:
        patch = WorldbookSettingsPatch.model_validate(values)
        updates = sync_worldbook_settings_patch(patch.model_dump(exclude_unset=True))
        with DbSession(self.engine) as session:
            record = session.get(WorldbookSettingsRecord, 1) or WorldbookSettingsRecord(id=1)
            current = _worldbook_settings_from_record(record)
            next_settings = WorldbookSettings.model_validate({**current.model_dump(), **updates, "updated_at": utc_now()})
            for key, value in next_settings.model_dump().items():
                if key != "id" and hasattr(record, key):
                    setattr(record, key, value)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _worldbook_settings_from_record(record)

    def list_worldbooks(self) -> List[Worldbook]:
        with DbSession(self.engine) as session:
            records = session.exec(select(WorldbookRecord).order_by(WorldbookRecord.name, WorldbookRecord.created_at)).all()
            return [_worldbook_from_record(session, record) for record in records]

    def create_worldbook(self, worldbook: Worldbook) -> Worldbook:
        with DbSession(self.engine) as session:
            record = WorldbookRecord(**_worldbook_record_data(worldbook))
            session.add(record)
            session.commit()
            session.refresh(record)
            return _worldbook_from_record(session, record)

    def get_worldbook(self, worldbook_id: str) -> Worldbook:
        with DbSession(self.engine) as session:
            record = session.get(WorldbookRecord, worldbook_id)
            if record is None:
                raise KeyError(f"unknown worldbook: {worldbook_id}")
            return _worldbook_from_record(session, record)

    def update_worldbook(self, worldbook_id: str, values: Dict[str, Any]) -> Worldbook:
        with DbSession(self.engine) as session:
            record = session.get(WorldbookRecord, worldbook_id)
            if record is None:
                raise KeyError(f"unknown worldbook: {worldbook_id}")
            candidate = _worldbook_from_record(session, record).model_copy(update={**values, "updated_at": utc_now()})
            updated = Worldbook.model_validate(candidate.model_dump())
            for key, value in _worldbook_record_data(updated).items():
                setattr(record, key, value)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _worldbook_from_record(session, record)

    def delete_worldbook(self, worldbook_id: str) -> Worldbook:
        with DbSession(self.engine) as session:
            record = session.get(WorldbookRecord, worldbook_id)
            if record is None:
                raise KeyError(f"unknown worldbook: {worldbook_id}")
            worldbook = _worldbook_from_record(session, record)
            session.exec(delete(WorldbookEntryRecord).where(WorldbookEntryRecord.worldbook_id == worldbook_id))
            session.exec(delete(SessionWorldbookBindingRecord).where(SessionWorldbookBindingRecord.worldbook_id == worldbook_id))
            session.delete(record)
            session.commit()
            return worldbook

    def list_entries(self, worldbook_id: str) -> List[WorldbookEntry]:
        with DbSession(self.engine) as session:
            if session.get(WorldbookRecord, worldbook_id) is None:
                raise KeyError(f"unknown worldbook: {worldbook_id}")
            records = session.exec(
                select(WorldbookEntryRecord)
                .where(WorldbookEntryRecord.worldbook_id == worldbook_id)
                .order_by(WorldbookEntryRecord.sort_order, WorldbookEntryRecord.created_at)
            ).all()
            return [_worldbook_entry_from_record(record) for record in records]

    def create_entry(self, entry: WorldbookEntry) -> WorldbookEntry:
        with DbSession(self.engine) as session:
            if session.get(WorldbookRecord, entry.worldbook_id) is None:
                raise KeyError(f"unknown worldbook: {entry.worldbook_id}")
            record = WorldbookEntryRecord(**entry.model_dump())
            session.add(record)
            session.commit()
            session.refresh(record)
            return _worldbook_entry_from_record(record)

    def get_entry(self, entry_id: str) -> WorldbookEntry:
        with DbSession(self.engine) as session:
            record = session.get(WorldbookEntryRecord, entry_id)
            if record is None:
                raise KeyError(f"unknown worldbook entry: {entry_id}")
            return _worldbook_entry_from_record(record)

    def update_entry(self, entry_id: str, values: Dict[str, Any]) -> WorldbookEntry:
        with DbSession(self.engine) as session:
            record = session.get(WorldbookEntryRecord, entry_id)
            if record is None:
                raise KeyError(f"unknown worldbook entry: {entry_id}")
            candidate = _worldbook_entry_from_record(record).model_copy(update={**values, "updated_at": utc_now()})
            updated = WorldbookEntry.model_validate(candidate.model_dump())
            for key, value in updated.model_dump().items():
                setattr(record, key, value)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _worldbook_entry_from_record(record)

    def delete_entry(self, entry_id: str) -> WorldbookEntry:
        with DbSession(self.engine) as session:
            record = session.get(WorldbookEntryRecord, entry_id)
            if record is None:
                raise KeyError(f"unknown worldbook entry: {entry_id}")
            entry = _worldbook_entry_from_record(record)
            session.delete(record)
            session.commit()
            return entry

    def reorder_entries(self, worldbook_id: str, entry_ids: List[str]) -> List[WorldbookEntry]:
        with DbSession(self.engine) as session:
            existing = session.exec(select(WorldbookEntryRecord).where(WorldbookEntryRecord.worldbook_id == worldbook_id)).all()
            by_id = {record.id: record for record in existing}
            if set(entry_ids) != set(by_id):
                raise ValueError("WORLDBOOK_REORDER_IDS_MISMATCH")
            now = utc_now()
            for index, entry_id in enumerate(entry_ids):
                by_id[entry_id].sort_order = (index + 1) * 10
                by_id[entry_id].updated_at = now
                session.add(by_id[entry_id])
            session.commit()
        return self.list_entries(worldbook_id)

    def list_session_bindings(self, session_id: str) -> List[SessionWorldbookBinding]:
        with DbSession(self.engine) as session:
            records = session.exec(
                select(SessionWorldbookBindingRecord)
                .where(SessionWorldbookBindingRecord.session_id == session_id)
                .order_by(SessionWorldbookBindingRecord.sort_order, SessionWorldbookBindingRecord.created_at)
            ).all()
            return [_session_worldbook_binding_from_record(session, record) for record in records]

    def replace_session_bindings(self, session_id: str, worldbook_ids: List[str]) -> tuple[List[SessionWorldbookBinding], List[str]]:
        warnings: list[str] = []
        with DbSession(self.engine) as session:
            seen: set[str] = set()
            valid_ids: list[str] = []
            for worldbook_id in worldbook_ids:
                if worldbook_id in seen:
                    continue
                record = session.get(WorldbookRecord, worldbook_id)
                if record is None:
                    raise KeyError(f"unknown worldbook: {worldbook_id}")
                if not record.enabled:
                    warnings.append(f"Worldbook is disabled and was not bound: {worldbook_id}")
                    continue
                seen.add(worldbook_id)
                valid_ids.append(worldbook_id)
            session.exec(delete(SessionWorldbookBindingRecord).where(SessionWorldbookBindingRecord.session_id == session_id))
            now = utc_now()
            for index, worldbook_id in enumerate(valid_ids):
                session.add(SessionWorldbookBindingRecord(id=str(uuid4()), session_id=session_id, worldbook_id=worldbook_id, enabled=True, sort_order=(index + 1) * 10, created_at=now, updated_at=now))
            session.commit()
        return self.list_session_bindings(session_id), warnings

    def delete_session_bindings(self, session_id: str) -> None:
        with DbSession(self.engine) as session:
            session.exec(delete(SessionWorldbookBindingRecord).where(SessionWorldbookBindingRecord.session_id == session_id))
            session.commit()


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
            chunk_size_defaults_changed = any(
                key in updates and getattr(current, key) != updates[key]
                for key in ("default_chunk_size", "default_chunk_overlap")
            )
            next_settings = KnowledgeSettings.model_validate({**current.model_dump(), **updates})
            _apply_knowledge_settings_to_record(record, next_settings)
            record.updated_at = utc_now()
            session.add(record)
            if chunk_size_defaults_changed:
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

    def find_embedding_profile_by_alias(self, alias: str) -> Optional[EmbeddingModelProfile]:
        with DbSession(self.engine) as session:
            record = _find_embedding_profile_by_alias(session, alias)
            return _embedding_profile_from_record(record) if record is not None else None

    def get_embedding_profile_by_id_or_alias(self, profile_id_or_alias: str) -> EmbeddingModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(EmbeddingModelProfileRecord, profile_id_or_alias)
            if record is None:
                record = _find_embedding_profile_by_alias(session, profile_id_or_alias)
            if record is None:
                raise KeyError(f"unknown embedding model profile: {profile_id_or_alias}")
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
            stale_keys = {"provider_profile_id", "provider_model_id", "model_path", "dimension", "normalize", "document_instruction", "query_instruction"}
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

    def list_reranker_profiles(self) -> List[RerankerModelProfile]:
        with DbSession(self.engine) as session:
            records = session.exec(select(RerankerModelProfileRecord).order_by(RerankerModelProfileRecord.alias)).all()
            return [_reranker_profile_from_record(record) for record in records]

    def create_reranker_profile(self, profile: RerankerModelProfile) -> RerankerModelProfile:
        with DbSession(self.engine) as session:
            if session.get(RerankerModelProfileRecord, profile.id) is not None:
                raise ValueError("KNOWLEDGE_RERANKER_ID_EXISTS")
            if _find_reranker_profile_by_alias(session, profile.alias) is not None:
                raise ValueError("KNOWLEDGE_RERANKER_ALIAS_EXISTS")
            record = RerankerModelProfileRecord(**profile.model_dump())
            session.add(record)
            session.commit()
            session.refresh(record)
            return _reranker_profile_from_record(record)

    def get_reranker_profile(self, profile_id: str) -> RerankerModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(RerankerModelProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown reranker model profile: {profile_id}")
            return _reranker_profile_from_record(record)

    def update_reranker_profile(self, profile_id: str, values: Dict[str, Any]) -> RerankerModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(RerankerModelProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown reranker model profile: {profile_id}")
            alias = values.get("alias")
            if alias is not None:
                conflict = _find_reranker_profile_by_alias(session, str(alias))
                if conflict is not None and conflict.id != record.id:
                    raise ValueError("KNOWLEDGE_RERANKER_ALIAS_EXISTS")
            candidate = _reranker_profile_from_record(record).model_copy(update={**values, "updated_at": utc_now()})
            profile = RerankerModelProfile.model_validate(candidate.model_dump())
            for key, value in profile.model_dump().items():
                setattr(record, key, value)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _reranker_profile_from_record(record)

    def delete_reranker_profile(self, profile_id: str) -> RerankerModelProfile:
        with DbSession(self.engine) as session:
            record = session.get(RerankerModelProfileRecord, profile_id)
            if record is None:
                raise KeyError(f"unknown reranker model profile: {profile_id}")
            settings = session.get(KnowledgeSettingsRecord, 1)
            if settings is not None and getattr(settings, "reranker_profile_id", None) == record.id:
                raise ValueError("KNOWLEDGE_RERANKER_MODEL_IN_USE")
            profile = _reranker_profile_from_record(record)
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
            stale_keys = {"embedding_model_profile_id", "chunk_size_override", "chunk_overlap_override", "default_chunk_profile"}
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
            session.exec(delete(KnowledgeOriginRecord).where(KnowledgeOriginRecord.knowledge_base_id == record.id))
            session.exec(delete(SessionKnowledgeBindingRecord).where(SessionKnowledgeBindingRecord.knowledge_base_id == record.id))
            session.delete(record)
            session.commit()
            return knowledge_base

    def list_origins(self, knowledge_base_id: str) -> List[KnowledgeOrigin]:
        with DbSession(self.engine) as session:
            if session.get(KnowledgeBaseRecord, knowledge_base_id) is None:
                raise KeyError(f"unknown knowledge base: {knowledge_base_id}")
            records = session.exec(
                select(KnowledgeOriginRecord)
                .where(KnowledgeOriginRecord.knowledge_base_id == knowledge_base_id)
                .order_by(KnowledgeOriginRecord.slug)
            ).all()
            return [_knowledge_origin_from_record(record) for record in records]

    def create_origin(self, origin: KnowledgeOrigin) -> KnowledgeOrigin:
        with DbSession(self.engine) as session:
            if session.get(KnowledgeBaseRecord, origin.knowledge_base_id) is None:
                raise KeyError(f"unknown knowledge base: {origin.knowledge_base_id}")
            conflict = session.exec(
                select(KnowledgeOriginRecord)
                .where(KnowledgeOriginRecord.knowledge_base_id == origin.knowledge_base_id)
                .where(KnowledgeOriginRecord.slug == origin.slug)
            ).first()
            if conflict is not None:
                raise ValueError("KNOWLEDGE_ORIGIN_SLUG_EXISTS")
            data = origin.model_dump()
            data["metadata_json"] = _dumps(data.pop("metadata", {}))
            record = KnowledgeOriginRecord(**data)
            session.add(record)
            session.commit()
            session.refresh(record)
            return _knowledge_origin_from_record(record)

    def get_origin(self, origin_id: str) -> KnowledgeOrigin:
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeOriginRecord, origin_id)
            if record is None:
                raise KeyError(f"unknown knowledge origin: {origin_id}")
            return _knowledge_origin_from_record(record)

    def update_origin(self, origin_id: str, values: Dict[str, Any]) -> KnowledgeOrigin:
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeOriginRecord, origin_id)
            if record is None:
                raise KeyError(f"unknown knowledge origin: {origin_id}")
            if "metadata" in values:
                record.metadata_json = _dumps(values.pop("metadata") or {})
            default_chunk_profile_changed = (
                "default_chunk_profile" in values
                and getattr(record, "default_chunk_profile", None) != values.get("default_chunk_profile")
            )
            for key, value in values.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            record.updated_at = utc_now()
            session.add(record)
            if default_chunk_profile_changed:
                _mark_origin_sources_needs_reindex(session, record.id)
            session.commit()
            session.refresh(record)
            return _knowledge_origin_from_record(record)

    def delete_origin(self, origin_id: str) -> KnowledgeOrigin:
        with DbSession(self.engine) as session:
            record = session.get(KnowledgeOriginRecord, origin_id)
            if record is None:
                raise KeyError(f"unknown knowledge origin: {origin_id}")
            origin = _knowledge_origin_from_record(record)
            source_records = session.exec(
                select(KnowledgeSourceRecord).where(KnowledgeSourceRecord.origin_id == origin_id)
            ).all()
            for source_record in source_records:
                _delete_source_index_rows(session, source_record.id)
                session.delete(source_record)
            session.delete(record)
            _refresh_kb_index_status(session, origin.knowledge_base_id)
            session.commit()
            return origin

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
            record.origin_id = source.origin_id
            record.source_type = source.source_type
            record.uri = source.uri
            record.title = source.title
            record.relative_path = source.relative_path
            record.virtual_path = source.virtual_path
            record.folder_path = source.folder_path
            record.file_name = source.file_name
            record.extension = source.extension
            record.path_depth = source.path_depth
            record.file_status = "ready"
            record.source_mtime = source.source_mtime
            record.source_size_bytes = source.source_size_bytes or source.size_bytes
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
                        metadata_json=_dumps(chunk.metadata),
                    )
                )
                session.add(
                    KnowledgeEmbeddingRecord(
                        id=str(uuid4()),
                        knowledge_base_id=source.knowledge_base_id,
                        source_id=source.id,
                        chunk_id=chunk_id,
                        embedding_model_profile_id=embedding_model_profile.id,
                        embedding_model_id_snapshot=_embedding_profile_model_identity(embedding_model_profile),
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
                    origin_id=source.origin_id,
                    source_type=source.source_type,
                    uri=source.uri,
                    title=source.title,
                    relative_path=source.relative_path,
                    virtual_path=source.virtual_path,
                    folder_path=source.folder_path,
                    file_name=source.file_name,
                    extension=source.extension,
                    path_depth=source.path_depth,
                    file_status="failed",
                    source_mtime=source.source_mtime,
                    source_size_bytes=source.source_size_bytes or source.size_bytes,
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
                .order_by(SessionKnowledgeBindingRecord.sort_order, SessionKnowledgeBindingRecord.created_at)
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
            for index, knowledge_base_id in enumerate(validated_ids):
                session.add(SessionKnowledgeBindingRecord(session_id=session_id, knowledge_base_id=knowledge_base_id, enabled=True, sort_order=(index + 1) * 10))
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
        speaker_type=getattr(record, "speaker_type", None),
        speaker_id=getattr(record, "speaker_id", None),
        speaker_name=getattr(record, "speaker_name", None),
        origin=getattr(record, "origin", None),
        content_version=getattr(record, "content_version", None),
        parts=_loads(getattr(record, "parts_json", "[]"), []),
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
        external_inference_enabled=bool(getattr(record, "external_inference_enabled", False)),
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


def _multimodal_embedding_profile_to_record(profile: MultimodalEmbeddingModelProfile) -> MultimodalEmbeddingModelProfileRecord:
    data = profile.model_dump()
    data["supported_input_types_json"] = _dumps(data.pop("supported_input_types", []))
    data["metadata_json"] = _dumps(data.pop("metadata", {}))
    return MultimodalEmbeddingModelProfileRecord(**data)


def _apply_multimodal_embedding_profile_to_record(
    record: MultimodalEmbeddingModelProfileRecord,
    profile: MultimodalEmbeddingModelProfile,
) -> None:
    data = profile.model_dump()
    supported_input_types = data.pop("supported_input_types", [])
    metadata = data.pop("metadata", {})
    for key, value in data.items():
        setattr(record, key, value)
    record.supported_input_types_json = _dumps(supported_input_types)
    record.metadata_json = _dumps(metadata)


def _multimodal_embedding_profile_from_record(record: MultimodalEmbeddingModelProfileRecord) -> MultimodalEmbeddingModelProfile:
    return MultimodalEmbeddingModelProfile(
        id=record.id,
        alias=getattr(record, "alias", "") or "",
        name=record.name,
        description=getattr(record, "description", "") or "",
        notes=getattr(record, "notes", "") or "",
        enabled=bool(getattr(record, "enabled", True)),
        external_inference_enabled=bool(getattr(record, "external_inference_enabled", False)),
        provider_profile_id=getattr(record, "provider_profile_id", None),
        provider_model_id=getattr(record, "provider_model_id", "") or "",
        architecture=record.architecture,
        backend=getattr(record, "backend", "auto") or "auto",
        embedding_space=getattr(record, "embedding_space", None),
        dimensions=getattr(record, "dimensions", None),
        normalize_default=bool(getattr(record, "normalize_default", True)),
        supported_input_types=_loads(getattr(record, "supported_input_types_json", "") or "", ["image", "text"]),
        preprocessing_signature=getattr(record, "preprocessing_signature", None),
        pooling_strategy=getattr(record, "pooling_strategy", "model_default") or "model_default",
        max_batch_size=getattr(record, "max_batch_size", None),
        metadata=_loads(getattr(record, "metadata_json", "") or "", {}),
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _vision_profile_to_record(profile: VisionModelProfile) -> VisionModelProfileRecord:
    data = profile.model_dump()
    data["supported_tasks_json"] = _dumps(data.pop("supported_tasks", []))
    data["metadata_json"] = _dumps(data.pop("metadata", {}))
    return VisionModelProfileRecord(**data)


def _apply_vision_profile_to_record(
    record: VisionModelProfileRecord,
    profile: VisionModelProfile,
) -> None:
    data = profile.model_dump()
    supported_tasks = data.pop("supported_tasks", [])
    metadata = data.pop("metadata", {})
    for key, value in data.items():
        setattr(record, key, value)
    record.supported_tasks_json = _dumps(supported_tasks)
    record.metadata_json = _dumps(metadata)


def _vision_profile_from_record(record: VisionModelProfileRecord) -> VisionModelProfile:
    return VisionModelProfile(
        id=record.id,
        alias=getattr(record, "alias", "") or "",
        name=record.name,
        description=getattr(record, "description", "") or "",
        notes=getattr(record, "notes", "") or "",
        enabled=bool(getattr(record, "enabled", True)),
        external_inference_enabled=bool(getattr(record, "external_inference_enabled", False)),
        provider_profile_id=getattr(record, "provider_profile_id", None),
        provider_model_id=getattr(record, "provider_model_id", "") or "",
        architecture=getattr(record, "architecture", "florence2") or "florence2",
        backend=getattr(record, "backend", "transformers") or "transformers",
        supported_tasks=_loads(
            getattr(record, "supported_tasks_json", "") or "",
            ["caption", "detailed_caption", "more_detailed_caption", "ocr", "object_detection"],
        ),
        max_batch_size=getattr(record, "max_batch_size", 1),
        metadata=_loads(getattr(record, "metadata_json", "{}") or "{}", {}),
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _knowledge_settings_from_record(record: KnowledgeSettingsRecord) -> KnowledgeSettings:
    return KnowledgeSettings.model_validate(
        {key: getattr(record, key) for key in KnowledgeSettings.model_fields if hasattr(record, key)}
    )


def _worldbook_settings_from_record(record: WorldbookSettingsRecord) -> WorldbookSettings:
    return WorldbookSettings.model_validate(
        {key: getattr(record, key) for key in WorldbookSettings.model_fields if hasattr(record, key)}
    )


def _worldbook_record_data(worldbook: Worldbook) -> Dict[str, Any]:
    data = worldbook.model_dump()
    data.pop("entry_count", None)
    data.pop("active_binding_count", None)
    return data


def _worldbook_from_record(session: DbSession, record: WorldbookRecord) -> Worldbook:
    entry_count = len(session.exec(select(WorldbookEntryRecord.id).where(WorldbookEntryRecord.worldbook_id == record.id)).all())
    active_binding_count = len(
        session.exec(
            select(SessionWorldbookBindingRecord.id)
            .where(SessionWorldbookBindingRecord.worldbook_id == record.id)
            .where(SessionWorldbookBindingRecord.enabled == True)  # noqa: E712
        ).all()
    )
    return Worldbook(
        id=record.id,
        name=record.name,
        description=record.description,
        enabled=record.enabled,
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
        entry_count=entry_count,
        active_binding_count=active_binding_count,
    )


def _worldbook_entry_from_record(record: WorldbookEntryRecord) -> WorldbookEntry:
    return WorldbookEntry(
        id=record.id,
        worldbook_id=record.worldbook_id,
        name=record.name,
        keywords_text=record.keywords_text,
        content=record.content,
        activation_mode=record.activation_mode,
        enabled=record.enabled,
        sort_order=record.sort_order,
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _session_worldbook_binding_from_record(session: DbSession, record: SessionWorldbookBindingRecord) -> SessionWorldbookBinding:
    worldbook_record = session.get(WorldbookRecord, record.worldbook_id)
    return SessionWorldbookBinding(
        id=record.id,
        session_id=record.session_id,
        worldbook_id=record.worldbook_id,
        enabled=record.enabled,
        sort_order=record.sort_order,
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
        worldbook=_worldbook_from_record(session, worldbook_record) if worldbook_record is not None else None,
    )


def _apply_knowledge_settings_to_record(record: KnowledgeSettingsRecord, settings: KnowledgeSettings) -> None:
    for key, value in settings.model_dump().items():
        if key in {"id"}:
            continue
        setattr(record, key, value)


def _find_embedding_profile_by_alias(session: DbSession, alias: str) -> Optional[EmbeddingModelProfileRecord]:
    return session.exec(select(EmbeddingModelProfileRecord).where(EmbeddingModelProfileRecord.alias == alias)).first()


def _find_reranker_profile_by_alias(session: DbSession, alias: str) -> Optional[RerankerModelProfileRecord]:
    return session.exec(select(RerankerModelProfileRecord).where(RerankerModelProfileRecord.alias == alias)).first()


def _find_multimodal_embedding_profile_by_alias(session: DbSession, alias: str) -> Optional[MultimodalEmbeddingModelProfileRecord]:
    return session.exec(select(MultimodalEmbeddingModelProfileRecord).where(MultimodalEmbeddingModelProfileRecord.alias == alias)).first()


def _find_vision_profile_by_alias(session: DbSession, alias: str) -> Optional[VisionModelProfileRecord]:
    return session.exec(select(VisionModelProfileRecord).where(VisionModelProfileRecord.alias == alias)).first()


def _embedding_profile_from_record(record: EmbeddingModelProfileRecord) -> EmbeddingModelProfile:
    return EmbeddingModelProfile(
        id=record.id,
        name=record.name,
        alias=record.alias,
        model_path=getattr(record, "model_path", "") or "",
        provider_profile_id=getattr(record, "provider_profile_id", None),
        provider_model_id=getattr(record, "provider_model_id", "") or "",
        dimension=record.dimension,
        normalize=record.normalize,
        document_instruction=record.document_instruction,
        query_instruction=record.query_instruction,
        enabled=record.enabled,
        external_inference_enabled=bool(getattr(record, "external_inference_enabled", False)),
        notes=record.notes,
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _embedding_profile_model_identity(profile: EmbeddingModelProfile) -> str:
    return profile.provider_model_id or profile.model_path


def _reranker_profile_from_record(record: RerankerModelProfileRecord) -> RerankerModelProfile:
    return RerankerModelProfile(
        id=record.id,
        name=record.name,
        alias=record.alias,
        provider_profile_id=record.provider_profile_id,
        provider_model_id=record.provider_model_id,
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
        aliases_text=getattr(record, "aliases_text", "") or "",
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
        default_chunk_profile=getattr(record, "default_chunk_profile", None) or "markdown_auto",
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _knowledge_origin_from_record(record: KnowledgeOriginRecord) -> KnowledgeOrigin:
    return KnowledgeOrigin(
        id=record.id,
        knowledge_base_id=record.knowledge_base_id,
        name=record.name,
        slug=record.slug,
        root_path=record.root_path,
        include_globs=getattr(record, "include_globs", "") or "**/*",
        exclude_globs=getattr(record, "exclude_globs", "") or "",
        default_chunk_profile=getattr(record, "default_chunk_profile", None),
        last_scan_at=ensure_utc(getattr(record, "last_scan_at", None)),
        last_import_at=ensure_utc(getattr(record, "last_import_at", None)),
        status=getattr(record, "status", "") or "ready",
        error=getattr(record, "error", None),
        metadata=_loads(getattr(record, "metadata_json", "{}") or "{}", {}),
        created_at=ensure_utc(record.created_at),
        updated_at=ensure_utc(record.updated_at),
    )


def _knowledge_source_from_record(session: DbSession, record: KnowledgeSourceRecord) -> KnowledgeSource:
    latest_embedding = session.exec(
        select(KnowledgeEmbeddingRecord)
        .where(KnowledgeEmbeddingRecord.source_id == record.id)
        .order_by(KnowledgeEmbeddingRecord.created_at.desc())
    ).first()
    metadata = _loads(record.metadata_json, {})
    return KnowledgeSource(
        id=record.id,
        knowledge_base_id=record.knowledge_base_id,
        origin_id=getattr(record, "origin_id", None),
        source_type=record.source_type,
        uri=record.uri,
        title=record.title,
        relative_path=getattr(record, "relative_path", "") or "",
        virtual_path=getattr(record, "virtual_path", "") or "",
        folder_path=getattr(record, "folder_path", "") or "",
        file_name=getattr(record, "file_name", "") or "",
        extension=getattr(record, "extension", "") or "",
        path_depth=int(getattr(record, "path_depth", 0) or 0),
        file_status=getattr(record, "file_status", "") or "ready",
        source_mtime=ensure_utc(getattr(record, "source_mtime", None)),
        source_size_bytes=int(getattr(record, "source_size_bytes", 0) or 0),
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        content_hash=record.content_hash,
        indexed_at=ensure_utc(record.indexed_at),
        status=record.status,
        error=record.error,
        metadata=metadata,
        chunks=_source_chunk_count(session, record.id),
        embedding_model_profile_id=latest_embedding.embedding_model_profile_id if latest_embedding is not None else None,
        embedding_dimension=latest_embedding.embedding_dimension if latest_embedding is not None else None,
        chunk_profile_requested=metadata.get("chunk_profile_requested"),
        chunk_profile_effective=metadata.get("chunk_profile_effective"),
        chunk_profile_confidence=metadata.get("chunk_profile_confidence"),
        profile_source=metadata.get("profile_source"),
        entity_level=metadata.get("entity_level"),
        title_source=metadata.get("title_source"),
        type_source=metadata.get("type_source"),
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


def _mark_origin_sources_needs_reindex(session: DbSession, origin_id: str) -> None:
    origin = session.get(KnowledgeOriginRecord, origin_id)
    if origin is None:
        return
    now = utc_now()
    session.exec(
        update(KnowledgeSourceRecord)
        .where(KnowledgeSourceRecord.origin_id == origin_id)
        .where(KnowledgeSourceRecord.status == "indexed")
        .values(status="needs_reindex", updated_at=now)
    )
    _mark_kb_needs_reindex(session, origin.knowledge_base_id)


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
        sort_order=record.sort_order,
        created_at=ensure_utc(record.created_at),
        knowledge_base=_knowledge_base_from_record(knowledge_base_record) if knowledge_base_record is not None else None,
    )
    MultimodalEmbeddingModelProfileRecord,
