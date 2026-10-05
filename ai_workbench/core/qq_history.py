"""Local QQ history deletion without changing delivery or ingestion outcomes."""
from pydantic import Field
from sqlmodel import Session, select
from sqlalchemy import update

from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.conversation_history import HistoryPruned
from ai_workbench.core.message_parts import make_text_part
from ai_workbench.core.qq_names import model_batch_text
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery


class QQHistoryPruned(HistoryPruned):
    deleted_qq_message_ids: list[int] = Field(default_factory=list)
    deleted_qq_delivery_ids: list[int] = Field(default_factory=list)
    history_version: int


class QQHistory:
    def __init__(self, state, store):
        self.state = state
        self.store = store

    def busy(self, session_id):
        return self.store.active_batch(session_id) is not None or self.state.runs.has_unfinished(session_id=session_id)

    def delete(self, session_id, *, message_id=None, delivery_id=None, run_id=None):
        if self.store.get(QQBinding, session_id) is None:
            raise ChatError("SESSION_NOT_FOUND", "QQ Session does not exist.", 404)
        self.state.chat_service.assert_idle(session_id)
        self.state.qq.assert_idle(session_id)
        change = QQHistoryPruned(history_version=self.state.sessions.get_session(session_id).history_version + 1)
        attachments = self.store.media_attachment_ids(message_id=message_id) if message_id is not None else set()
        if run_id is not None:
            attachments.update(self.state.runs.context_attachment_ids({run_id}))
        updated = None
        with Session(self.store.engine) as db:
            if message_id is not None:
                row = self._row(db, QQMessage, message_id, session_id)
                row.deleted = True
                db.add(row)
                change.deleted_qq_message_ids = [message_id]
                if row.batch_id is not None:
                    batch = db.get(QQBatch, row.batch_id)
                    remaining = db.exec(select(QQMessage).where(QQMessage.batch_id == batch.id,
                        QQMessage.deleted == False).order_by(QQMessage.id)).all()
                    batch.text = "\n".join(f"[{m.timestamp}][{m.sender_name}]:{m.text}" for m in remaining)
                    if not remaining and batch.status == "queued":
                        batch.status = "cancelled"
                    db.add(batch)
                    if batch.input_message_id is not None:
                        original = self.state.messages.get_message(batch.input_message_id)
                        updated = original.model_copy(update={"parts": [make_text_part(model_batch_text(remaining),
                            format="plain")] if remaining else []})
            elif delivery_id is not None:
                row = self._row(db, QQDelivery, delivery_id, session_id)
                row.deleted = True
                db.add(row)
                change.deleted_qq_delivery_ids = [delivery_id]
                change.deleted_message_ids = [message.message_id for message in self.state.messages.messages_for_run(row.run_id)
                    if message.metadata.get("qq_delivery_id") == delivery_id]
            else:
                run = self.state.runs.get_run(run_id)
                if run.session_id != session_id:
                    raise ChatError("RUN_NOT_FOUND", "QQ reply does not exist in this Session.", 404)
                change.deleted_run_ids = [run_id]
                change.deleted_message_ids = self.state.messages.selected_message_ids(session_id, set(), {run_id})
                change.deleted_qq_delivery_ids = list(db.exec(select(QQDelivery.id).where(
                    QQDelivery.run_id == run_id, QQDelivery.deleted == False)).all())
                db.exec(update(QQDelivery).where(QQDelivery.run_id == run_id).values(deleted=True))
                db.exec(update(QQBatch).where(QQBatch.session_id == session_id, QQBatch.run_id == run_id).values(run_id=None))
            history = self.state.history.store
            if getattr(history, "engine", None) is not None:
                history.prune(session_id, change, updated, transaction=db)
                db.commit()
            else:
                db.commit()
                history.prune(session_id, change, updated)
        self.state.events.emit("history_pruned", session_id=session_id, payload=change.model_dump())
        self.state.qq.media.cleanup(attachments)
        return change

    @staticmethod
    def _row(db, kind, key, session_id):
        row = db.get(kind, key)
        if row is None or row.session_id != session_id or row.deleted:
            raise ChatError("MESSAGE_NOT_FOUND", "QQ message does not exist in this Session.", 404)
        return row
