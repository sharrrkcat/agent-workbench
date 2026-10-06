"""Bounded SQLite operations for QQ queues; batches reserve ingress atomically."""
import json
from sqlmodel import Session, select, delete
from sqlalchemy import update, func
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery, QQParticipant, QQMedia, QQMediaAsset
from ai_workbench.core.time import utc_now


class QQStore:
    def __init__(self, engine, sessions=None):
        self.engine = engine
        self.sessions = sessions

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

    def record_ingress(self, binding, message, *, media=()):
        with Session(self.engine) as db:
            if db.exec(select(QQMessage.id).where(QQMessage.session_id == binding.session_id,
                    QQMessage.external_id == message.external_id)).first() is not None:
                return False
            db.add(message)
            db.flush()
            message_id = message.id
            for item in media:
                db.add(QQMedia(message_id=message.id, **item))
            db.commit()
            db.refresh(message)
            return message_id

    def activate_ingress(self, message_id, *, keyword, now, eligibility_before=None):
        with Session(self.engine) as db:
            message = db.get(QQMessage, message_id)
            if message is None or message.deleted:
                return False
            current = db.get(QQBinding, message.session_id)
            if current is None:
                return False
            if current.target_kind == "friend":
                current.window_kind = "private"
                current.deadline = now + 5
                db.add(current)
            else:
                participant = db.get(QQParticipant, (message.session_id, message.sender_id))
                if keyword:
                    if participant is None:
                        participant = QQParticipant(session_id=message.session_id, sender_id=message.sender_id,
                            grant_message_id=message.id, expires_at=now + 60)
                    participant.grant_message_id = max(participant.grant_message_id, message.id)
                    participant.expires_at = max(participant.expires_at, now + 60)
                expires_at = participant.expires_at if participant is not None else float("-inf")
                if eligibility_before is not None and participant is not None and participant.grant_message_id == eligibility_before[0]:
                    expires_at = min(expires_at, eligibility_before[1])
                if participant is not None and (keyword or participant.in_window or expires_at > now):
                    if keyword or current.deadline is None:
                        current.window_kind = "keyword" if keyword else "followup"
                    participant.in_window = True
                    current.deadline = now + 5
                    db.add(participant)
                    db.add(current)
            db.commit()
            return True

    def freeze(self, session_id, limit, now, *, icebreaker_first_id=None, before_message_id=None):
        with Session(self.engine) as db:
            binding = db.get(QQBinding, session_id)
            icebreaker = icebreaker_first_id is not None
            if binding is None:
                return None
            if icebreaker:
                if binding.paused or binding.deadline is not None:
                    return None
            elif binding.deadline is None or binding.deadline > now:
                return None
            query = select(QQMessage).where(QQMessage.session_id == session_id,
                QQMessage.disposition == "pending", QQMessage.deleted == False)
            if before_message_id is not None:
                query = query.where(QQMessage.id < before_message_id)
            if icebreaker:
                query = query.where(QQMessage.id >= icebreaker_first_id, func.length(func.trim(QQMessage.text)) > 0)
            rows = db.exec(query.order_by(QQMessage.id.desc()).limit(limit)).all()
            participants = []
            if not icebreaker:
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
            grants = ({rows[-1].sender_id: rows[-1].id} if icebreaker else
                {p.sender_id: p.grant_message_id for p in participants})
            batch = QQBatch(session_id=session_id, project_id=binding.project_id, created_at=now,
                trigger_kind="icebreaker" if icebreaker else "private" if binding.target_kind == "friend" else binding.window_kind,
                participants_json=json.dumps(grants),
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

    def has_reply_work(self, session_id):
        with Session(self.engine) as db:
            return db.exec(select(QQBatch.id).where(QQBatch.session_id == session_id,
                QQBatch.status.in_(("queued", "running")), QQBatch.trigger_kind != "icebreaker").limit(1)).first() is not None

    def start_icebreaker_cooldown(self, session_id, until):
        with Session(self.engine) as db:
            db.exec(update(QQBinding).where(QQBinding.session_id == session_id).values(icebreaker_cooldown_until=until))
            db.commit()

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
            rows = db.exec(select(QQMedia, QQMediaAsset).outerjoin(QQMediaAsset, QQMedia.asset_id == QQMediaAsset.id)
                .where(QQMedia.message_id.in_(message_ids))
                .order_by(QQMedia.message_id, QQMedia.segment_index)).all()
            result = {key: [] for key in message_ids}
            for row, asset in rows:
                row._asset = asset
                result[row.message_id].append(row)
            return result

    def pending_media(self, *, exclude=(), limit=4, batch_id=None):
        with Session(self.engine) as db:
            query = select(QQMedia, QQBinding.project_id).join(QQMessage, QQMedia.message_id == QQMessage.id)
            query = query.join(QQBinding, QQMessage.session_id == QQBinding.session_id).where(
                QQMedia.status == "pending", QQMessage.deleted == False, QQMedia.id.not_in(exclude))
            if batch_id is not None:
                query = query.where(QQMessage.batch_id == batch_id, QQMedia.kind != "face")
            return db.exec(query.order_by(QQMedia.id).limit(limit)).all()

    def finish_media(self, media):
        # A download never recreates a deleted message or Session.
        with Session(self.engine) as db:
            visible = select(QQMessage.id).where(QQMessage.deleted == False)
            result = db.exec(update(QQMedia).where(QQMedia.id == media.id, QQMedia.message_id.in_(visible))
                .values(**media.model_dump(include={"status", "error_code"})))
            db.commit()
            return result.rowcount == 1

    def acquire_media(self, media, sha256, create_asset=None):
        # Serialize lookup, file creation and reference assignment, including competing downloads.
        with Session(self.engine) as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            row = db.exec(select(QQMedia).join(QQMessage, QQMedia.message_id == QQMessage.id).where(
                QQMedia.id == media.id, QQMedia.status == "pending", QQMessage.deleted == False)).first()
            if row is None:
                return False
            asset = db.exec(select(QQMediaAsset).where(QQMediaAsset.sha256 == sha256)).first()
            if asset is None:
                if create_asset is None:
                    return False
                asset = create_asset()
                db.add(asset)
                db.flush()
            row.asset_id, row.status = asset.id, "ready"
            row.error_code = None if asset.model_attachment_json is not None or row.kind == "face" else "QQ_IMAGE_TOO_LARGE"
            db.add(row)
            db.commit()
            return True

    def media_assets(self, media_ids):
        with Session(self.engine) as db:
            return db.exec(select(QQMediaAsset).join(QQMedia, QQMedia.asset_id == QQMediaAsset.id)
                .join(QQMessage, QQMedia.message_id == QQMessage.id)
                .where(QQMedia.id.in_(media_ids), QQMessage.deleted == False).distinct()).all()

    def update_description(self, asset_id, description, *, only_if_empty=False):
        with Session(self.engine) as db:
            query = update(QQMediaAsset).where(QQMediaAsset.id == asset_id)
            if only_if_empty:
                query = query.where(QQMediaAsset.description_manual == False,
                    QQMediaAsset.description.is_(None) | (QQMediaAsset.description == ""))
            changed = db.exec(query.values(description=description, updated_at=utc_now())).rowcount
            sessions = self.asset_sessions(db, asset_id) if changed else set()
            self.advance_history(db, sessions)
            db.commit()
            return sessions

    @staticmethod
    def asset_sessions(db, asset_id):
        incoming = select(QQMessage.session_id).join(QQMedia, QQMedia.message_id == QQMessage.id).where(
            QQMedia.asset_id == asset_id, QQMessage.deleted == False)
        outgoing = select(QQDelivery.session_id).where(QQDelivery.asset_id == asset_id, QQDelivery.deleted == False)
        return set(db.exec(incoming).all()) | set(db.exec(outgoing).all())

    def advance_history(self, db, sessions):
        if hasattr(self.sessions, "engine"):
            from ai_workbench.db.models import SessionRecord
            db.exec(update(SessionRecord).where(SessionRecord.session_id.in_(sessions))
                .values(history_version=SessionRecord.history_version + 1))
        else:
            for session_id in sessions:
                current = self.sessions.get_session(session_id)
                self.sessions.update_session(session_id, {"history_version": current.history_version + 1})

    def confirm_generated_asset(self, db, candidate, prompt, session_id):
        asset = db.exec(select(QQMediaAsset).where(QQMediaAsset.sha256 == candidate.sha256)).first()
        if asset is None:
            asset = QQMediaAsset(**candidate.model_dump())
        if not asset.description_manual:
            asset.description, asset.updated_at = prompt, utc_now()
        db.add(asset)
        db.flush()
        self.advance_history(db, self.asset_sessions(db, asset.id) | {session_id})
        return asset.id

    def delivery_assets(self, asset_ids):
        with Session(self.engine) as db:
            return {row.id: row for row in db.exec(select(QQMediaAsset).where(QQMediaAsset.id.in_(asset_ids))).all()}

    def delivery_attachment_ids(self, *, session_id=None, delivery_id=None, run_id=None):
        with Session(self.engine) as db:
            query = select(QQMediaAsset.attachment_json, QQMediaAsset.model_attachment_json).join(QQDelivery,
                QQDelivery.asset_id == QQMediaAsset.id)
            for field, value in ((QQDelivery.session_id, session_id), (QQDelivery.id, delivery_id), (QQDelivery.run_id, run_id)):
                if value is not None:
                    query = query.where(field == value)
            return {json.loads(value)["id"] for row in db.exec(query) for value in row if value}

    def release_unused_assets(self, attachment_ids):
        if not attachment_ids:
            return set()
        with Session(self.engine) as db:
            candidates = select(QQMediaAsset.id).where(
                func.json_extract(QQMediaAsset.attachment_json, "$.id").in_(attachment_ids)
                | func.json_extract(QQMediaAsset.model_attachment_json, "$.id").in_(attachment_ids))
            db.exec(delete(QQMedia).where(QQMedia.asset_id.in_(candidates),
                QQMedia.message_id.in_(select(QQMessage.id).where(QQMessage.deleted == True))))
            db.exec(update(QQDelivery).where(QQDelivery.asset_id.in_(candidates), QQDelivery.deleted == True).values(asset_id=None))
            assets = db.exec(select(QQMediaAsset).where(QQMediaAsset.id.in_(candidates), QQMediaAsset.is_favorite == False,
                ~QQMediaAsset.id.in_(select(QQMedia.asset_id)
                .where(QQMedia.asset_id.is_not(None))), ~QQMediaAsset.id.in_(select(QQDelivery.asset_id)
                .where(QQDelivery.asset_id.is_not(None))))).all()
            attachments = {json.loads(value)["id"] for asset in assets
                for value in (asset.attachment_json, asset.model_attachment_json) if value}
            for asset in assets:
                db.delete(asset)
            db.commit()
            return attachments

    def media_attachment_ids(self, *, session_id=None, message_id=None):
        with Session(self.engine) as db:
            query = select(QQMediaAsset.attachment_json, QQMediaAsset.model_attachment_json).join(QQMedia,
                QQMedia.asset_id == QQMediaAsset.id).join(QQMessage, QQMedia.message_id == QQMessage.id)
            if session_id is not None:
                query = query.where(QQMessage.session_id == session_id)
            if message_id is not None:
                query = query.where(QQMessage.id == message_id)
            result = {json.loads(value)["id"] for row in db.exec(query) for value in row if value}
        if message_id is None:
            result.update(self.delivery_attachment_ids(session_id=session_id))
        return result

    def referenced_attachments(self, names):
        with Session(self.engine) as db:
            original = func.json_extract(QQMediaAsset.attachment_json, "$.id")
            model = func.json_extract(QQMediaAsset.model_attachment_json, "$.id")
            rows = db.exec(select(original, model).join(QQMedia, QQMedia.asset_id == QQMediaAsset.id)
                .join(QQMessage, QQMedia.message_id == QQMessage.id).where(
                QQMessage.deleted == False, original.in_(names) | model.in_(names))).all()
            rows += db.exec(select(original, model).join(QQDelivery, QQDelivery.asset_id == QQMediaAsset.id).where(
                QQDelivery.deleted == False, original.in_(names) | model.in_(names))).all()
            rows += db.exec(select(original, model).where(QQMediaAsset.is_favorite == True,
                original.in_(names) | model.in_(names))).all()
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
        before = {}
        if batch.trigger_kind == "followup":
            participants = db.exec(select(QQParticipant).where(QQParticipant.session_id == batch.session_id,
                QQParticipant.sender_id.in_(batch.participants))).all()
            before = {p.sender_id: (p.grant_message_id, p.expires_at) for p in participants}
            db.exec(update(QQParticipant).where(QQParticipant.session_id == batch.session_id,
                QQParticipant.sender_id.in_(batch.participants)).values(expires_at=func.max(QQParticipant.expires_at, now + 45)))
        elif batch.trigger_kind == "icebreaker":
            for sender_id, grant_id in batch.participants.items():
                participant = db.get(QQParticipant, (batch.session_id, sender_id))
                expires_at = participant.expires_at if participant is not None else float("-inf")
                if participant is None:
                    participant = QQParticipant(session_id=batch.session_id, sender_id=sender_id,
                        grant_message_id=grant_id, expires_at=now + 60)
                else:
                    participant.grant_message_id = max(participant.grant_message_id, grant_id)
                    participant.expires_at = max(participant.expires_at, now + 60)
                before[sender_id] = (participant.grant_message_id, expires_at)
                db.add(participant)
        return before

    def skip_participants(self, batch, now):
        with Session(self.engine) as db:
            for sender_id, grant_id in batch.participants.items():
                db.exec(update(QQParticipant).where(QQParticipant.session_id == batch.session_id,
                    QQParticipant.sender_id == sender_id, QQParticipant.grant_message_id == grant_id).values(expires_at=now))
            db.commit()

    def recover(self):
        with Session(self.engine) as db:
            # No observation survives a connection gap. Submitted sends still use normal recovery.
            intent = select(QQDelivery.id).where(QQDelivery.run_id == QQBatch.run_id).exists()
            db.exec(update(QQBatch).where(QQBatch.trigger_kind == "icebreaker",
                QQBatch.status.in_(("queued", "running")), ~intent)
                .values(status="cancelled", error_code="QQ_ICEBREAKER_CANCELLED"))
            db.commit()
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
