"""Memory and SQLite persistence for typed Projects and ordered bindings."""

import json

from sqlmodel import Session, delete, select

from ai_workbench.core.schema.project import Project, project_adapter
from ai_workbench.db.models import ProjectRecord, ProjectKnowledgeBindingRecord, ProjectWorldbookBindingRecord


BINDINGS = {
    "workspace": (ProjectKnowledgeBindingRecord, "knowledge_base_id", "knowledge_base_ids"),
    "timeline": (ProjectWorldbookBindingRecord, "worldbook_id", "worldbook_ids"),
}


class ProjectStore:
    def __init__(self, engine=None):
        self.engine = engine
        self._projects: dict[str, Project] = {}

    @staticmethod
    def _decode(row: ProjectRecord, db: Session) -> Project:
        values = row.model_dump()
        values.update(json.loads(values.pop("configuration_json")))
        record, key, field = BINDINGS[row.kind]
        values[field] = [getattr(binding, key) for binding in db.exec(
            select(record).where(record.project_id == row.id).order_by(record.sort_order)).all()]
        return project_adapter.validate_python(values)

    def list(self) -> list[Project]:
        if self.engine is None:
            return sorted((p.model_copy(deep=True) for p in self._projects.values()),
                          key=lambda p: (p.updated_at, p.created_at, p.id), reverse=True)
        with Session(self.engine) as db:
            return [self._decode(row, db) for row in db.exec(select(ProjectRecord).order_by(
                ProjectRecord.updated_at.desc(), ProjectRecord.created_at.desc(), ProjectRecord.id.desc())).all()]

    def get(self, project_id: str) -> Project:
        if self.engine is None:
            return self._projects[project_id].model_copy(deep=True)
        with Session(self.engine) as db:
            row = db.get(ProjectRecord, project_id)
            if row is None:
                raise KeyError(project_id)
            return self._decode(row, db)

    def save(self, project: Project) -> Project:
        if self.engine is None:
            self._projects[project.id] = project.model_copy(deep=True)
        else:
            record, key, field = BINDINGS[project.kind]
            values = project.model_dump()
            ids = values.pop(field)
            metadata = {key: values.pop(key) for key in ("id", "name", "kind", "created_at", "updated_at")}
            metadata["configuration_json"] = json.dumps(values, ensure_ascii=False)
            with Session(self.engine) as db:
                row = db.get(ProjectRecord, project.id)
                if row is None:
                    row = ProjectRecord(**metadata)
                else:
                    for name, value in metadata.items():
                        setattr(row, name, value)
                db.add(row)
                db.flush()
                db.exec(delete(record).where(record.project_id == project.id))
                for index, resource_id in enumerate(ids):
                    db.add(record(project_id=project.id, sort_order=index, **{key: resource_id}))
                db.commit()
        return project.model_copy(deep=True)

    def delete(self, project_id: str) -> None:
        project = self.get(project_id)
        if self.engine is None:
            del self._projects[project_id]
        else:
            record, _, _ = BINDINGS[project.kind]
            with Session(self.engine) as db:
                db.exec(delete(record).where(record.project_id == project_id))
                db.delete(db.get(ProjectRecord, project_id))
                db.commit()

    def references_persona(self, persona_id: str) -> bool:
        return any(persona_id in (
            (project.agent_persona_id, project.cogita_persona_id) if project.kind == "workspace"
            else (project.character_persona_id, project.user_persona_id)) for project in self.list())

    def references_resource(self, kind: str, resource_id: str) -> bool:
        return any(resource_id in (
            project.knowledge_base_ids if kind == "knowledge" and project.kind == "workspace"
            else project.worldbook_ids if kind == "worldbook" and project.kind == "timeline" else [])
            for project in self.list())
