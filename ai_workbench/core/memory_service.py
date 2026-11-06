"""User-managed publication and Session-scoped durable fact operations."""

import hashlib
import json

from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.memory_store import conflict
from ai_workbench.core.schema.memory import (
    MemoryCreate, MemoryEdit, MemoryEntry, MemoryOrigin, MemoryPublication, MemoryEvidence,
    MemoryView, MemoryPage, MemoryPreview, MemoryDeletionPreview, MemoryDeletionChoice,
)
from ai_workbench.core.time import utc_now


def message_digest(message):
    value = {"parts": message.parts, "speaker_id": message.speaker_id,
        "attachments": message.metadata.get("attachments", [])}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def forget(entry):
    # No old text is kept in revisions, lexical terms or nominal audit fields.
    return entry.model_copy(deep=True, update={"revision": entry.revision + 1, "summary": "", "body": "",
        "status": "deleted", "pinned": False, "origin": entry.origin.model_copy(update={"evidence": []}),
        "updated_at": utc_now()})


class MemoryService:
    def __init__(self, store, chat_service, messages):
        self.store = store
        self.chat = chat_service
        self.messages = messages

    def view(self, session_id):
        session = self.chat.sessions.get_session(session_id)
        if session.kind != "normal":
            raise ChatError("MEMORY_UNAVAILABLE", "Memory is available only in normal conversations.", 409)
        owner = self.chat.normal_character(session.character_id)
        settings = self.chat.settings(session)
        return MemoryView(session_id=session_id, character_id=owner.id,
            persona_id=session.bound_persona_id or settings.persona_id,
            imports=session.memory_isolation in {"shared", "block_outgoing"},
            general=not owner.memory_external_isolation, enabled=settings.memory_enabled,
            version=session.memory_version)

    def get(self, memory_id, *, session_id=None, transaction=None):
        entry = self.store.get(memory_id, transaction=transaction)
        if (entry is None or entry.status == "deleted"
            or (session_id is not None and not self.store.visible(entry, self.view(session_id)))):
            raise ChatError("MEMORY_UNAVAILABLE", "Memory is unavailable.", 404)
        return entry

    def list(self, *, session_id=None, filters=None, query="", offset=0, limit=20):
        view = self.view(session_id) if session_id is not None else None
        rows, total = self.store.query(view=view, filters=filters, query=query, offset=offset, limit=limit)
        return MemoryPage(items=[MemoryPreview.from_entry(entry) for entry in rows], total=total,
            next_offset=offset + len(rows) if offset + len(rows) < total else None)

    def create(self, values: MemoryCreate):
        with self.store.transaction() as db:
            self.chat.normal_character(values.character_id)
            self.chat.persona(values.persona_id)
            origin = MemoryOrigin(character_id=values.character_id, persona_id=values.persona_id,
                session_id=values.session_id)
            if values.session_id is not None:
                session = self.chat.sessions.get_session(values.session_id)
                if (session.kind != "normal" or session.character_id != values.character_id
                    or session.bound_persona_id != values.persona_id):
                    raise ChatError("MEMORY_OWNER_MISMATCH", "Choose the Session's bound Character and Persona.", 409)
            if values.source_message_id:
                source = self.messages.get_message(values.source_message_id)
                source_session = self.chat.sessions.get_session(source.session_id)
                if (source_session.kind != "normal" or source_session.character_id != values.character_id
                    or source_session.bound_persona_id != values.persona_id
                    or (values.session_id and source.session_id != values.session_id)):
                    raise ChatError("MEMORY_SOURCE_MISMATCH", "The source belongs to another conversation identity.", 409)
                origin.session_id = source.session_id
                origin.run_id = source.run_id
                origin.evidence = [MemoryEvidence(message_id=source.message_id, digest=message_digest(source))]
            entry = MemoryEntry(**values.model_dump(exclude={"source_message_id"}), origin=origin)
            self.store.save(entry, None, transaction=db)
            return entry

    def edit(self, memory_id, values: MemoryEdit):
        with self.store.transaction() as db:
            current = self.get(memory_id, transaction=db)
            if current.revision != values.expected_revision:
                raise conflict()
            revised = current.model_copy(update={**values.model_dump(exclude={"expected_revision"}),
                "managed_by": "user", "revision": current.revision + 1, "updated_at": utc_now()})
            self.store.save(revised, current.revision, transaction=db)
            return revised

    def delete(self, memory_id, revision):
        with self.store.transaction() as db:
            current = self.get(memory_id, transaction=db)
            if current.revision != revision:
                raise conflict()
            self.store.save(forget(current), revision, transaction=db)

    def _all(self, filters, *, transaction=None):
        offset = 0
        while True:
            batch, total = self.store.query(filters=filters, offset=offset, limit=128, transaction=transaction)
            yield from batch
            offset += len(batch)
            if offset >= total:
                return

    def _publish(self, current, db):
        if current.pool != "character":
            raise ChatError("MEMORY_ALREADY_GENERAL", "This memory is already in the General pool.", 409)
        publication = MemoryPublication(memory_id=current.id, revision=current.revision)
        for entry in self._all({"pool": "general", "persona_id": current.persona_id,
            "character_id": current.character_id}, transaction=db):
            if entry.publication == publication:
                return entry
        entry = MemoryEntry(pool="general", character_id=current.character_id, persona_id=current.persona_id,
            summary=current.summary, body=current.body, status=current.status, pinned=current.pinned,
            origin=current.origin.model_copy(deep=True), publication=publication, observed_at=current.observed_at)
        self.store.save(entry, None, transaction=db)
        return entry

    def publish(self, memory_id, revision):
        with self.store.transaction() as db:
            current = self.get(memory_id, transaction=db)
            if current.revision != revision:
                raise conflict()
            return self._publish(current, db)

    def assert_character_idle(self, character_id):
        for session in self.chat.sessions.list_sessions():
            if session.character_id == character_id:
                self.chat.assert_idle(session.session_id)

    def policy_changed(self, character_id):
        ids = [session.session_id for session in self.chat.sessions.list_sessions()
            if session.kind == "normal" and session.character_id == character_id]
        with self.store.transaction() as db:
            self.store.invalidate_sessions(ids, transaction=db)

    def has_persona(self, persona_id):
        return bool(self.store.query(filters={"persona_id": persona_id}, limit=1)[1])

    def deletion_preview(self, *, session_id=None, character_id=None, transaction=None):
        if session_id is not None:
            self.view(session_id)
            local = list(self._all({"pool": "character", "session_id": session_id}, transaction=transaction))
            general = list(self._all({"pool": "general", "origin_session_id": session_id}, transaction=transaction))
        else:
            self.chat.normal_character(character_id)
            local = list(self._all({"pool": "character", "character_id": character_id}, transaction=transaction))
            general = list(self._all({"pool": "general", "character_id": character_id}, transaction=transaction))
        version = hashlib.sha256(json.dumps(sorted((entry.id, entry.revision) for entry in local + general)).encode()).hexdigest()
        return MemoryDeletionPreview(revision=version,
            local=[MemoryPreview.from_entry(entry) for entry in local],
            general=[MemoryPreview.from_entry(entry) for entry in general])

    def apply_deletion(self, choice: MemoryDeletionChoice, *, session_id=None, character_id=None, transaction):
        preview = self.deletion_preview(session_id=session_id, character_id=character_id, transaction=transaction)
        if not preview.local and not preview.general:
            return
        if choice.expected_revision != preview.revision:
            raise ChatError("MEMORY_DELETION_CHANGED", "Review the current memories before deleting this owner.", 409)
        allowed = {"delete", "keep"} if session_id is not None else {"delete", "transfer", "publish"}
        if (preview.local and choice.local not in allowed) or (preview.general and choice.general is None):
            raise ChatError("MEMORY_DISPOSITION_REQUIRED", "Choose what to do with local and General memories.", 409)
        if choice.local == "transfer":
            target = self.chat.normal_character(choice.target_character_id or "")
            if target.id == character_id:
                raise ChatError("MEMORY_TRANSFER_TARGET", "Choose another Character.", 409)
            self.assert_character_idle(target.id)
        # Existing copies are a separate choice. Remove them before publishing
        # the selected local versions so an idempotent publication cannot reuse
        # a copy the user explicitly chose to delete.
        if choice.general == "delete":
            for item in preview.general:
                current = self.get(item.id, transaction=transaction)
                self.store.save(forget(current), current.revision, transaction=transaction)
        for item in preview.local:
            current = self.get(item.id, transaction=transaction)
            if choice.local in {"delete", "publish"}:
                if choice.local == "publish":
                    self._publish(current, transaction)
                self.store.save(forget(current), current.revision, transaction=transaction)
            else:
                changes = {"session_id": None, "managed_by": "user", "revision": current.revision + 1, "updated_at": utc_now()}
                if choice.local == "transfer":
                    changes["character_id"] = choice.target_character_id
                self.store.save(current.model_copy(update=changes), current.revision, transaction=transaction)
