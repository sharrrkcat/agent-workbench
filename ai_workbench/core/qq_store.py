"""Bounded SQLite operations for QQ queues; batches reserve ingress atomically."""
from sqlmodel import Session, select, delete
from sqlalchemy import update
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery


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

    def ingest(self, binding, message, *, trigger, now):
        with Session(self.engine) as db:
            if db.exec(select(QQMessage.id).where(QQMessage.session_id == binding.session_id,
                    QQMessage.external_id == message.external_id)).first() is not None:
                return False
            db.add(message)
            if trigger:
                current = db.get(QQBinding, binding.session_id)
                current.deadline = now + 5
                db.add(current)
            db.commit()
            return True

    def freeze(self, session_id, limit, now):
        with Session(self.engine) as db:
            binding = db.get(QQBinding, session_id)
            if binding is None or binding.deadline is None or binding.deadline > now:
                return None
            rows = db.exec(select(QQMessage).where(QQMessage.session_id == session_id,
                QQMessage.disposition == "pending").order_by(QQMessage.id.desc()).limit(limit)).all()
            binding.deadline = None
            db.add(binding)
            if not rows:
                db.commit()
                return None
            rows.reverse()
            batch = QQBatch(session_id=session_id, project_id=binding.project_id, created_at=now,
                text="\n".join(f"[{m.timestamp}][{m.sender_name}]:{m.text}" for m in rows))
            db.add(batch)
            db.flush()
            db.exec(update(QQMessage).where(QQMessage.session_id == session_id,
                QQMessage.disposition == "pending", QQMessage.id < rows[0].id).values(disposition="skipped"))
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
            if before is not None:
                query = query.where(kind.id < before)
            rows = db.exec(query.order_by(kind.id.desc()).limit(limit + 1)).all()
            return {"items": [r.model_dump() for r in rows[:limit]],
                "next_cursor": rows[limit - 1].id if len(rows) > limit else None}

    def delivery(self, run_id, call_id):
        with Session(self.engine) as db:
            return db.exec(select(QQDelivery).where(QQDelivery.run_id == run_id,
                QQDelivery.tool_call_id == call_id)).first()

    def reconcile_echo(self, session_id, external_id):
        with Session(self.engine) as db:
            db.exec(update(QQDelivery).where(QQDelivery.session_id == session_id,
                QQDelivery.external_id == external_id, QQDelivery.status == "sent").values(echoed=True))
            db.commit()

    def active_batch(self, session_id):
        with Session(self.engine) as db:
            return db.exec(select(QQBatch).where(QQBatch.session_id == session_id,
                QQBatch.status == "running").limit(1)).first()

    def recover(self):
        with Session(self.engine) as db:
            for kind, statuses in ((QQBatch, ["running"]), (QQDelivery, ["pending", "sending"])):
                # Process recovery in bounded pages, including interrupted send intents.
                while True:
                    rows = db.exec(select(kind).where(kind.status.in_(statuses)).limit(100)).all()
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
            for kind in (QQDelivery, QQBatch, QQMessage, QQBinding):
                db.exec(delete(kind).where(kind.session_id == session_id))
            db.commit()
