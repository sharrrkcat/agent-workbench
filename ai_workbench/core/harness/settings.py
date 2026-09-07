from __future__ import annotations

import json
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator
from sqlmodel import Session as DbSession

from ai_workbench.db.models import AppMetadataRecord


class HarnessSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    searxng_base_url: str | None = None

    @field_validator("searxng_base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        value = str(value).strip().rstrip("/")
        parsed = urlsplit(value)
        _ = parsed.port
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("searxng_base_url must be an HTTP(S) URL without credentials, query or fragment")
        return value


class HarnessSettingsStore:
    _KEY = "harness_settings"

    def __init__(self, engine=None) -> None:
        self.engine = engine
        self._settings = HarnessSettings()

    def get(self) -> HarnessSettings:
        if self.engine is None:
            return self._settings
        with DbSession(self.engine) as db:
            row = db.get(AppMetadataRecord, self._KEY)
            return HarnessSettings.model_validate(json.loads(row.value) if row else {})

    def patch(self, values: dict) -> HarnessSettings:
        current = self.get().model_dump()
        current.update(values)
        result = HarnessSettings.model_validate(current)
        if self.engine is None:
            self._settings = result
            return result
        with DbSession(self.engine) as db:
            row = db.get(AppMetadataRecord, self._KEY)
            encoded = json.dumps(result.model_dump(), ensure_ascii=False, separators=(",", ":"))
            if row is None:
                row = AppMetadataRecord(key=self._KEY, value=encoded)
            else:
                row.value = encoded
            db.add(row)
            db.commit()
        return result
