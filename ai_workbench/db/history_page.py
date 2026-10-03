"""Identity-first history pagination; no private run payloads in list reads."""
from collections import defaultdict

from sqlalchemy import func, literal, or_, select, tuple_, union_all
from sqlalchemy.orm import defer
from sqlmodel import Session

from ai_workbench.core.history_page import HistoryCursor, HistoryQuery, page_envelope
from ai_workbench.db.models import MessageRecord as M, RunRecord as R, RunStepRecord as S, SessionRecord
from ai_workbench.db.stores import _message, _run, _step


class SqlHistoryReader:
    def __init__(self, engine):
        self.engine = engine

    def reference_numbers(self, session_id, ids):
        result, cached = {}, {}
        ids = list(ids)
        with Session(self.engine) as db:
            for start in range(0, len(ids), 128):
                batch = ids[start:start + 128]
                messages = db.exec(select(M.message_id, M.created_at, M.role, M.run_id).where(M.session_id == session_id, M.message_id.in_(batch))).all()
                run_ids = set(batch) | {row.run_id for row in messages if row.run_id}
                runs = {row.run_id: row.created_at for row in db.exec(select(R.run_id, R.created_at).where(R.session_id == session_id, R.run_id.in_(run_ids)))}
                keys = {id: (time, 1, id) for id, time in runs.items() if id in batch}
                for row in messages:
                    if row.role == "user" or not row.run_id:
                        keys[row.message_id] = (row.created_at, 0, row.message_id)
                    elif row.run_id in runs:
                        keys[row.message_id] = (runs[row.run_id], 1, row.run_id)
                for id, key in keys.items():
                    if key not in cached:
                        message_count = db.exec(select(func.count()).select_from(M).where(M.session_id == session_id,
                            or_(M.role == "user", M.run_id.is_(None)), tuple_(M.created_at, literal(0), M.message_id) <= key)).scalar_one()
                        run_count = db.exec(select(func.count()).select_from(R).where(R.session_id == session_id,
                            tuple_(R.created_at, literal(1), R.run_id) <= key)).scalar_one()
                        cached[key] = message_count + run_count
                    result[id] = cached[key]
        return result

    def page(self, session_id: str, query: HistoryQuery, *, users: bool = False):
        messages = select(M.created_at.label("created_at"), literal(0).label("kind"), M.message_id.label("id")).where(
            M.session_id == session_id, or_(M.role == "user", M.run_id.is_(None)))
        runs = select(R.created_at.label("created_at"), literal(1).label("kind"), R.run_id.label("id")).where(R.session_id == session_id)
        all_items = union_all(messages, runs).subquery()
        candidates = (select(M.created_at.label("created_at"), literal(0).label("kind"), M.message_id.label("id")).where(
            M.session_id == session_id, M.role == "user").subquery() if users else all_items)
        key = tuple_(candidates.c.created_at, candidates.c.kind, candidates.c.id)
        order = (candidates.c.created_at, candidates.c.kind, candidates.c.id)
        value = query.before or query.after or query.around
        anchor = HistoryCursor.decode(value, session_id).key() if value else None
        with Session(self.engine) as db:
            version = db.exec(select(SessionRecord.history_version).where(SessionRecord.session_id == session_id)).scalar_one()

            def read(condition, count, descending=False):
                statement = select(candidates)
                if condition is not None:
                    statement = statement.where(condition)
                return db.exec(statement.order_by(*(c.desc() for c in order) if descending else order).limit(count)).all()

            if query.around:
                earlier = list(reversed(read(key < anchor, query.limit // 2, True)))
                rows = earlier + read(key >= anchor, query.limit - len(earlier))
            elif query.after:
                rows = read(key > anchor, query.limit)
            else:
                rows = list(reversed(read(key < anchor if anchor else None, query.limit, True)))
            keys = [tuple(row) for row in rows]
            global_key = tuple_(all_items.c.created_at, all_items.c.kind, all_items.c.id)
            if users:
                numbers = [db.exec(select(func.count()).select_from(all_items).where(global_key <= item)).scalar_one() for item in keys]
            else:
                preceding = db.exec(select(func.count()).select_from(all_items).where(global_key < keys[0])).scalar_one() if keys else 0
                numbers = range(preceding + 1, preceding + len(keys) + 1)
            has_before = bool(keys and db.exec(select(literal(1)).select_from(candidates).where(key < keys[0]).limit(1)).first())
            has_after = bool(keys and db.exec(select(literal(1)).select_from(candidates).where(key > keys[-1]).limit(1)).first())
            items = self._items(db, keys, users)
            active = None if users else db.exec(select(R).options(defer(R.config_snapshot_json), defer(R.harness_state_json)).where(
                R.session_id == session_id, R.status.in_(("PENDING", "RUNNING", "CANCELLING", "WAITING_FOR_USER")))
                .order_by(R.created_at.desc(), R.run_id.desc()).limit(1)).scalars().first()
            return page_envelope(session_id, keys, numbers, items, version, has_before, has_after,
                                 _run(active).model_dump(mode="json") if active else None)

    def _items(self, db, keys, users):
        message_ids = [key[2] for key in keys if key[1] == 0]
        run_ids = [key[2] for key in keys if key[1] == 1]
        if users:
            # SQLite extracts only a bounded preview; full parts/attachment text never leave the database.
            preview = func.substr(func.coalesce(func.json_extract(M.parts_json, "$[0].text"), ""), 1, 160)
            summaries = dict(db.exec(select(M.message_id, preview).where(M.message_id.in_(message_ids))).all())
            return [{"kind": "user", "summary": summaries[key[2]]} for key in keys]
        messages = db.exec(select(M).where(or_(M.message_id.in_(message_ids), M.run_id.in_(run_ids)))
                           .order_by(M.created_at, M.message_id)).scalars().all()
        by_id, by_run = {}, defaultdict(list)
        for row in messages:
            payload = _message(row).model_dump(mode="json")
            by_id[row.message_id] = payload
            by_run[row.run_id].append(payload)
        steps = defaultdict(list)
        for row in db.exec(select(S).options(defer(S.context_snapshot_json)).where(S.run_id.in_(run_ids)).order_by(S.order, S.step_id)).scalars():
            steps[row.run_id].append(_step(row).model_dump(mode="json"))
        runs = {row.run_id: {**_run(row).model_dump(mode="json"), "steps": steps[row.run_id]} for row in db.exec(
            select(R).options(defer(R.config_snapshot_json), defer(R.harness_state_json)).where(R.run_id.in_(run_ids))).scalars()}
        return [{"kind": "message", "message": by_id[key[2]]} if key[1] == 0 else
                {"kind": "reply", "run": runs[key[2]], "messages": by_run[key[2]]} for key in keys]
