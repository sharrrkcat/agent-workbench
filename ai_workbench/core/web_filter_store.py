"""Small transactions for filter settings, separate from page evidence caches."""
from sqlmodel import Session, select
from sqlalchemy.dialects.sqlite import insert

from ai_workbench.core.web_filter_defaults import DEFAULT_CUSTOM_RULES, DEFAULT_SUBSCRIPTIONS
from ai_workbench.db.web_filter_models import WebFilterSettingsRecord, WebSubscriptionRecord


class WebFilterStore:
    def __init__(self, engine=None):
        self.engine = engine
        self.settings = WebFilterSettingsRecord(custom_rules=DEFAULT_CUSTOM_RULES)
        self.subscriptions = {identity: WebSubscriptionRecord(id=identity, name=name, url=url)
                              for identity, name, url in DEFAULT_SUBSCRIPTIONS}

    def load(self):
        if self.engine is None:
            return self.settings.model_copy(), {key: value.model_copy() for key, value in self.subscriptions.items()}
        with Session(self.engine) as db:
            settings = db.get(WebFilterSettingsRecord, 1)
            subscriptions = db.exec(select(WebSubscriptionRecord).order_by(
                WebSubscriptionRecord.created_at, WebSubscriptionRecord.id)).all()
            return settings, {row.id: row for row in subscriptions}

    def write(self, *, settings=None, subscription=None, deleted_id=None):
        if self.engine is None:
            if settings is not None:
                self.settings = settings.model_copy()
            if subscription is not None:
                self.subscriptions[subscription.id] = subscription.model_copy()
            if deleted_id is not None:
                self.subscriptions.pop(deleted_id)
            return
        with Session(self.engine) as db:
            # Snapshots are value copies; persist columns instead of copied ORM state.
            for record in (settings, subscription):
                if record is not None:
                    values = record.model_dump()
                    statement = insert(type(record)).values(**values)
                    db.exec(statement.on_conflict_do_update(index_elements=["id"],
                        set_={key: getattr(statement.excluded, key) for key in values if key != "id"}))
            if deleted_id is not None:
                db.delete(db.get(WebSubscriptionRecord, deleted_id))
            db.commit()

