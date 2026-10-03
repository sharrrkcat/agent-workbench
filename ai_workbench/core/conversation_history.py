"""Whole-reply history mutations with explicit persistence ownership."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.core.attachments import delete_attachment_if_unreferenced
from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.message_parts import make_text_part
from ai_workbench.core.schema.message import MessageSchema
from ai_workbench.core.time import utc_now


class HistoryPruned(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted_message_ids: list[str] = Field(default_factory=list)
    deleted_run_ids: list[str] = Field(default_factory=list)


class MemoryHistoryStore:
    def __init__(self, sessions, messages, runs, run_events) -> None:
        self.sessions = sessions
        self.messages = messages
        self.runs = runs
        self.run_events = run_events

    def prune(self, session_id: str, change: HistoryPruned, updated: MessageSchema | None = None) -> None:
        self.sessions.get_session(session_id)
        for message_id in change.deleted_message_ids:
            if self.messages.get_message(message_id).session_id != session_id:
                raise ValueError("Message belongs to another session")
        for run_id in change.deleted_run_ids:
            if self.runs.get_run(run_id).session_id != session_id:
                raise ValueError("Run belongs to another session")
        if updated is not None:
            updated = MessageSchema.model_validate(updated.model_dump())
            if self.messages.get_message(updated.message_id).session_id != session_id:
                raise ValueError("Message belongs to another session")
        for message_id in change.deleted_message_ids:
            self.messages.delete_message(message_id)
        for run_id in change.deleted_run_ids:
            self.runs.delete_run(run_id)
            self.run_events.delete_run(run_id)
        if updated is not None:
            self.messages.update_message(updated)
        session = self.sessions.get_session(session_id)
        self.sessions.update_session(session_id, {"history_version": session.history_version + 1})


class ConversationHistory:
    def __init__(self, *, store, sessions, messages, runs, events, chat_service, personas) -> None:
        self.store = store
        self.sessions = sessions
        self.messages = messages
        self.runs = runs
        self.events = events
        self.chat_service = chat_service
        self.personas = personas

    def delete_reply(self, run_id: str) -> HistoryPruned:
        run = self.runs.get_run(run_id)
        self.chat_service.assert_idle(run.session_id)
        return self._apply(run.session_id, {run_id})

    def delete_user(self, message_id: str) -> HistoryPruned:
        message = self._user(message_id)
        self.chat_service.assert_idle(message.session_id)
        run_ids = set(self.runs.run_ids_for_input(message.session_id, message_id))
        return self._apply(message.session_id, run_ids, {message_id})

    def retry(self, run_id: str):
        run = self.runs.get_run(run_id)
        self.chat_service.assert_idle(run.session_id)
        if run.kind != "chat":
            raise ChatError("CANNOT_RETRY_RUN", "Only chat replies can be retried.", 400)
        source = self._user(str(run.metadata.get("input_message_id") or ""))
        if source.session_id != run.session_id:
            raise ChatError("MESSAGE_SESSION_MISMATCH", "Reply input belongs to another session.", 400)
        session = self.sessions.get_session(run.session_id)
        self.chat_service.resolve(session, persona_id=run.persona_id)
        run_ids = set(self.runs.later_run_ids(run))
        message_ids = self.messages.message_ids_after_run(run, source.message_id)
        change = self._apply(run.session_id, run_ids, message_ids)
        return run, source, change

    def edit_user(self, message_id: str, content: str, attachment_ids: list[str]) -> tuple[MessageSchema, HistoryPruned]:
        message = self._user(message_id)
        self.chat_service.assert_idle(message.session_id)
        original = message.metadata.get("attachments", [])
        retained_ids = set(attachment_ids)
        if len(retained_ids) != len(attachment_ids) or not retained_ids.issubset({item["id"] for item in original}):
            raise ChatError("INVALID_ATTACHMENTS", "Keep only unique attachment ids from this message.", 400)
        attachments = [item for item in original if item["id"] in retained_ids]
        if not content.strip() and not attachments:
            raise ChatError("EMPTY_MESSAGE", "Message content or an attachment is required.", 400)
        updated = MessageSchema.model_validate({**message.model_dump(),
                                               "parts": [make_text_part(content, format="plain")] if content.strip() else [],
                                               "metadata": {**message.metadata, "attachments": attachments},
                                               "created_at": utc_now()})
        message_ids = self.messages.later_message_ids(message)
        run_ids = set(self.runs.run_ids_after_message(message))
        change = self._apply(message.session_id, run_ids, message_ids, updated)
        for attachment in original:
            if attachment["id"] not in retained_ids:
                delete_attachment_if_unreferenced(attachment, self.messages, persona_store=self.personas,
                                                 knowledge_store=self.chat_service.knowledge, run_store=self.runs)
        self.events.emit("message_updated", session_id=message.session_id, message_id=message_id,
                         payload={"message": updated.model_dump(mode="json")})
        return updated, change

    def _user(self, message_id: str) -> MessageSchema:
        message = self.messages.get_message(message_id)
        if message.role != "user":
            raise ChatError("CANNOT_EDIT_MESSAGE", "Use the reply's run for assistant history operations.", 400)
        return message

    def _apply(self, session_id: str, run_ids: set[str], message_ids: set[str] | None = None,
               updated: MessageSchema | None = None) -> HistoryPruned:
        message_ids = message_ids or set()
        deleted = self.messages.selected_message_ids(session_id, message_ids, run_ids)
        change = HistoryPruned(deleted_message_ids=deleted,
                               deleted_run_ids=self.runs.existing_run_ids(session_id, run_ids))
        attachments = set(self.messages.attachment_filenames(session_id=session_id, message_ids=set(deleted)))
        snapshot_attachments = self.runs.context_attachment_ids(run_ids)
        self.store.prune(session_id, change, updated)
        self.events.emit("history_pruned", session_id=session_id, payload=change.model_dump())
        for attachment_id in snapshot_attachments | attachments:
            delete_attachment_if_unreferenced({"uri": "local://attachments/" + attachment_id}, self.messages,
                persona_store=self.personas, knowledge_store=self.chat_service.knowledge, run_store=self.runs)
        return change
