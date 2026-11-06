"""SQLite and in-memory durable fact storage with the same access predicate."""

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from threading import RLock

from sqlalchemy import and_, or_, false, delete, func, update, text
from sqlmodel import Session as DbSession, select

from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.memory_search import entry_terms, query_terms
from ai_workbench.core.schema.memory import MemoryEntry, MemoryView
from ai_workbench.core.time import utc_now
from ai_workbench.db.memory_models import DurableMemoryRecord as Record, DurableMemoryTerm as Term
from ai_workbench.db.memory_models import DurableMemoryDependency as Dependency, DurableMemoryEvidence as Evidence
from ai_workbench.db.models import SessionRecord, ContextCheckpointRecord, ContextRetrievalRecord


def conflict():
    return ChatError("MEMORY_CONFLICT", "Memory changed. Reload it before trying again.", 409)


class DurableMemoryStore:
    def __init__(self, sessions, engine=None, *, messages, runs, run_events, characters):
        self.sessions = sessions
        self.engine = engine
        self.messages, self.runs, self.run_events, self.characters = messages, runs, run_events, characters
        self.lock = RLock()
        self._entries: dict[str, MemoryEntry] = {}
        self._terms: dict[str, dict[str, int]] = {}
        self._dependencies: dict[str, set[str]] = {}

    @contextmanager
    def transaction(self, *, conversation=False):
        with self.lock:
            if self.engine is not None:
                with DbSession(self.engine) as db:
                    db.execute(text("BEGIN IMMEDIATE"))
                    yield db
                    db.commit()
            else:
                before = deepcopy((self._entries, self._terms, self._dependencies,
                    self.sessions._sessions, self.sessions._checkpoints, self.sessions._retrieval_states))
                if conversation:
                    conversation_before = deepcopy((self.messages.__dict__, self.runs.__dict__,
                        self.run_events.__dict__, self.characters._characters,
                        self.sessions.web_cache.__dict__ if self.sessions.web_cache is not None else None))
                try:
                    yield None
                except BaseException:
                    (self._entries, self._terms, self._dependencies, self.sessions._sessions,
                        self.sessions._checkpoints, self.sessions._retrieval_states) = before
                    if conversation:
                        (self.messages.__dict__, self.runs.__dict__, self.run_events.__dict__,
                            self.characters._characters, web_cache) = conversation_before
                        if web_cache is not None:
                            self.sessions.web_cache.__dict__ = web_cache
                    raise

    def get(self, memory_id, *, transaction=None):
        if self.engine is None:
            with self.lock:
                entry = self._entries.get(memory_id)
                return entry.model_copy(deep=True) if entry else None
        with nullcontext(transaction) if transaction is not None else DbSession(self.engine) as db:
            row = db.get(Record, memory_id)
            return MemoryEntry.model_validate_json(row.record_json) if row else None

    def visible(self, entry: MemoryEntry, view: MemoryView) -> bool:
        if not view.enabled or entry.status != "active" or entry.persona_id != view.persona_id:
            return False
        if entry.pool == "general":
            return view.imports and view.general
        if entry.character_id != view.character_id:
            return False
        if entry.session_id == view.session_id:
            return True
        if not view.imports:
            return False
        if entry.session_id is None:
            return True
        try:
            origin = self.sessions.get_session(entry.session_id)
        except KeyError:
            return False
        return (origin.kind == "normal" and origin.character_id == view.character_id
            and origin.memory_isolation in {"shared", "block_incoming"})

    def _visibility(self, view):
        if not view.enabled:
            return false()
        local = and_(Record.pool == "character", Record.character_id == view.character_id)
        origins = [Record.session_id == view.session_id]
        if view.imports:
            exported = select(SessionRecord.session_id).where(SessionRecord.kind == "normal",
                SessionRecord.character_id == view.character_id,
                SessionRecord.memory_isolation.in_(("shared", "block_incoming")))
            origins += [Record.session_id.is_(None), Record.session_id.in_(exported)]
        scopes = [and_(local, or_(*origins))]
        if view.imports and view.general:
            scopes.append(Record.pool == "general")
        return and_(Record.status == "active", Record.persona_id == view.persona_id, or_(*scopes))

    def query(self, *, view=None, filters=None, query="", offset=0, limit=20, transaction=None):
        filters = filters or {}
        tokens = query_terms(query)
        if self.engine is None:
            with self.lock:
                rows = [value for value in self._entries.values() if value.status != "deleted"
                    and all((value.origin.session_id if key == "origin_session_id" else getattr(value, key)) == value_filter
                        for key, value_filter in filters.items())
                    and (view is None or self.visible(value, view))]
                scores = {entry.id: sum(self._terms.get(entry.id, {}).get(term, 0) for term in tokens) for entry in rows}
                if query:
                    rows = [entry for entry in rows if scores[entry.id] > 0]
                rows.sort(key=lambda entry: (entry.pinned, scores[entry.id], entry.observed_at, entry.id), reverse=True)
                return [entry.model_copy(deep=True) for entry in rows[offset:offset + limit]], len(rows)
        with nullcontext(transaction) if transaction is not None else DbSession(self.engine) as db:
            predicates = [Record.status != "deleted"]
            predicates.extend(getattr(Record, key) == value for key, value in filters.items())
            if view is not None:
                predicates.append(self._visibility(view))
            score = (select(func.coalesce(func.sum(Term.weight), 0)).where(Term.memory_id == Record.id,
                Term.term.in_(tokens)).correlate(Record).scalar_subquery()) if tokens else None
            if query:
                predicates.append(score > 0 if score is not None else false())
            total = db.exec(select(func.count()).select_from(Record).where(*predicates)).one()
            order = [Record.pinned.desc()]
            if score is not None:
                order.append(score.desc())
            order.extend([Record.observed_at.desc(), Record.id.desc()])
            rows = db.exec(select(Record.record_json).where(*predicates).order_by(*order).offset(offset).limit(limit)).all()
            return [MemoryEntry.model_validate_json(value) for value in rows], total

    def save(self, entry, expected_revision, *, transaction):
        current = self.get(entry.id, transaction=transaction)
        if (current is None) != (expected_revision is None) or (current and current.revision != expected_revision):
            raise conflict()
        if current and current.status == "deleted":
            raise conflict()
        if self.engine is None:
            self._entries[entry.id] = entry.model_copy(deep=True)
            self._terms[entry.id] = entry_terms(entry.summary, entry.body) if entry.status == "active" else {}
        else:
            db = transaction
            values = entry.model_dump(include={"id", "revision", "pool", "character_id", "persona_id", "session_id",
                "status", "managed_by", "pinned", "observed_at", "updated_at"})
            db.merge(Record(**values, origin_run_id=entry.origin.run_id, origin_session_id=entry.origin.session_id,
                record_json=entry.model_dump_json()))
            db.exec(delete(Term).where(Term.memory_id == entry.id))
            db.exec(delete(Evidence).where(Evidence.memory_id == entry.id))
            if entry.status == "active":
                for term, weight in entry_terms(entry.summary, entry.body).items():
                    db.add(Term(memory_id=entry.id, term=term, weight=weight))
            if entry.status != "deleted" and entry.managed_by == "model":
                for source in entry.origin.evidence:
                    db.add(Evidence(memory_id=entry.id, message_id=source.message_id))
            db.flush()
        if current is not None:
            self.invalidate_dependencies([entry.id], transaction=transaction)

    def track(self, session_id, memory_ids):
        if not memory_ids:
            return
        with self.transaction() as db:
            if self.engine is None:
                for memory_id in memory_ids:
                    self._dependencies.setdefault(memory_id, set()).add(session_id)
            else:
                for memory_id in memory_ids:
                    db.merge(Dependency(memory_id=memory_id, session_id=session_id))

    def invalidate_sessions(self, session_ids, *, transaction):
        ids = set(session_ids)
        if self.engine is None:
            for session_id in ids:
                session = self.sessions.get_session(session_id)
                if session.kind == "normal":
                    self.sessions.update_session(session_id, {"memory_version": session.memory_version + 1})
                    self.sessions.discard_context_checkpoint(session_id)
                    self.sessions.discard_retrieval_state(session_id)
        else:
            db = transaction
            db.exec(update(SessionRecord).where(SessionRecord.session_id.in_(ids), SessionRecord.kind == "normal")
                .values(memory_version=SessionRecord.memory_version + 1))
            for model in (ContextCheckpointRecord, ContextRetrievalRecord):
                db.exec(delete(model).where(model.session_id.in_(ids)))

    def invalidate_dependencies(self, memory_ids, *, transaction):
        if self.engine is None:
            affected = set().union(*(self._dependencies.get(memory_id, set()) for memory_id in memory_ids))
            affected.intersection_update(self.sessions._sessions)
        else:
            affected = transaction.exec(select(Dependency.session_id).where(Dependency.memory_id.in_(memory_ids))).all()
        self.invalidate_sessions(affected, transaction=transaction)

    def invalidate_history(self, message_ids, run_ids, *, transaction=None):
        if self.engine is None:
            affected = [entry.model_copy(deep=True) for entry in self._entries.values()
                if entry.managed_by == "model" and entry.status == "active" and
                (entry.origin.run_id in run_ids or any(source.message_id in message_ids for source in entry.origin.evidence))]
        else:
            sources = select(Evidence.memory_id).where(Evidence.message_id.in_(message_ids))
            rows = transaction.exec(select(Record.record_json).where(Record.managed_by == "model", Record.status == "active",
                or_(Record.origin_run_id.in_(run_ids), Record.id.in_(sources)))).all()
            affected = [MemoryEntry.model_validate_json(value) for value in rows]
        for entry in affected:
            revised = entry.model_copy(update={"revision": entry.revision + 1, "status": "needs_review", "updated_at": utc_now()})
            self.save(revised, entry.revision, transaction=transaction)

    def remove_session_dependencies(self, session_id, *, transaction):
        if self.engine is None:
            for ids in self._dependencies.values():
                ids.discard(session_id)
        else:
            transaction.exec(delete(Dependency).where(Dependency.session_id == session_id))
