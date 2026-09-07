"""Persona persistence, including ordered default context bindings."""

from __future__ import annotations

from sqlmodel import Session, delete, select

from ai_workbench.core.schema.persona import Persona, PersonaInput, seed_personas
from ai_workbench.core.time import utc_now
from ai_workbench.db.models import PersonaRecord, PersonaKnowledgeBindingRecord, PersonaWorldbookBindingRecord


BINDINGS = {
    "knowledge": (PersonaKnowledgeBindingRecord, "knowledge_base_id"),
    "worldbook": (PersonaWorldbookBindingRecord, "worldbook_id"),
}


class PersonaStore:
    def __init__(self, engine=None):
        self.engine = engine
        self._personas = {p.id: p for p in seed_personas()} if engine is None else {}
        self._bindings: dict[tuple[str, str], list[str]] = {}

    @staticmethod
    def _decode(row: PersonaRecord) -> Persona:
        return Persona.model_validate(row.model_dump())

    @staticmethod
    def _encode(persona: Persona) -> dict:
        return persona.model_dump()

    def list(self) -> list[Persona]:
        if self.engine is None:
            return sorted((p.model_copy(deep=True) for p in self._personas.values()), key=lambda p: (p.name, p.id))
        with Session(self.engine) as db:
            return [self._decode(r) for r in db.exec(select(PersonaRecord).order_by(PersonaRecord.name, PersonaRecord.id)).all()]

    def get(self, persona_id: str) -> Persona:
        if self.engine is None:
            return self._personas[persona_id].model_copy(deep=True)
        with Session(self.engine) as db:
            row = db.get(PersonaRecord, persona_id)
            if row is None:
                raise KeyError(persona_id)
            return self._decode(row)

    def create(self, values: PersonaInput) -> Persona:
        persona = Persona(**values.model_dump())
        if self.engine is None:
            self._personas[persona.id] = persona
        else:
            with Session(self.engine) as db:
                db.add(PersonaRecord(**self._encode(persona)))
                db.commit()
        return persona.model_copy(deep=True)

    def update(self, persona_id: str, values: dict) -> Persona:
        current = self.get(persona_id)
        data = PersonaInput.model_validate({**current.model_dump(include=set(PersonaInput.model_fields)), **values})
        persona = Persona(**{**current.model_dump(), **data.model_dump(), "updated_at": utc_now()})
        if self.engine is None:
            self._personas[persona_id] = persona
        else:
            with Session(self.engine) as db:
                row = db.get(PersonaRecord, persona_id)
                for key, value in self._encode(persona).items():
                    setattr(row, key, value)
                db.add(row)
                db.commit()
        return persona.model_copy(deep=True)

    def delete(self, persona_id: str) -> Persona:
        current = self.get(persona_id)
        if self.engine is None:
            del self._personas[persona_id]
            for kind in BINDINGS:
                self._bindings.pop((persona_id, kind), None)
        else:
            with Session(self.engine) as db:
                for record, _field in BINDINGS.values():
                    db.exec(delete(record).where(record.persona_id == persona_id))
                db.delete(db.get(PersonaRecord, persona_id))
                db.commit()
        return current

    def binding_ids(self, persona_id: str, kind: str) -> list[str]:
        self.get(persona_id)
        if self.engine is None:
            return list(self._bindings.get((persona_id, kind), []))
        record, key = BINDINGS[kind]
        with Session(self.engine) as db:
            return [getattr(r, key) for r in db.exec(select(record).where(record.persona_id == persona_id).order_by(record.sort_order)).all()]

    def replace_bindings(self, persona_id: str, kind: str, ids: list[str]) -> list[str]:
        self.get(persona_id)
        if len(ids) != len(set(ids)):
            raise ValueError("Bindings must be unique")
        if self.engine is None:
            self._bindings[persona_id, kind] = list(ids)
        else:
            record, key = BINDINGS[kind]
            with Session(self.engine) as db:
                db.exec(delete(record).where(record.persona_id == persona_id))
                for index, value in enumerate(ids):
                    db.add(record(persona_id=persona_id, sort_order=index, **{key: value}))
                db.commit()
        return list(ids)

    def references_resource(self, kind: str, resource_id: str) -> bool:
        return any(resource_id in self.binding_ids(p.id, kind) for p in self.list())

    def references_attachment(self, attachment_id: str) -> bool:
        return any(p.avatar_attachment_id == attachment_id for p in self.list())
