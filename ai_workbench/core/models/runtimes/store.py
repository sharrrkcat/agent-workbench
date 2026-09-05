from __future__ import annotations

from sqlmodel import Session, select

from ai_workbench.core.models.runtimes.schema import DownloadSettings, Installation, RuntimeJob, TERMINAL
from ai_workbench.core.time import utc_now
from ai_workbench.db.models import AppMetadataRecord, RuntimeInstallationRecord, RuntimeJobRecord


class RuntimeStore:
    def __init__(self, engine=None):
        self.engine = engine
        self._installations: dict[str, Installation] = {}
        self._jobs: dict[str, RuntimeJob] = {}
        self._settings = DownloadSettings()

    def installations(self) -> list[Installation]:
        if self.engine is None:
            return [value.model_copy(deep=True) for value in self._installations.values()]
        with Session(self.engine) as db:
            return [Installation.model_validate(row.model_dump()) for row in db.exec(select(RuntimeInstallationRecord))]

    def save_installation(self, value: Installation):
        value.updated_at = utc_now()
        self._save(value, RuntimeInstallationRecord, self._installations)
        return value

    def jobs(self) -> list[RuntimeJob]:
        if self.engine is None:
            values = [value.model_copy(deep=True) for value in self._jobs.values()]
        else:
            with Session(self.engine) as db:
                values = [RuntimeJob.model_validate(row.model_dump()) for row in db.exec(select(RuntimeJobRecord))]
        return sorted(values, key=lambda job: (job.created_at, job.id), reverse=True)

    def job(self, job_id: str) -> RuntimeJob:
        if self.engine is None:
            return self._jobs[job_id].model_copy(deep=True)
        with Session(self.engine) as db:
            row = db.get(RuntimeJobRecord, job_id)
            if row is None:
                raise KeyError(job_id)
            return RuntimeJob.model_validate(row.model_dump())

    def save_job(self, value: RuntimeJob):
        value.updated_at = utc_now()
        try:
            previous = self.job(value.id).revision
        except KeyError:
            previous = 0
        value.revision = max(previous, value.revision) + 1
        self._save(value, RuntimeJobRecord, self._jobs)
        return value

    def _save(self, value, record_type, memory):
        if self.engine is None:
            memory[value.id] = value.model_copy(deep=True)
            return
        with Session(self.engine) as db:
            row = db.get(record_type, value.id) or record_type(**value.model_dump())
            for key, item in value.model_dump().items():
                setattr(row, key, item)
            db.add(row)
            db.commit()

    def settings(self) -> DownloadSettings:
        if self.engine is None:
            return self._settings.model_copy(deep=True)
        with Session(self.engine) as db:
            row = db.get(AppMetadataRecord, "runtime_settings")
            return DownloadSettings.model_validate_json(row.value) if row else DownloadSettings()

    def patch_settings(self, patch: dict) -> DownloadSettings:
        value = DownloadSettings.model_validate({**self.settings().model_dump(), **patch})
        if self.engine is None:
            self._settings = value
        else:
            with Session(self.engine) as db:
                row = db.get(AppMetadataRecord, "runtime_settings") or AppMetadataRecord(key="runtime_settings", value="{}")
                row.value = value.model_dump_json()
                row.updated_at = utc_now()
                db.add(row)
                db.commit()
        return value

    def interrupt_unfinished(self):
        for job in self.jobs():
            if job.state not in TERMINAL:
                job.state = "interrupted"
                job.error_code = "RUNTIME_INTERRUPTED"
                job.finished_at = utc_now()
                self.save_job(job)
        for value in self.installations():
            if value.state == "installing":
                value.state = "interrupted"
                value.error_code = "RUNTIME_INTERRUPTED"
                self.save_installation(value)
