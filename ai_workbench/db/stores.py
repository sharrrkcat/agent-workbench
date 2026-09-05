"""SQLite-backed stores matching the explicit Phase 1 core contracts."""

from __future__ import annotations

import json
from array import array
from typing import Any, Optional, TypeVar
from uuid import uuid4

from sqlmodel import Session as DbSession, delete, select

from ai_workbench.core.knowledge_settings import KnowledgeSettings, KnowledgeSettingsPatch, knowledge_settings_patch_updates
from ai_workbench.core.knowledge_store import KnowledgeBase, KnowledgeSource, KnowledgeSourceIndexResult, SessionKnowledgeBinding
from ai_workbench.core.message_parts import make_text_part, validate_message_parts
from ai_workbench.core.schema.message import MessageSchema, infer_speaker_identity
from ai_workbench.core.schema.run import RunSchema, RunStatus, RunStepKind, RunStepSchema, RunStepStatus
from ai_workbench.core.schema.run_event import RunEventSchema
from ai_workbench.core.session import Session
from ai_workbench.core.settings import AppSettings, AppSettingsPatch, app_settings_patch_updates
from ai_workbench.core.time import utc_now
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.worldbook import SessionWorldbookBinding, Worldbook, WorldbookEntry, WorldbookSettings, sync_worldbook_settings_patch
from ai_workbench.db.models import (
    AppMetadataRecord, KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeEmbeddingRecord,
    KnowledgeSettingsRecord, KnowledgeSourceRecord, MessageRecord,
    RunEventRecord, RunRecord, RunStepRecord, SessionKnowledgeBindingRecord, SessionRecord,
    SessionWorldbookBindingRecord, WorldbookEntryRecord, WorldbookRecord, WorldbookSettingsRecord,
)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


class SqlSessionStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def create_session(self, title: str = "", context_mode: str = "single_assistant") -> Session:
        record = SessionRecord(session_id=str(uuid4()), title=title, context_mode=context_mode, title_generation_state="pending" if not title.strip() or title.strip() == "New session" else "manual")
        with DbSession(self.engine) as db:
            db.add(record); db.commit(); db.refresh(record)
        return _session(record)

    def get_session(self, session_id: str) -> Session:
        with DbSession(self.engine) as db:
            record = db.get(SessionRecord, session_id)
            if record is None: raise KeyError(f"unknown session id: {session_id}")
            return _session(record)

    def _update(self, session_id: str, **values: Any) -> Session:
        with DbSession(self.engine) as db:
            record = db.get(SessionRecord, session_id)
            if record is None: raise KeyError(f"unknown session id: {session_id}")
            for key, value in values.items(): setattr(record, key, value)
            record.updated_at = utc_now(); db.add(record); db.commit(); db.refresh(record)
            return _session(record)

    def set_context_mode(self, session_id: str, context_mode: str) -> Session: return self._update(session_id, context_mode=context_mode)
    def set_title(self, session_id: str, title: str) -> Session: return self._update(session_id, title=title, title_generation_state="manual")
    def set_generated_title(self, session_id: str, title: str, metadata: Optional[dict[str, Any]] = None) -> Session: return self._update(session_id, title=title, title_generation_state="done", title_generation_metadata_json=_dump(metadata or {}))
    def set_title_generation_state(self, session_id: str, state: str, metadata: Optional[dict[str, Any]] = None) -> Session: return self._update(session_id, title_generation_state=state, title_generation_metadata_json=_dump(metadata or {}))
    def set_waiting_run(self, session_id: str, run_id: Optional[str]) -> Session: return self._update(session_id, waiting_run_id=run_id)
    def set_model_profile(self, session_id: str, profile_id: Optional[str]) -> Session: return self._update(session_id, model_profile_id=profile_id)

    def clear_interrupted_waiting_runs(self, run_ids: list[str]) -> None:
        if not run_ids: return
        with DbSession(self.engine) as db:
            rows = db.exec(select(SessionRecord).where(SessionRecord.waiting_run_id.in_(run_ids))).all()
            for row in rows: row.waiting_run_id = None; row.updated_at = utc_now(); db.add(row)
            db.commit()

    def delete_session(self, session_id: str) -> None:
        with DbSession(self.engine) as db:
            row = db.get(SessionRecord, session_id)
            if row is None: raise KeyError(f"unknown session id: {session_id}")
            db.delete(row); db.commit()

    def list_sessions(self) -> list[Session]:
        with DbSession(self.engine) as db:
            return [_session(row) for row in db.exec(select(SessionRecord).order_by(SessionRecord.updated_at.desc(), SessionRecord.created_at.desc())).all()]


class SqlMessageStore:
    def __init__(self, engine) -> None: self.engine = engine

    def add_message(self, session_id: str, role: str, content: Any = None, *, parts: list[dict[str, Any]] | None = None, run_id: str | None = None, parent_message_id: str | None = None, metadata: dict[str, Any] | None = None, speaker_type: str | None = None, speaker_id: str | None = None, speaker_name: str | None = None, origin: str | None = None, message_id: str | None = None) -> MessageSchema:
        metadata = dict(metadata or {})
        speaker = infer_speaker_identity(role, metadata=metadata, speaker_type=speaker_type, speaker_id=speaker_id, speaker_name=speaker_name, origin=origin)
        if parts is None: parts = [make_text_part(str(content), format="markdown" if role == "assistant" else "plain")] if content not in (None, "") else []
        validated = validate_message_parts(parts)
        record = MessageRecord(message_id=message_id or str(uuid4()), session_id=session_id, role=role, **speaker, parts_json=_dump(validated), run_id=run_id, parent_message_id=parent_message_id, metadata_json=_dump(metadata))
        with DbSession(self.engine) as db:
            db.add(record)
            session = db.get(SessionRecord, session_id)
            if session is not None: session.updated_at = utc_now(); db.add(session)
            db.commit(); db.refresh(record)
        return _message(record)

    def get_message(self, message_id: str) -> MessageSchema:
        with DbSession(self.engine) as db:
            row = db.get(MessageRecord, message_id)
            if row is None: raise KeyError(f"unknown message id: {message_id}")
            return _message(row)

    def update_message(self, message: MessageSchema) -> MessageSchema:
        with DbSession(self.engine) as db:
            row = db.get(MessageRecord, message.message_id)
            if row is None: raise KeyError(f"unknown message id: {message.message_id}")
            row.role = message.role; row.speaker_type = message.speaker_type; row.speaker_id = message.speaker_id; row.speaker_name = message.speaker_name; row.origin = message.origin; row.content_version = message.content_version; row.parts_json = _dump(message.parts); row.run_id = message.run_id; row.parent_message_id = message.parent_message_id; row.metadata_json = _dump(message.metadata)
            db.add(row); db.commit(); db.refresh(row)
            return _message(row)

    def delete_message(self, message_id: str) -> MessageSchema:
        with DbSession(self.engine) as db:
            row = db.get(MessageRecord, message_id)
            if row is None: raise KeyError(f"unknown message id: {message_id}")
            result = _message(row); db.delete(row); db.commit(); return result

    def delete_messages_after(self, session_id: str, message_id: str, include_target: bool = False) -> list[MessageSchema]:
        rows = self.list_messages(session_id); index = next((i for i, item in enumerate(rows) if item.message_id == message_id), None)
        if index is None: raise KeyError(f"unknown message id: {message_id}")
        deleted = rows[index if include_target else index + 1:]
        with DbSession(self.engine) as db:
            for item in deleted:
                row = db.get(MessageRecord, item.message_id)
                if row is not None: db.delete(row)
            db.commit()
        return deleted

    def list_messages(self, session_id: str) -> list[MessageSchema]:
        with DbSession(self.engine) as db: return [_message(row) for row in db.exec(select(MessageRecord).where(MessageRecord.session_id == session_id).order_by(MessageRecord.created_at)).all()]
    def list_all_messages(self) -> list[MessageSchema]:
        with DbSession(self.engine) as db: return [_message(row) for row in db.exec(select(MessageRecord).order_by(MessageRecord.created_at)).all()]
    def delete_session(self, session_id: str) -> None:
        with DbSession(self.engine) as db: db.exec(delete(MessageRecord).where(MessageRecord.session_id == session_id)); db.commit()
    def find_latest_assistant_message(self, session_id: str) -> MessageSchema | None:
        return next((item for item in reversed(self.list_messages(session_id)) if item.role == "assistant"), None)


class SqlRunStore:
    def __init__(self, engine) -> None: self.engine = engine

    def create_run(self, kind: str, target: str, session_id: str, metadata: dict[str, Any] | None = None) -> RunSchema:
        row = RunRecord(run_id=str(uuid4()), kind=kind, target=target, session_id=session_id, status=RunStatus.PENDING.value, metadata_json=_dump(metadata or {}))
        with DbSession(self.engine) as db: db.add(row); db.commit(); db.refresh(row)
        return _run(row)

    def get_run(self, run_id: str) -> RunSchema:
        with DbSession(self.engine) as db:
            row = db.get(RunRecord, run_id)
            if row is None: raise KeyError(f"unknown run id: {run_id}")
            return _run(row)

    def update_status(self, run_id: str, status: RunStatus, current_step: str | None = None, error: str | None = None, error_code: str | None = None, error_message: str | None = None, cancel_requested: bool | None = None) -> RunSchema:
        with DbSession(self.engine) as db:
            row = db.get(RunRecord, run_id)
            if row is None: raise KeyError(f"unknown run id: {run_id}")
            row.status = status.value if isinstance(status, RunStatus) else str(status); now = utc_now()
            if row.status == RunStatus.RUNNING.value and row.started_at is None: row.started_at = now
            if row.status in {item.value for item in (RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED)}: row.finished_at = now
            if current_step is not None: row.current_step = current_step; row.stage = current_step
            if error is not None: row.error = error; row.error_message = error
            if error_code is not None: row.error_code = error_code
            if error_message is not None: row.error_message = error_message; row.error = error_message
            if cancel_requested is not None: row.cancel_requested = cancel_requested
            row.updated_at = now; db.add(row); db.commit(); db.refresh(row); return _run(row)

    def update_progress(self, run_id: str, stage: str | None = None, message: str | None = None, current: int | None = None, total: int | None = None) -> RunSchema:
        with DbSession(self.engine) as db:
            row = db.get(RunRecord, run_id)
            if row is None: raise KeyError(f"unknown run id: {run_id}")
            if stage is not None: row.stage = stage; row.current_step = stage
            if message is not None: row.progress_message = message
            if current is not None: row.progress_current = current
            if total is not None: row.progress_total = total
            row.updated_at = utc_now(); db.add(row); db.commit(); db.refresh(row); return _run(row)

    def update_metadata(self, run_id: str, metadata: dict[str, Any]) -> RunSchema:
        with DbSession(self.engine) as db:
            row = db.get(RunRecord, run_id)
            if row is None: raise KeyError(f"unknown run id: {run_id}")
            row.metadata_json = _dump(metadata); row.updated_at = utc_now(); db.add(row); db.commit(); db.refresh(row); return _run(row)

    def list_runs(self, session_id: str) -> list[RunSchema]:
        with DbSession(self.engine) as db: return [_run(row) for row in db.exec(select(RunRecord).where(RunRecord.session_id == session_id).order_by(RunRecord.created_at)).all()]
    def list_all_runs(self) -> list[RunSchema]:
        with DbSession(self.engine) as db: return [_run(row) for row in db.exec(select(RunRecord).order_by(RunRecord.created_at)).all()]
    def delete_session(self, session_id: str) -> None:
        with DbSession(self.engine) as db: db.exec(delete(RunRecord).where(RunRecord.session_id == session_id)); db.commit()
    def cancel_runs(self, run_ids: list[str], reason: str = "Run was cancelled.") -> list[RunSchema]:
        result = []
        for run_id in run_ids:
            try: run = self.get_run(run_id)
            except KeyError: continue
            if run.status in {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}: continue
            result.append(self.update_status(run_id, RunStatus.CANCELLED, current_step="cancelled", error=reason, error_code="RUN_CANCELLED", cancel_requested=True))
        return result
    def interrupt_unfinished_runs(self) -> list[str]:
        result=[]
        for run in self.list_all_runs():
            if run.status not in {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}:
                self.update_status(run.run_id, RunStatus.INTERRUPTED, current_step="interrupted"); result.append(run.run_id)
        return result

    def create_step(self, run_id: str, kind: RunStepKind, label: str = "", message: str | None = None, metadata: dict[str, Any] | None = None, status: RunStepStatus = RunStepStatus.RUNNING, parent_step_id: str | None = None) -> RunStepSchema:
        self.get_run(run_id)
        if parent_step_id is not None and self.get_step(parent_step_id).run_id != run_id:
            raise ValueError("parent_step_id must belong to the same run")
        with DbSession(self.engine) as db:
            count = len(db.exec(select(RunStepRecord).where(RunStepRecord.run_id == run_id)).all()); now = utc_now()
            row = RunStepRecord(step_id=str(uuid4()), run_id=run_id, kind=kind, parent_step_id=parent_step_id, label=label, status=status.value, message=message or "", order=count, started_at=now if status == RunStepStatus.RUNNING else None, metadata_json=_dump(metadata or {}), created_at=now, updated_at=now)
            db.add(row); db.commit(); db.refresh(row); return _step(row)

    def update_step(self, step_id: str, status: RunStepStatus | None = None, message: str | None = None, error_code: str | None = None, error_message: str | None = None, metadata: dict[str, Any] | None = None) -> RunStepSchema:
        with DbSession(self.engine) as db:
            row = db.get(RunStepRecord, step_id)
            if row is None: raise KeyError(f"unknown run step id: {step_id}")
            now = utc_now()
            if status is not None: row.status = status.value; row.started_at = row.started_at or (now if status == RunStepStatus.RUNNING else None); row.finished_at = now if status in {RunStepStatus.COMPLETED, RunStepStatus.FAILED, RunStepStatus.SKIPPED} else row.finished_at
            if message is not None: row.message = message
            if error_code is not None: row.error_code = error_code
            if error_message is not None: row.error_message = error_message
            if metadata is not None: row.metadata_json = _dump({**_load(row.metadata_json, {}), **metadata})
            row.updated_at = now; db.add(row); db.commit(); db.refresh(row); return _step(row)
    def get_step(self, step_id: str) -> RunStepSchema:
        with DbSession(self.engine) as db:
            row = db.get(RunStepRecord, step_id)
            if row is None: raise KeyError(f"unknown run step id: {step_id}")
            return _step(row)
    def list_steps(self, run_id: str) -> list[RunStepSchema]:
        with DbSession(self.engine) as db: return [_step(row) for row in db.exec(select(RunStepRecord).where(RunStepRecord.run_id == run_id).order_by(RunStepRecord.order)).all()]


class SqlRunEventStore:
    def __init__(self, engine) -> None: self.engine = engine
    def add_event(self, run_id: str, session_id: str, type: str, message: str = "", payload: dict[str, Any] | None = None) -> RunEventSchema:
        row = RunEventRecord(event_id=str(uuid4()), run_id=run_id, session_id=session_id, type=type, message=message, payload_json=_dump(payload or {}), created_at=utc_now())
        with DbSession(self.engine) as db: db.add(row); db.commit(); db.refresh(row)
        return _event(row)
    def list_events(self, run_id: str) -> list[RunEventSchema]:
        with DbSession(self.engine) as db: return [_event(row) for row in db.exec(select(RunEventRecord).where(RunEventRecord.run_id == run_id).order_by(RunEventRecord.created_at)).all()]
    def delete_session(self, session_id: str) -> None:
        with DbSession(self.engine) as db: db.exec(delete(RunEventRecord).where(RunEventRecord.session_id == session_id)); db.commit()


class SqlAppSettingsStore:
    def __init__(self, engine) -> None: self.engine=engine
    def get(self) -> AppSettings:
        with DbSession(self.engine) as db:
            row=db.get(AppMetadataRecord,"app_settings")
            return AppSettings.model_validate(_load(row.value if row else None, {}))
    def patch(self, values: dict[str, Any]) -> AppSettings:
        current=self.get(); patch=AppSettingsPatch.model_validate(values); updates=app_settings_patch_updates(patch)
        data=current.model_dump(); nested=updates.pop("pet",None)
        if isinstance(nested,dict):
            pet=dict(data.get("pet") or {});
            for key in ("position","bubble_texts"):
                sub=nested.pop(key,None)
                if isinstance(sub,dict): pet[key]={**(pet.get(key) or {}),**sub}
            pet.update(nested); data["pet"]=pet
        data.update(updates); result=AppSettings.model_validate(data)
        with DbSession(self.engine) as db:
            row=db.get(AppMetadataRecord,"app_settings")
            if row is None: row=AppMetadataRecord(key="app_settings",value=_dump(result.model_dump()))
            else: row.value=_dump(result.model_dump()); row.updated_at=utc_now()
            db.add(row); db.commit()
        return result


class SqlWorldbookStore:
    def __init__(self, engine) -> None: self.engine=engine
    def get_settings(self) -> WorldbookSettings:
        with DbSession(self.engine) as db:
            row=db.get(WorldbookSettingsRecord,1)
            return _worldbook_settings(row) if row else WorldbookSettings()
    def patch_settings(self, values: dict[str, Any]) -> WorldbookSettings:
        current=self.get_settings(); data=current.model_dump(); data.update(sync_worldbook_settings_patch(values)); result=WorldbookSettings.model_validate(data)
        with DbSession(self.engine) as db:
            row=db.get(WorldbookSettingsRecord,1) or WorldbookSettingsRecord(id=1)
            for key,val in result.model_dump(exclude={"id","created_at","updated_at"}).items(): setattr(row,key,val)
            row.updated_at=utc_now(); db.add(row); db.commit(); db.refresh(row); return _worldbook_settings(row)
    def list_worldbooks(self) -> list[Worldbook]:
        with DbSession(self.engine) as db: return [_worldbook(row,db) for row in db.exec(select(WorldbookRecord).order_by(WorldbookRecord.name)).all()]
    def create_worldbook(self, worldbook: Worldbook) -> Worldbook:
        row=WorldbookRecord(id=worldbook.id,name=worldbook.name,description=worldbook.description,enabled=worldbook.enabled,created_at=worldbook.created_at,updated_at=worldbook.updated_at)
        with DbSession(self.engine) as db: db.add(row); db.commit(); db.refresh(row); return _worldbook(row,db)
    def get_worldbook(self, worldbook_id: str) -> Worldbook:
        with DbSession(self.engine) as db:
            row=db.get(WorldbookRecord,worldbook_id)
            if row is None: raise KeyError(f"unknown worldbook: {worldbook_id}")
            return _worldbook(row,db)
    def update_worldbook(self, worldbook_id: str, values: dict[str, Any]) -> Worldbook:
        with DbSession(self.engine) as db:
            row=db.get(WorldbookRecord,worldbook_id)
            if row is None: raise KeyError(f"unknown worldbook: {worldbook_id}")
            for key,val in values.items(): setattr(row,key,val)
            row.updated_at=utc_now(); db.add(row); db.commit(); db.refresh(row); return _worldbook(row,db)
    def delete_worldbook(self, worldbook_id: str) -> Worldbook:
        current=self.get_worldbook(worldbook_id)
        with DbSession(self.engine) as db:
            db.exec(delete(WorldbookEntryRecord).where(WorldbookEntryRecord.worldbook_id==worldbook_id)); db.exec(delete(SessionWorldbookBindingRecord).where(SessionWorldbookBindingRecord.worldbook_id==worldbook_id)); row=db.get(WorldbookRecord,worldbook_id); db.delete(row); db.commit()
        return current
    def list_entries(self, worldbook_id: str) -> list[WorldbookEntry]:
        with DbSession(self.engine) as db: return [_entry(row) for row in db.exec(select(WorldbookEntryRecord).where(WorldbookEntryRecord.worldbook_id==worldbook_id).order_by(WorldbookEntryRecord.sort_order,WorldbookEntryRecord.created_at)).all()]
    def create_entry(self, entry: WorldbookEntry) -> WorldbookEntry:
        row=WorldbookEntryRecord(id=entry.id,worldbook_id=entry.worldbook_id,name=entry.name,keywords_text=entry.keywords_text,content=entry.content,activation_mode=entry.activation_mode,enabled=entry.enabled,sort_order=entry.sort_order,created_at=entry.created_at,updated_at=entry.updated_at)
        with DbSession(self.engine) as db: db.add(row); db.commit(); db.refresh(row); return _entry(row)
    def get_entry(self, entry_id: str) -> WorldbookEntry:
        with DbSession(self.engine) as db:
            row=db.get(WorldbookEntryRecord,entry_id)
            if row is None: raise KeyError(f"unknown worldbook entry: {entry_id}")
            return _entry(row)
    def update_entry(self, entry_id: str, values: dict[str, Any]) -> WorldbookEntry:
        with DbSession(self.engine) as db:
            row=db.get(WorldbookEntryRecord,entry_id)
            if row is None: raise KeyError(f"unknown worldbook entry: {entry_id}")
            for key,val in values.items(): setattr(row,key,val)
            row.updated_at=utc_now(); db.add(row); db.commit(); db.refresh(row); return _entry(row)
    def delete_entry(self, entry_id: str) -> WorldbookEntry:
        current=self.get_entry(entry_id)
        with DbSession(self.engine) as db: db.delete(db.get(WorldbookEntryRecord,entry_id)); db.commit()
        return current
    def reorder_entries(self, worldbook_id: str, entry_ids: list[str]) -> list[WorldbookEntry]:
        current=self.list_entries(worldbook_id)
        if {item.id for item in current} != set(entry_ids): raise ValueError("Reorder ids must exactly match entries in this worldbook.")
        with DbSession(self.engine) as db:
            for index,item_id in enumerate(entry_ids):
                row=db.get(WorldbookEntryRecord,item_id); row.sort_order=(index+1)*10; row.updated_at=utc_now(); db.add(row)
            db.commit()
        return self.list_entries(worldbook_id)
    def list_session_bindings(self, session_id: str) -> list[SessionWorldbookBinding]:
        with DbSession(self.engine) as db:
            rows=db.exec(select(SessionWorldbookBindingRecord).where(SessionWorldbookBindingRecord.session_id==session_id).order_by(SessionWorldbookBindingRecord.sort_order)).all(); result=[]
            for row in rows:
                wb=db.get(WorldbookRecord,row.worldbook_id); result.append(SessionWorldbookBinding(id=row.id,session_id=row.session_id,worldbook_id=row.worldbook_id,enabled=row.enabled,sort_order=row.sort_order,created_at=row.created_at,updated_at=row.updated_at,worldbook=_worldbook(wb,db) if wb else None))
            return result
    def replace_session_bindings(self, session_id: str, worldbook_ids: list[str]) -> tuple[list[SessionWorldbookBinding], list[str]]:
        warnings=[]
        with DbSession(self.engine) as db:
            db.exec(delete(SessionWorldbookBindingRecord).where(SessionWorldbookBindingRecord.session_id==session_id)); seen=set()
            for index,worldbook_id in enumerate(worldbook_ids):
                if worldbook_id in seen: continue
                row=db.get(WorldbookRecord,worldbook_id)
                if row is None: raise KeyError(f"unknown worldbook: {worldbook_id}")
                if not row.enabled: warnings.append(f"Worldbook is disabled and was not bound: {worldbook_id}"); continue
                seen.add(worldbook_id); db.add(SessionWorldbookBindingRecord(id=str(uuid4()),session_id=session_id,worldbook_id=worldbook_id,sort_order=(index+1)*10))
            db.commit()
        return self.list_session_bindings(session_id),warnings
    def delete_session_bindings(self, session_id: str) -> None:
        with DbSession(self.engine) as db: db.exec(delete(SessionWorldbookBindingRecord).where(SessionWorldbookBindingRecord.session_id==session_id)); db.commit()


class SqlKnowledgeStore:
    def __init__(self, engine) -> None: self.engine=engine
    def get_settings(self) -> KnowledgeSettings:
        with DbSession(self.engine) as db:
            row=db.get(KnowledgeSettingsRecord,1); return KnowledgeSettings.model_validate(row.model_dump(exclude={"created_at", "updated_at"}) if row else KnowledgeSettings().model_dump())
    def patch_settings(self, values: dict[str, Any]) -> KnowledgeSettings:
        current=self.get_settings(); patch=KnowledgeSettingsPatch.model_validate(values); result=KnowledgeSettings.model_validate({**current.model_dump(),**knowledge_settings_patch_updates(patch)})
        with DbSession(self.engine) as db:
            row=db.get(KnowledgeSettingsRecord,1) or KnowledgeSettingsRecord(id=1)
            for key,val in result.model_dump(exclude={"id"}).items(): setattr(row,key,val)
            row.updated_at=utc_now(); db.add(row); db.commit(); db.refresh(row)
        return result
    def invalidate_base_index(self, base_id: str) -> None:
        with DbSession(self.engine) as db:
            base = db.get(KnowledgeBaseRecord, base_id)
            if base is None:
                raise KeyError(base_id)
            base.index_status = "needs_reindex"
            db.add(base)
            for source in db.exec(select(KnowledgeSourceRecord).where(KnowledgeSourceRecord.knowledge_base_id == base_id)).all():
                source.status = "needs_reindex"
                db.add(source)
            db.exec(delete(KnowledgeEmbeddingRecord).where(KnowledgeEmbeddingRecord.knowledge_base_id == base_id))
            db.commit()

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        with DbSession(self.engine) as db: return [_kb(row) for row in db.exec(select(KnowledgeBaseRecord).order_by(KnowledgeBaseRecord.name)).all()]
    def create_knowledge_base(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        row=KnowledgeBaseRecord(**knowledge_base.model_dump());
        with DbSession(self.engine) as db: db.add(row); db.commit(); db.refresh(row)
        return _kb(row)
    def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        with DbSession(self.engine) as db:
            row=db.get(KnowledgeBaseRecord,knowledge_base_id)
            if row is None: raise KeyError(f"unknown knowledge base: {knowledge_base_id}")
            return _kb(row)
    def update_knowledge_base(self, knowledge_base_id: str, values: dict[str, Any]) -> KnowledgeBase:
        current=self.get_knowledge_base(knowledge_base_id); result=KnowledgeBase.model_validate({**current.model_dump(),**values,"updated_at":utc_now().isoformat()})
        with DbSession(self.engine) as db:
            row=db.get(KnowledgeBaseRecord,knowledge_base_id)
            for key,val in result.model_dump().items(): setattr(row,key,val)
            db.add(row); db.commit(); db.refresh(row); return _kb(row)
    def delete_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        current=self.get_knowledge_base(knowledge_base_id)
        with DbSession(self.engine) as db:
            sources=db.exec(select(KnowledgeSourceRecord).where(KnowledgeSourceRecord.knowledge_base_id==knowledge_base_id)).all()
            for source in sources:
                db.exec(delete(KnowledgeChunkRecord).where(KnowledgeChunkRecord.source_id==source.id)); db.exec(delete(KnowledgeEmbeddingRecord).where(KnowledgeEmbeddingRecord.source_id==source.id))
            db.exec(delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.knowledge_base_id==knowledge_base_id)); db.exec(delete(SessionKnowledgeBindingRecord).where(SessionKnowledgeBindingRecord.knowledge_base_id==knowledge_base_id)); db.delete(db.get(KnowledgeBaseRecord,knowledge_base_id)); db.commit()
        return current
    def list_session_bindings(self, session_id: str) -> list[SessionKnowledgeBinding]:
        with DbSession(self.engine) as db:
            rows=db.exec(select(SessionKnowledgeBindingRecord).where(SessionKnowledgeBindingRecord.session_id==session_id).order_by(SessionKnowledgeBindingRecord.sort_order)).all(); return [SessionKnowledgeBinding(id=row.id,session_id=row.session_id,knowledge_base_id=row.knowledge_base_id,enabled=row.enabled,sort_order=row.sort_order,created_at=row.created_at,knowledge_base=_kb(db.get(KnowledgeBaseRecord,row.knowledge_base_id)) if db.get(KnowledgeBaseRecord,row.knowledge_base_id) else None) for row in rows]
    def replace_session_bindings(self, session_id: str, knowledge_base_ids: list[str]) -> list[SessionKnowledgeBinding]:
        with DbSession(self.engine) as db:
            db.exec(delete(SessionKnowledgeBindingRecord).where(SessionKnowledgeBindingRecord.session_id==session_id))
            for index,kb_id in enumerate(dict.fromkeys(knowledge_base_ids)): db.add(SessionKnowledgeBindingRecord(session_id=session_id,knowledge_base_id=kb_id,sort_order=(index+1)*10))
            db.commit()
        return self.list_session_bindings(session_id)
    def delete_session_bindings(self, session_id: str) -> None:
        with DbSession(self.engine) as db: db.exec(delete(SessionKnowledgeBindingRecord).where(SessionKnowledgeBindingRecord.session_id==session_id)); db.commit()
    def list_sources(self, knowledge_base_id: str) -> list[KnowledgeSource]:
        with DbSession(self.engine) as db: return [_source(row,db) for row in db.exec(select(KnowledgeSourceRecord).where(KnowledgeSourceRecord.knowledge_base_id==knowledge_base_id).order_by(KnowledgeSourceRecord.created_at)).all()]
    def get_source(self, source_id: str) -> KnowledgeSource:
        with DbSession(self.engine) as db:
            row=db.get(KnowledgeSourceRecord,source_id)
            if row is None: raise KeyError(f"unknown knowledge source: {source_id}")
            return _source(row,db)
    def upsert_indexed_source(self, *, source: KnowledgeSource, chunks: list[Any], vectors: list[list[float]], embedding_model_profile: ModelProfile, embedding_dimension: int, search_texts: list[str]) -> KnowledgeSourceIndexResult:
        with DbSession(self.engine) as db:
            row=db.get(KnowledgeSourceRecord,source.id)
            values = source.model_dump(exclude={"chunks", "metadata"})
            values["metadata_json"] = _dump(source.metadata)
            values.pop("indexed_at", None)
            if row is None:
                row=KnowledgeSourceRecord(**values)
            for key,val in values.items():
                if hasattr(row, key): setattr(row,key,val)
            row.status="indexed"; row.indexed_at=utc_now(); row.error=None; row.updated_at=utc_now()
            db.add(row); db.flush()
            db.exec(delete(KnowledgeChunkRecord).where(KnowledgeChunkRecord.source_id==source.id)); db.exec(delete(KnowledgeEmbeddingRecord).where(KnowledgeEmbeddingRecord.source_id==source.id))
            # FTS5 is a separate virtual table, so replace its rows together
            # with the relational index.  This is deliberately best-effort on
            # non-SQLite engines where the table is not present.
            if self.engine.dialect.name == "sqlite":
                db.connection().exec_driver_sql("DELETE FROM kb_chunk_fts WHERE source_id = ?", (source.id,))
            for index,chunk in enumerate(chunks):
                chunk_id=str(uuid4()); db.add(KnowledgeChunkRecord(id=chunk_id,knowledge_base_id=source.knowledge_base_id,source_id=source.id,chunk_index=index,heading_path=chunk.heading_path,content=chunk.content,char_start=chunk.char_start,char_end=chunk.char_end,token_count=getattr(chunk,"token_count",None),content_hash=chunk.content_hash,metadata_json=_dump(chunk.metadata)))
                if index < len(vectors): db.add(KnowledgeEmbeddingRecord(id=str(uuid4()),knowledge_base_id=source.knowledge_base_id,source_id=source.id,chunk_id=chunk_id,embedding_model_profile_id=embedding_model_profile.id,embedding_model_id_snapshot=embedding_model_profile.model_ref,embedding_dimension=embedding_dimension,embedding_normalize_snapshot=embedding_model_profile.parameters["normalize"],vector_blob=array("f", [float(value) for value in vectors[index]]).tobytes()))
                if self.engine.dialect.name == "sqlite":
                    search_text = search_texts[index] if index < len(search_texts) else chunk.content
                    db.connection().exec_driver_sql("INSERT INTO kb_chunk_fts (chunk_id, knowledge_base_id, source_id, title, heading_path, content, search_text) VALUES (?, ?, ?, ?, ?, ?, ?)", (chunk_id, source.knowledge_base_id, source.id, source.title, chunk.heading_path, chunk.content, search_text))
            kb = db.get(KnowledgeBaseRecord, source.knowledge_base_id)
            if kb is not None:
                kb.index_status = "ready"; kb.index_error = None; kb.updated_at = utc_now(); db.add(kb)
            db.commit()
        return KnowledgeSourceIndexResult(source_id=source.id,status="indexed",chunks=len(chunks),embedding_model_profile_id=embedding_model_profile.id,embedding_dimension=embedding_dimension,indexed_at=utc_now())
    def mark_source_failed(self, source: KnowledgeSource, error: str) -> KnowledgeSourceIndexResult:
        with DbSession(self.engine) as db:
            row=db.get(KnowledgeSourceRecord,source.id)
            values=source.model_dump(exclude={"chunks", "metadata"}); values["metadata_json"]=_dump(source.metadata); values.pop("indexed_at",None)
            if row is None: row=KnowledgeSourceRecord(**values)
            row.status="failed"; row.error=error; db.add(row); db.commit()
        return KnowledgeSourceIndexResult(source_id=source.id,status="failed",chunks=0,error=error)
    def delete_source(self, source_id: str) -> KnowledgeSource:
        current=self.get_source(source_id)
        with DbSession(self.engine) as db:
            db.exec(delete(KnowledgeChunkRecord).where(KnowledgeChunkRecord.source_id==source_id)); db.exec(delete(KnowledgeEmbeddingRecord).where(KnowledgeEmbeddingRecord.source_id==source_id))
            if self.engine.dialect.name == "sqlite": db.connection().exec_driver_sql("DELETE FROM kb_chunk_fts WHERE source_id = ?", (source_id,))
            db.delete(db.get(KnowledgeSourceRecord,source_id)); db.commit()
        return current
    def source_text_reference(self, source_id: str) -> dict[str, Any]:
        source=self.get_source(source_id); return {"source_id":source.id,"uri":source.uri,"title":source.title}


def _session(row: SessionRecord) -> Session:
    return Session(session_id=row.session_id,title=row.title,context_mode=row.context_mode,waiting_run_id=row.waiting_run_id,model_profile_id=row.model_profile_id,title_generation_state=row.title_generation_state,title_generation_metadata=_load(row.title_generation_metadata_json,{}),created_at=row.created_at,updated_at=row.updated_at)
def _message(row: MessageRecord) -> MessageSchema:
    return MessageSchema(message_id=row.message_id,session_id=row.session_id,role=row.role,speaker_type=row.speaker_type,speaker_id=row.speaker_id,speaker_name=row.speaker_name,origin=row.origin,content_version=row.content_version,parts=_load(row.parts_json,[]),run_id=row.run_id,parent_message_id=row.parent_message_id,metadata=_load(row.metadata_json,{}),created_at=row.created_at)
def _run(row: RunRecord) -> RunSchema:
    return RunSchema(run_id=row.run_id,session_id=row.session_id,kind=row.kind,target=row.target,status=row.status,current_step=row.current_step,stage=row.stage,progress_message=row.progress_message,progress_current=row.progress_current,progress_total=row.progress_total,cancel_requested=row.cancel_requested,started_at=row.started_at,finished_at=row.finished_at,error_code=row.error_code,error_message=row.error_message,error=row.error,metadata=_load(row.metadata_json,{}),created_at=row.created_at,updated_at=row.updated_at)
def _step(row: RunStepRecord) -> RunStepSchema:
    return RunStepSchema(step_id=row.step_id,run_id=row.run_id,kind=row.kind,parent_step_id=row.parent_step_id,label=row.label,status=row.status,message=row.message,order=row.order,started_at=row.started_at,finished_at=row.finished_at,error_code=row.error_code,error_message=row.error_message,metadata=_load(row.metadata_json,{}),created_at=row.created_at,updated_at=row.updated_at)
def _event(row: RunEventRecord) -> RunEventSchema:
    return RunEventSchema(event_id=row.event_id,run_id=row.run_id,session_id=row.session_id,type=row.type,message=row.message,payload=_load(row.payload_json,{}),created_at=row.created_at)
def _worldbook_settings(row: WorldbookSettingsRecord) -> WorldbookSettings: return WorldbookSettings(**{key:getattr(row,key) for key in WorldbookSettings.model_fields if hasattr(row,key)})
def _worldbook(row: WorldbookRecord, db: DbSession) -> Worldbook:
    entries=len(db.exec(select(WorldbookEntryRecord).where(WorldbookEntryRecord.worldbook_id==row.id)).all()); bindings=len(db.exec(select(SessionWorldbookBindingRecord).where(SessionWorldbookBindingRecord.worldbook_id==row.id,SessionWorldbookBindingRecord.enabled==True)).all()); return Worldbook(id=row.id,name=row.name,description=row.description,enabled=row.enabled,created_at=row.created_at,updated_at=row.updated_at,entry_count=entries,active_binding_count=bindings)
def _entry(row: WorldbookEntryRecord) -> WorldbookEntry: return WorldbookEntry(id=row.id,worldbook_id=row.worldbook_id,name=row.name,keywords_text=row.keywords_text,content=row.content,activation_mode=row.activation_mode,enabled=row.enabled,sort_order=row.sort_order,created_at=row.created_at,updated_at=row.updated_at)
def _kb(row: KnowledgeBaseRecord) -> KnowledgeBase: return KnowledgeBase(**{key:getattr(row,key) for key in KnowledgeBase.model_fields if hasattr(row,key)})
def _source(row: KnowledgeSourceRecord, db: DbSession) -> KnowledgeSource:
    chunks=db.exec(select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.source_id==row.id)).all(); return KnowledgeSource(id=row.id,knowledge_base_id=row.knowledge_base_id,source_type=row.source_type,uri=row.uri,title=row.title,relative_path=row.relative_path,virtual_path=row.virtual_path,folder_path=row.folder_path,file_name=row.file_name,extension=row.extension,path_depth=row.path_depth,file_status=row.file_status,source_mtime=row.source_mtime,source_size_bytes=row.source_size_bytes,mime_type=row.mime_type,size_bytes=row.size_bytes,content_hash=row.content_hash,indexed_at=row.indexed_at,status=row.status,error=row.error,metadata=_load(row.metadata_json,{}),chunks=len(chunks))
