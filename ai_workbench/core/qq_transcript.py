"""Bounded, identity-first QQ timeline reads. Processing bodies are loaded separately."""
import base64
import binascii
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, func, tuple_
from sqlalchemy.orm import defer
from sqlmodel import Session, select

from ai_workbench.core.history_page import HistoryQuery
from ai_workbench.core.schema.run import RunStepSchema
from ai_workbench.core.time import ensure_utc
from ai_workbench.db.models import RunRecord as R, RunStepRecord as S, SessionRecord
from ai_workbench.db.qq_models import QQBinding, QQMessage as M, QQDelivery as D, QQBatch, QQMedia, QQMediaAsset
from ai_workbench.db.stores import _run

ACTIVE = ("PENDING", "RUNNING", "CANCELLING", "WAITING_FOR_USER")
BINDING_PRIVATE = {"window_kind", "icebreaker_cooldown_until"}


class QQHistoryCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session_id: str
    time: float = Field(allow_inf_nan=False)
    kind: Literal[0, 1, 2]
    id: str | int

    @model_validator(mode="after")
    def identity(self):
        if (self.kind == 1 and not isinstance(self.id, str)) or (self.kind != 1 and type(self.id) is not int):
            raise ValueError("Invalid timeline identity")
        try:
            datetime.fromtimestamp(self.time, timezone.utc)
        except (OverflowError, OSError) as exc:
            raise ValueError("Invalid timeline timestamp") from exc
        return self

    def key(self):
        return self.time, self.kind, self.id

    def encode(self):
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode()

    @classmethod
    def decode(cls, value, session_id):
        try:
            cursor = cls.model_validate_json(base64.b64decode(value, altchars=b"-_", validate=True))
            if cursor.session_id != session_id:
                raise ValueError("Cursor belongs to another session")
            return cursor
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid QQ history cursor") from exc


def stamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return ensure_utc(value).timestamp() if isinstance(value, datetime) else value


def call_summary(step):
    """Keep the existing metrics/context schema without reading step bodies."""
    values = step.model_dump() if isinstance(step, RunStepSchema) else dict(step._mapping)
    metadata = values.pop("metadata", None)
    if metadata is None:
        metadata = json.loads(values.pop("metadata_json"))
    values = {key: value for key, value in values.items() if key not in {"message", "label", "context_snapshot_json"}}
    return RunStepSchema(**values, metadata={key: metadata[key] for key in ("llm", "context", "compaction", "operation") if key in metadata}).model_dump(mode="json")


class QQTranscriptReader:
    def __init__(self, state, store):
        self.state, self.engine = state, store.engine
        self.sql_runs = getattr(state.runs, "engine", None) is not None

    def _candidates(self, db, session_id, count, anchor=None, *, before=False, inclusive=False, memory_runs=()):
        candidates = []
        for kind, model, clock, identity, filters in (
            (0, M, M.timestamp, M.id, (M.deleted == False,)),
            (1, R, R.created_at, R.run_id, (R.kind == "chat",)),
            (2, D, D.created_at, D.id, (D.deleted == False, D.origin != "model")),
        ):
            if kind == 1 and not self.sql_runs:
                rows = [(stamp(row.created_at), kind, row.run_id) for row in memory_runs if row.kind == "chat"]
                if anchor:
                    rows = [key for key in rows if (key < anchor.key() if before else key >= anchor.key() if inclusive else key > anchor.key())]
                candidates.extend(sorted(rows, reverse=before)[:count])
                continue
            query = select(identity, clock).where(model.session_id == session_id, *filters)
            if anchor is not None:
                value = datetime.fromtimestamp(anchor.time, timezone.utc)
                native = value.isoformat() if kind == 0 else value if kind == 1 else anchor.time
                # DateTime storage rounds to microseconds; preserve the strict float boundary for deliveries.
                equal_time = stamp(native)
                lower = (equal_time, kind) < (anchor.time, anchor.kind)
                higher = (equal_time, kind) > (anchor.time, anchor.kind)
                equal = (equal_time, kind) == (anchor.time, anchor.kind)
                include_equal = lower if before else higher
                condition = clock < native if before else clock > native
                if include_equal:
                    condition = clock <= native if before else clock >= native
                elif equal:
                    key = tuple_(clock, identity)
                    condition = key < (native, anchor.id) if before else key >= (native, anchor.id) if inclusive else key > (native, anchor.id)
                query = query.where(condition)
            order = (clock.desc(), identity.desc()) if before else (clock, identity)
            rows = db.exec(query.order_by(*order).limit(count)).all()
            candidates.extend((stamp(time), kind, id) for id, time in rows)
        return sorted(candidates, reverse=before)[:count]

    def page(self, session_id: str, query: HistoryQuery, *, program_busy=False):
        value = next((cursor for cursor in (query.before, query.after, query.around) if cursor is not None), None)
        anchor = QQHistoryCursor.decode(value, session_id) if value is not None else None
        with Session(self.engine) as db:
            if self.sql_runs:
                # SQLite's legacy driver mode does not BEGIN on SELECT by itself.
                db.connection().exec_driver_sql("BEGIN")
            bound = db.get(QQBinding, session_id)
            if bound is None:
                raise KeyError(session_id)
            version = (db.exec(select(SessionRecord.history_version).where(SessionRecord.session_id == session_id)).one()
                if self.sql_runs else self.state.sessions.get_session(session_id).history_version)
            memory_runs = () if self.sql_runs else self.state.runs.list_runs(session_id)
            def read(count, position=None, **direction):
                return self._candidates(db, session_id, count, position, memory_runs=memory_runs, **direction)
            if query.around:
                earlier = list(reversed(read(query.limit // 2, anchor, before=True)))
                keys = earlier + read(query.limit - len(earlier), anchor, inclusive=True)
                if keys and len(keys) < query.limit and earlier:
                    first = QQHistoryCursor(session_id=session_id, time=keys[0][0], kind=keys[0][1], id=keys[0][2])
                    keys = list(reversed(read(query.limit - len(keys), first, before=True))) + keys
            elif query.after:
                keys = read(query.limit, anchor)
            else:
                keys = list(reversed(read(query.limit, anchor, before=True)))
            def cursor(key):
                return QQHistoryCursor(session_id=session_id, time=key[0], kind=key[1], id=key[2])
            has_before = bool(keys and read(1, cursor(keys[0]), before=True))
            has_after = bool(keys and read(1, cursor(keys[-1])))
            if self.sql_runs:
                visible = select(R).options(defer(R.config_snapshot_json), defer(R.harness_state_json)).where(R.session_id == session_id)
                # QQ execution is serial per Character; status lookup must not walk settled history.
                active = db.exec(visible.where(R.status.in_(ACTIVE)).limit(1)).first()
                completed_call = select(S.step_id).where(S.run_id == R.run_id, S.kind == "model", S.status.not_in(("pending", "running"))).exists()
                latest = db.exec(visible.where(completed_call).order_by(R.created_at.desc(), R.run_id.desc()).limit(1)).first()
            else:
                active = next((r for r in reversed(memory_runs) if r.status in ACTIVE), None)
                latest = next((r for r in reversed(memory_runs) if any(s.kind == "model" and s.status not in ("pending", "running")
                    for s in self.state.runs.list_steps(r.run_id))), None)
            run_ids = {key[2] for key in keys if key[1] == 1} | {row.run_id for row in (active, latest) if row is not None}
            runs = self._runs(db, run_ids, memory_runs)
            items, media = self._items(db, keys, runs)
            for item, key in zip(items, keys):
                item.update(id=f"qq-{('message', 'run', 'delivery')[key[1]]}-{key[2]}", cursor=cursor(key).encode(),
                    created_at=datetime.fromtimestamp(key[0], timezone.utc).isoformat())
            batch_busy = db.exec(select(QQBatch.id).where(QQBatch.session_id == session_id, QQBatch.status == "running").limit(1)).first() is not None
            page = dict(items=items, history_version=version,
                before_cursor=cursor(keys[0]).encode() if keys else None, after_cursor=cursor(keys[-1]).encode() if keys else None,
                has_before=has_before, has_after=has_after, active_run=runs.get(active.run_id) if active else None,
                latest_run=runs.get(latest.run_id) if latest else None,
                binding={**bound.model_dump(exclude=BINDING_PRIVATE), "history_version": version,
                    "busy": program_busy or batch_busy or active is not None})
            return page, bound, media

    def _runs(self, db, run_ids, memory_runs):
        if not run_ids:
            return {}
        if not self.sql_runs:
            return {row.run_id: {**row.model_dump(mode="json"), "steps": [call_summary(step)
                for step in self.state.runs.list_steps(row.run_id) if step.kind in ("model", "compaction") or step.metadata.get("operation") == "reset"]}
                for row in memory_runs if row.run_id in run_ids}
        rows = db.exec(select(R).options(defer(R.config_snapshot_json), defer(R.harness_state_json)).where(R.run_id.in_(run_ids))).all()
        calls = defaultdict(list)
        columns = [S.step_id, S.run_id, S.kind, S.status, S.order, S.started_at, S.finished_at, S.created_at, S.updated_at, S.metadata_json]
        for step in db.exec(select(*columns).where(S.run_id.in_(run_ids), or_(S.kind.in_(("model", "compaction")),
                func.json_extract(S.metadata_json, "$.operation") == "reset")).order_by(S.run_id, S.order, S.step_id)):
            calls[step.run_id].append(call_summary(step))
        return {row.run_id: {**_run(row).model_dump(mode="json"), "steps": calls[row.run_id]} for row in rows}

    def _items(self, db, keys, runs):
        message_ids = [key[2] for key in keys if key[1] == 0]
        run_ids = [key[2] for key in keys if key[1] == 1]
        delivery_ids = [key[2] for key in keys if key[1] == 2]
        messages = {row.id: row.model_dump(exclude={"deleted", "image_generation_keyword"})
            for row in db.exec(select(M).where(M.id.in_(message_ids)))} if message_ids else {}
        media = defaultdict(list)
        if message_ids:
            for occurrence, asset in db.exec(select(QQMedia, QQMediaAsset).outerjoin(QQMediaAsset, QQMedia.asset_id == QQMediaAsset.id)
                    .where(QQMedia.message_id.in_(message_ids)).order_by(QQMedia.message_id, QQMedia.segment_index)):
                occurrence._asset = asset
                media[occurrence.message_id].append(occurrence)
        by_id, by_run = {}, defaultdict(list)
        if run_ids or delivery_ids:
            for row, asset in db.exec(select(D, QQMediaAsset).outerjoin(QQMediaAsset, D.asset_id == QQMediaAsset.id).where(
                    D.deleted == False, or_(D.run_id.in_(run_ids), D.id.in_(delivery_ids))).order_by(D.id)):
                value = {**row.model_dump(exclude={"deleted"}), "description": asset.description if asset else None,
                    "attachment": asset.attachment.model_dump() if asset else None}
                by_id[row.id] = value
                by_run[row.run_id].append(value)
        return [dict(kind="incoming", message=messages[id]) if kind == 0 else
            dict(kind="reply", run=runs[id], deliveries=by_run[id]) if kind == 1 else
            dict(kind="program", delivery=by_id[id]) for _, kind, id in keys], media
