from __future__ import annotations

import json

from sqlmodel import Session, select

from ai_workbench.core.models.runtimes.schema import Installation, RuntimeJob, TERMINAL
from ai_workbench.core.time import utc_now
from ai_workbench.db.models import RuntimeInstallationRecord, RuntimeJobRecord


class RuntimeStore:
    def __init__(self, engine=None):
        self.engine = engine
        self._installations: dict[str, Installation] = {}
        self._jobs: dict[str, RuntimeJob] = {}

    def installations(self) -> list[Installation]:
        if self.engine is None:
            return [value.model_copy(deep=True) for value in self._installations.values()]
        with Session(self.engine) as db:
            return [Installation.model_validate(row.model_dump(exclude={"id"})) for row in db.exec(select(RuntimeInstallationRecord))]

    def save_installation(self, value: Installation):
        value.updated_at = utc_now()
        if self.engine is None:
            self._installations["local"] = value.model_copy(deep=True)
        else:
            with Session(self.engine) as db:
                row = db.get(RuntimeInstallationRecord, "local") or RuntimeInstallationRecord(**value.model_dump())
                for key, item in value.model_dump().items():
                    setattr(row, key, item)
                db.add(row)
                db.commit()
        return value

    def jobs(self) -> list[RuntimeJob]:
        if self.engine is None:
            values = [value.model_copy(deep=True) for value in self._jobs.values()]
        else:
            with Session(self.engine) as db:
                values = [self._read_job(row) for row in db.exec(select(RuntimeJobRecord))]
        return sorted(values, key=lambda job: (job.created_at, job.id), reverse=True)

    def job(self, job_id: str) -> RuntimeJob:
        if self.engine is None:
            return self._jobs[job_id].model_copy(deep=True)
        with Session(self.engine) as db:
            row = db.get(RuntimeJobRecord, job_id)
            if row is None:
                raise KeyError(job_id)
            return self._read_job(row)

    @staticmethod
    def _read_job(row):
        values = row.model_dump()
        result = values.pop("result_json")
        return RuntimeJob.model_validate({**values, "result": json.loads(result) if result is not None else None})

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
        values = value.model_dump()
        if isinstance(value, RuntimeJob):
            values.pop("result")
            values["result_json"] = value.result.model_dump_json() if value.result is not None else None
        with Session(self.engine) as db:
            row = db.get(record_type, value.id) or record_type(**values)
            for key, item in values.items():
                setattr(row, key, item)
            db.add(row)
            db.commit()

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
