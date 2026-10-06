"""Global QQ gallery operations and explicit shared-resource deletion."""
from sqlalchemy import func, update
from sqlmodel import Session, select

from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.schema.qq import QQImageCandidate
from ai_workbench.core.time import utc_now
from ai_workbench.db.qq_models import QQMedia, QQMediaAsset, QQMessage, QQDelivery


def incoming_reference(*, pictures_only=False):
    query = select(QQMedia.id).join(QQMessage, QQMedia.message_id == QQMessage.id).where(
        QQMedia.asset_id == QQMediaAsset.id, QQMessage.deleted == False)
    if pictures_only:
        query = query.where(QQMedia.kind != "face")
    return query.correlate(QQMediaAsset).exists()


def outgoing_reference():
    return select(QQDelivery.id).where(QQDelivery.asset_id == QQMediaAsset.id,
        QQDelivery.deleted == False, QQDelivery.kind.in_(("generated_image", "resource_image"))).correlate(QQMediaAsset).exists()


def gallery_resource():
    return (QQMediaAsset.is_favorite == True) | incoming_reference(pictures_only=True) | outgoing_reference()


def public_resource(asset, has_references):
    return {"id": asset.id, "attachment": asset.attachment.model_dump(), "description": asset.description,
        "is_favorite": asset.is_favorite, "created_at": asset.created_at, "has_references": has_references}


class QQResources:
    def __init__(self, state, store):
        self.state, self.store = state, store

    def image_candidates(self):
        with Session(self.store.engine) as db:
            rows = db.exec(select(QQMediaAsset.id, QQMediaAsset.description).where(
                QQMediaAsset.is_favorite == True, QQMediaAsset.description.is_not(None))
                .order_by(QQMediaAsset.id)).all()
            return [QQImageCandidate(asset_id=asset_id, description=description)
                for asset_id, description in rows if description.strip()]

    def page(self, page, page_size, sort, order, favorite):
        condition = gallery_resource()
        if favorite != "all":
            condition &= QQMediaAsset.is_favorite == (favorite == "favorites")
        sort_column = QQMediaAsset.created_at if sort == "created_at" else func.json_extract(QQMediaAsset.attachment_json, "$.size")
        ordering = [column.desc() if order == "desc" else column.asc() for column in (sort_column, QQMediaAsset.id)]
        with Session(self.store.engine) as db:
            total = db.exec(select(func.count()).select_from(QQMediaAsset).where(condition)).one()
            rows = db.exec(select(QQMediaAsset, incoming_reference() | outgoing_reference()).where(condition)
                .order_by(*ordering).offset((page - 1) * page_size).limit(page_size)).all()
            return {"items": [public_resource(asset, referenced) for asset, referenced in rows],
                "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def resource(db, asset_id):
        asset = db.exec(select(QQMediaAsset).where(QQMediaAsset.id == asset_id, gallery_resource())).first()
        if asset is None:
            raise ChatError("QQ_RESOURCE_NOT_FOUND", "QQ image resource does not exist.", 404)
        return asset

    def update(self, asset_id, values):
        with Session(self.store.engine) as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            asset = self.resource(db, asset_id)
            sessions = self.store.asset_sessions(db, asset_id)
            if values.get("is_favorite") is False and not sessions:
                raise ChatError("QQ_RESOURCE_UNREFERENCED", "This image has no chat references. Confirm deletion to remove it.", 409)
            if "description" in values:
                description = values["description"]
                asset.description = description.strip() or None if description is not None else None
                asset.description_manual = True
                self.store.advance_history(db, sessions)
            if "is_favorite" in values:
                asset.is_favorite = values["is_favorite"]
            asset.updated_at = utc_now()
            db.add(asset)
            db.commit()
            db.refresh(asset)
            return public_resource(asset, bool(sessions))

    def delete(self, asset_id):
        with Session(self.store.engine) as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            asset = self.resource(db, asset_id)
            sessions = self.store.asset_sessions(db, asset_id)
            for session_id in sessions:
                self.state.chat_service.assert_idle(session_id)
                self.state.qq.assert_idle(session_id)
            attachments = {value.id for value in (asset.attachment, asset.model_attachment) if value is not None}
            db.exec(update(QQMedia).where(QQMedia.asset_id == asset_id)
                .values(asset_id=None, status="deleted", error_code=None))
            db.exec(update(QQDelivery).where(QQDelivery.asset_id == asset_id).values(asset_id=None))
            db.delete(asset)
            self.store.advance_history(db, sessions)
            db.commit()
        task = self.state.qq.descriptions.tasks.get(asset_id)
        if task is not None:
            task.cancel()
        self.state.qq.media.cleanup(attachments)
        return {"deleted": True}
