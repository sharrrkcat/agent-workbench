from __future__ import annotations

import json
from typing import Generic, TypeVar

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import ModelInput, ModelProfile, ModelSettings, ProviderInput, ProviderProfile
from ai_workbench.core.time import utc_now
from ai_workbench.db.models import AppMetadataRecord, ModelProfileRecord, ProviderProfileRecord

T = TypeVar("T", ModelProfile, ProviderProfile)


class _Store(Generic[T]):
    def __init__(self, schema, record_type, input_type, engine=None):
        self.schema = schema
        self.record_type = record_type
        self.input_type = input_type
        self.engine = engine
        self._records: dict[str, T] = {}

    def _decode(self, record) -> T:
        data = record.model_dump()
        for key in ("capabilities", "parameters", "lifecycle"):
            if key + "_json" in data:
                data[key] = json.loads(data.pop(key + "_json"))
        return self.schema.model_validate(data)

    def _encode(self, profile) -> dict:
        data = profile.model_dump()
        for key in ("capabilities", "parameters", "lifecycle"):
            if key in data:
                data[key + "_json"] = json.dumps(data.pop(key))
        return data

    def get(self, profile_id: str) -> T:
        if self.engine is None:
            return self._records[profile_id].model_copy(deep=True)
        with Session(self.engine) as db:
            record = db.get(self.record_type, profile_id)
            if record is None:
                raise KeyError(profile_id)
            return self._decode(record)

    def list(self) -> list[T]:
        if self.engine is None:
            return sorted((p.model_copy(deep=True) for p in self._records.values()), key=lambda p: (p.name, p.id))
        with Session(self.engine) as db:
            return [self._decode(r) for r in db.exec(select(self.record_type).order_by(self.record_type.name, self.record_type.id)).all()]

    def create(self, profile: T) -> T:
        profile = self.schema.model_validate(profile.model_dump())
        if self.engine is None:
            if profile.id in self._records or (hasattr(profile, "alias") and any(p.alias == profile.alias for p in self._records.values())):
                raise ModelError("MODEL_ALIAS_EXISTS", "Model alias or id already exists.", 409)
            self._records[profile.id] = profile
        else:
            with Session(self.engine) as db:
                db.add(self.record_type(**self._encode(profile)))
                try:
                    db.commit()
                except IntegrityError as exc:
                    db.rollback()
                    raise ModelError("MODEL_CONFLICT", "Profile alias, id or provider reference conflicts.", 409) from exc
        return profile.model_copy(deep=True)

    def update(self, profile_id: str, values: dict) -> T:
        current = self.get(profile_id)
        data = self.input_type.model_validate({**current.model_dump(include=set(self.input_type.model_fields)), **values}).model_dump()
        updated = self.schema.model_validate({**current.model_dump(), **data, "updated_at": utc_now()})
        if self.engine is None:
            if hasattr(updated, "alias") and any(p.id != profile_id and p.alias == updated.alias for p in self._records.values()):
                raise ModelError("MODEL_ALIAS_EXISTS", "Model alias already exists.", 409)
            self._records[profile_id] = updated
        else:
            with Session(self.engine) as db:
                record = db.get(self.record_type, profile_id)
                for key, value in self._encode(updated).items():
                    setattr(record, key, value)
                db.add(record)
                try:
                    db.commit()
                except IntegrityError as exc:
                    db.rollback()
                    raise ModelError("MODEL_CONFLICT", "Profile alias or provider reference conflicts.", 409) from exc
        return updated.model_copy(deep=True)

    def delete(self, profile_id: str) -> T:
        current = self.get(profile_id)
        if self.engine is None:
            del self._records[profile_id]
        else:
            with Session(self.engine) as db:
                db.delete(db.get(self.record_type, profile_id))
                db.commit()
        return current


class ModelProfileStore(_Store[ModelProfile]):
    def __init__(self, engine=None):
        super().__init__(ModelProfile, ModelProfileRecord, ModelInput, engine)

    def list(self, kind: str | None = None) -> list[ModelProfile]:
        return [p for p in super().list() if kind is None or p.kind == kind]

    def find_by_alias(self, alias: str) -> ModelProfile | None:
        if self.engine is None:
            return next((p for p in self.list() if p.alias == alias), None)
        with Session(self.engine) as db:
            record = db.exec(select(ModelProfileRecord).where(ModelProfileRecord.alias == alias)).first()
            return self._decode(record) if record else None


class ProviderProfileStore(_Store[ProviderProfile]):
    def __init__(self, engine=None):
        super().__init__(ProviderProfile, ProviderProfileRecord, ProviderInput, engine)


class ModelSettingsStore:
    def __init__(self, engine=None):
        self.engine = engine
        self._settings = ModelSettings()

    def get(self) -> ModelSettings:
        if self.engine is None:
            return self._settings.model_copy(deep=True)
        with Session(self.engine) as db:
            record = db.get(AppMetadataRecord, "model_settings")
            return ModelSettings.model_validate_json(record.value) if record else ModelSettings()

    def patch(self, values: dict) -> ModelSettings:
        updated = ModelSettings.model_validate({**self.get().model_dump(), **values})
        if self.engine is None:
            self._settings = updated
        else:
            with Session(self.engine) as db:
                record = db.get(AppMetadataRecord, "model_settings") or AppMetadataRecord(key="model_settings", value="{}")
                record.value = updated.model_dump_json()
                record.updated_at = utc_now()
                db.add(record)
                db.commit()
        return updated.model_copy(deep=True)
