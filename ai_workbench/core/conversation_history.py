"""Whole-reply history mutations with explicit persistence ownership."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.core.attachments import delete_attachment_if_unreferenced
from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.message_parts import make_text_part
from ai_workbench.core.schema.message import MessageSchema


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
        self.sessions.touch_session(session_id)


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
        run_ids = {run.run_id for run in self.runs.list_runs(message.session_id)
                   if run.metadata.get("input_message_id") == message_id}
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
        ordered_runs = self.runs.list_runs(run.session_id)
        index = next(i for i, item in enumerate(ordered_runs) if item.run_id == run_id)
        run_ids = {item.run_id for item in ordered_runs[index:]}
        message_ids = {item.message_id for item in self.messages.list_messages(run.session_id)
                       if item.created_at >= run.created_at and item.message_id != source.message_id}
        change = self._apply(run.session_id, run_ids, message_ids)
        return run, source, change

    def edit_user(self, message_id: str, content: str) -> tuple[MessageSchema, HistoryPruned]:
        message = self._user(message_id)
        self.chat_service.assert_idle(message.session_id)
        updated = MessageSchema.model_validate({**message.model_dump(), "parts": [make_text_part(content, format="plain")]})
        ordered = self.messages.list_messages(message.session_id)
        index = next(i for i, item in enumerate(ordered) if item.message_id == message_id)
        message_ids = {item.message_id for item in ordered[index + 1:]}
        run_ids = {run.run_id for run in self.runs.list_runs(message.session_id)
                   if run.created_at >= message.created_at or run.metadata.get("input_message_id") == message_id}
        change = self._apply(message.session_id, run_ids, message_ids, updated)
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
        deleted = [item for item in self.messages.list_messages(session_id)
                   if item.message_id in message_ids or item.run_id in run_ids]
        change = HistoryPruned(deleted_message_ids=[item.message_id for item in deleted],
                               deleted_run_ids=[run.run_id for run in self.runs.list_runs(session_id) if run.run_id in run_ids])
        self.store.prune(session_id, change, updated)
        self.events.prune_history(session_id, change.model_dump())
        for message in deleted:
            attachments = message.metadata.get("attachments")
            for attachment in attachments if isinstance(attachments, list) else []:
                delete_attachment_if_unreferenced(attachment, self.messages, persona_store=self.personas, run_store=self.runs)
            avatar_id = message.metadata.get("speaker_avatar_attachment_id")
            if avatar_id:
                delete_attachment_if_unreferenced({"id": avatar_id, "uri": "local://attachments/" + avatar_id},
                                                 self.messages, persona_store=self.personas, run_store=self.runs)
        return change
