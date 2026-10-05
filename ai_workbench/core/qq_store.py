"""Bounded SQLite operations for QQ queues; batches reserve ingress atomically."""
import json
from sqlmodel import Session, select, delete
from sqlalchemy import update, func
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery, QQParticipant, QQMedia


class QQStore:
    def __init__(self, engine):
        self.engine = engine

    def save(self, row):
        with Session(self.engine) as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def get(self, kind, key):
        with Session(self.engine) as db:
            return db.get(kind, key)

    def binding(self, project_id, target_kind, target_id):
        with Session(self.engine) as db:
            return db.exec(select(QQBinding).where(QQBinding.project_id == project_id,
                QQBinding.target_kind == target_kind, QQBinding.target_id == target_id)).first()

    def bindings(self, project_id):
        with Session(self.engine) as db:
            return db.exec(select(QQBinding).where(QQBinding.project_id == project_id)).all()

    def ingest(self, binding, message, *, keyword, now, media=()):
        with Session(self.engine) as db:
            if db.exec(select(QQMessage.id).where(QQMessage.session_id == binding.session_id,
                    QQMessage.external_id == message.external_id)).first() is not None:
                return False
            db.add(message)
            db.flush()
            for item in media:
                db.add(QQMedia(message_id=message.id, **item))
            current = db.get(QQBinding, binding.session_id)
            if current.target_kind == "friend":
                current.window_kind = "private"
                current.deadline = now + 5
                db.add(current)
            else:
                participant = db.get(QQParticipant, (binding.session_id, message.sender_id))
                if keyword:
                    if participant is None:
                        participant = QQParticipant(session_id=binding.session_id, sender_id=message.sender_id,
                            keyword_message_id=message.id, expires_at=now + 60)
                    participant.keyword_message_id = message.id
                    participant.expires_at = now + 60
                if participant is not None and (keyword or participant.in_window or participant.expires_at > now):
                    if keyword or current.deadline is None:
                        current.window_kind = "keyword" if keyword else "followup"
                    participant.in_window = True
                    current.deadline = now + 5
                    db.add(participant)
                    db.add(current)
            db.commit()
            return True

    def freeze(self, session_id, limit, now):
        with Session(self.engine) as db:
            binding = db.get(QQBinding, session_id)
            if binding is None or binding.deadline is None or binding.deadline > now:
                return None
            rows = db.exec(select(QQMessage).where(QQMessage.session_id == session_id,
                QQMessage.disposition == "pending", QQMessage.deleted == False).order_by(QQMessage.id.desc()).limit(limit)).all()
            binding.deadline = None
            db.add(binding)
            participants = db.exec(select(QQParticipant).where(QQParticipant.session_id == session_id,
                QQParticipant.in_window == True, QQParticipant.sender_id.in_({row.sender_id for row in rows}))).all()
            db.exec(update(QQParticipant).where(QQParticipant.session_id == session_id,
                QQParticipant.in_window == True).values(in_window=False))
            if not rows:
                db.commit()
                return None
            rows.reverse()
            batch = QQBatch(session_id=session_id, project_id=binding.project_id, created_at=now,
                trigger_kind="private" if binding.target_kind == "friend" else binding.window_kind,
                participants_json=json.dumps({p.sender_id: p.keyword_message_id for p in participants}),
                text="\n".join(f"[{m.timestamp}][{m.sender_name}]:{m.text}" for m in rows))
            db.add(batch)
            db.flush()
            db.exec(update(QQMessage).where(QQMessage.session_id == session_id,
                QQMessage.disposition == "pending", QQMessage.deleted == False, QQMessage.id < rows[0].id).values(disposition="skipped"))
            for row in rows:
                row.disposition = "batched"
                row.batch_id = batch.id
                db.add(row)
            db.commit()
            db.refresh(batch)
            return batch

    def next_batch(self, project_id):
        with Session(self.engine) as db:
            return db.exec(select(QQBatch).join(QQBinding, QQBinding.session_id == QQBatch.session_id)
                .where(QQBatch.project_id == project_id, QQBatch.status == "queued", QQBinding.paused == False)
                .order_by(QQBatch.id).limit(1)).first()

    def pause(self, session_id, reason):
        binding = self.get(QQBinding, session_id)
        binding.paused = bool(reason)
        binding.pause_reason = reason
        self.save(binding)

    def page(self, kind, session_id, before=None, limit=50):
        with Session(self.engine) as db:
            query = select(kind).where(kind.session_id == session_id)
            if kind in (QQMessage, QQDelivery):
                query = query.where(kind.deleted == False)
            if before is not None:
                query = query.where(kind.id < before)
            rows = db.exec(query.order_by(kind.id.desc()).limit(limit + 1)).all()
            return {"items": [r.model_dump(exclude={"deleted"}) for r in rows[:limit]],
                "next_cursor": rows[limit - 1].id if len(rows) > limit else None}

    def delivery(self, run_id, call_id):
        with Session(self.engine) as db:
            return db.exec(select(QQDelivery).where(QQDelivery.run_id == run_id,
                QQDelivery.tool_call_id == call_id)).first()

    def has_sent(self, run_id):
        with Session(self.engine) as db:
            return db.exec(select(QQDelivery.id).where(QQDelivery.run_id == run_id,
                QQDelivery.status == "sent").limit(1)).first() is not None

    def batch_messages(self, batch_id):
        with Session(self.engine) as db:
            return db.exec(select(QQMessage).where(QQMessage.batch_id == batch_id, QQMessage.deleted == False)
                .order_by(QQMessage.id)).all()

    def message_media(self, message_ids):
        with Session(self.engine) as db:
            rows = db.exec(select(QQMedia).where(QQMedia.message_id.in_(message_ids))
                .order_by(QQMedia.message_id, QQMedia.segment_index)).all()
            result = {key: [] for key in message_ids}
            for row in rows:
                result[row.message_id].append(row)
            return result

    def pending_media(self, *, exclude=(), limit=4, batch_id=None):
        with Session(self.engine) as db:
            query = select(QQMedia, QQBinding.project_id).join(QQMessage, QQMedia.message_id == QQMessage.id)
            query = query.join(QQBinding, QQMessage.session_id == QQBinding.session_id).where(
                QQMedia.status == "pending", QQMessage.deleted == False, QQMedia.id.not_in(exclude))
            if batch_id is not None:
                query = query.where(QQMessage.batch_id == batch_id)
            return db.exec(query.order_by(QQMedia.id).limit(limit)).all()

    def finish_media(self, media):
        # A download never recreates a deleted message or Session.
        with Session(self.engine) as db:
            visible = select(QQMessage.id).where(QQMessage.deleted == False)
            result = db.exec(update(QQMedia).where(QQMedia.id == media.id, QQMedia.message_id.in_(visible))
                .values(**media.model_dump(include={"status", "attachment_json", "model_attachment_json", "error_code"})))
            db.commit()
            return result.rowcount == 1

    def media_attachment_ids(self, *, session_id=None, message_id=None):
        with Session(self.engine) as db:
            query = select(QQMedia.attachment_json, QQMedia.model_attachment_json).join(QQMessage,
                QQMedia.message_id == QQMessage.id)
            if session_id is not None:
                query = query.where(QQMessage.session_id == session_id)
            if message_id is not None:
                query = query.where(QQMessage.id == message_id)
            return {json.loads(value)["id"] for row in db.exec(query) for value in row if value}

    def referenced_attachments(self, names):
        with Session(self.engine) as db:
            original = func.json_extract(QQMedia.attachment_json, "$.id")
            model = func.json_extract(QQMedia.model_attachment_json, "$.id")
            rows = db.exec(select(original, model).join(QQMessage, QQMedia.message_id == QQMessage.id).where(
                QQMessage.deleted == False, original.in_(names) | model.in_(names))).all()
            return {value for row in rows for value in row if value in names}

    def save_references(self, rows):
        with Session(self.engine) as db:
            for row in rows:
                db.exec(update(QQMessage).where(QQMessage.id == row["id"]).values(references_json=row["references_json"]))
            db.commit()

    @staticmethod
    def _history_filter(session_id, current_message_id):
        conditions = [QQBatch.session_id == session_id, QQBatch.input_message_id.is_not(None)]
        if current_message_id is not None:
            conditions.append(QQBatch.input_message_id != current_message_id)
        return conditions

    def history_message_count(self, session_id, current_message_id):
        conditions = self._history_filter(session_id, current_message_id)
        with Session(self.engine) as db:
            visible_input = select(QQMessage.id).where(QQMessage.batch_id == QQBatch.id, QQMessage.deleted == False).exists()
            batches = db.exec(select(func.count()).select_from(QQBatch).where(*conditions, visible_input)).one()
            deliveries = db.exec(select(func.count()).select_from(QQDelivery).join(QQBatch, QQBatch.run_id == QQDelivery.run_id)
                .where(*conditions, QQDelivery.status == "sent", QQDelivery.deleted == False)).one()
            return batches + deliveries

    def iter_history(self, session_id, current_message_id):
        conditions = self._history_filter(session_id, current_message_id)
        before = None
        while True:
            with Session(self.engine) as db:
                query = select(QQBatch.id, QQBatch.input_message_id, QQBatch.run_id).where(*conditions)
                if before is not None:
                    query = query.where(QQBatch.id < before)
                batches = db.exec(query.order_by(QQBatch.id.desc()).limit(64)).all()
            if not batches:
                return
            for batch in batches:
                with Session(self.engine) as db:
                    deliveries = db.exec(select(QQDelivery).where(QQDelivery.run_id == batch.run_id,
                        QQDelivery.session_id == session_id, QQDelivery.status == "sent", QQDelivery.deleted == False)
                        .order_by(QQDelivery.id)).all()
                yield batch, deliveries
            before = batches[-1].id

    def reconcile_echo(self, session_id, external_id):
        with Session(self.engine) as db:
            db.exec(update(QQDelivery).where(QQDelivery.session_id == session_id,
                QQDelivery.external_id == external_id, QQDelivery.status == "sent").values(echoed=True))
            db.commit()

    def active_batch(self, session_id):
        with Session(self.engine) as db:
            return db.exec(select(QQBatch).where(QQBatch.session_id == session_id,
                QQBatch.status == "running").limit(1)).first()

    @staticmethod
    def renew_participants(db, batch, now):
        if batch.trigger_kind == "followup":
            db.exec(update(QQParticipant).where(QQParticipant.session_id == batch.session_id,
                QQParticipant.sender_id.in_(batch.participants)).values(expires_at=func.max(QQParticipant.expires_at, now + 45)))

    def skip_participants(self, batch, now):
        with Session(self.engine) as db:
            for sender_id, keyword_id in batch.participants.items():
                db.exec(update(QQParticipant).where(QQParticipant.session_id == batch.session_id,
                    QQParticipant.sender_id == sender_id, QQParticipant.keyword_message_id == keyword_id).values(expires_at=now))
            db.commit()

    def recover(self):
        with Session(self.engine) as db:
            for kind, statuses in ((QQBatch, ["running"]), (QQDelivery, ["pending", "sending"])):
                # Process recovery in bounded pages, including interrupted send intents.
                while True:
                    query = select(kind).where(kind.status.in_(statuses))
                    if kind is QQDelivery:
                        query = query.where(kind.deleted == False)
                    rows = db.exec(query.limit(100)).all()
                    if not rows:
                        break
                    for row in rows:
                        row.status = "interrupted" if kind is QQBatch else "unknown"
                        row.error_code = "QQ_INTERRUPTED"
                        db.add(row)
                        binding = db.get(QQBinding, row.session_id)
                        if binding:
                            binding.paused, binding.pause_reason = True, "QQ_INTERRUPTED"
                            db.add(binding)
                    db.commit()

    def delete_session(self, session_id):
        with Session(self.engine) as db:
            db.exec(delete(QQMedia).where(QQMedia.message_id.in_(select(QQMessage.id).where(QQMessage.session_id == session_id))))
            for kind in (QQDelivery, QQBatch, QQMessage, QQParticipant, QQBinding):
                db.exec(delete(kind).where(kind.session_id == session_id))
            db.commit()
