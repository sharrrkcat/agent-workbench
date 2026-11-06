"""User Persona persistence, without resources or conversation ownership."""

from sqlmodel import Session, select

from ai_workbench.core.schema.persona import Persona, PersonaInput, seed_personas
from ai_workbench.core.time import utc_now
from ai_workbench.db.models import PersonaRecord


class PersonaStore:
    def __init__(self, engine=None):
        self.engine = engine
        self._personas = {p.id: p for p in seed_personas()} if engine is None else {}

    def list(self) -> list[Persona]:
        if self.engine is None:
            return sorted((p.model_copy(deep=True) for p in self._personas.values()), key=lambda p: (p.name, p.id))
        with Session(self.engine) as db:
            return [Persona.model_validate(r.model_dump()) for r in db.exec(
                select(PersonaRecord).order_by(PersonaRecord.name, PersonaRecord.id)).all()]

    def get(self, persona_id: str) -> Persona:
        if self.engine is None:
            return self._personas[persona_id].model_copy(deep=True)
        with Session(self.engine) as db:
            row = db.get(PersonaRecord, persona_id)
            if row is None:
                raise KeyError(persona_id)
            return Persona.model_validate(row.model_dump())

    def _save(self, persona: Persona) -> Persona:
        if self.engine is None:
            self._personas[persona.id] = persona.model_copy(deep=True)
        else:
            with Session(self.engine) as db:
                db.merge(PersonaRecord(**persona.model_dump()))
                db.commit()
        return persona.model_copy(deep=True)

    def create(self, values: PersonaInput) -> Persona:
        return self._save(Persona(**values.model_dump()))

    def update(self, persona_id: str, values: dict) -> Persona:
        return self._save(Persona.model_validate({**self.get(persona_id).model_dump(), **values, "updated_at": utc_now()}))

    def delete(self, persona_id: str) -> Persona:
        current = self.get(persona_id)
        if self.engine is None:
            del self._personas[persona_id]
        else:
            with Session(self.engine) as db:
                db.delete(db.get(PersonaRecord, persona_id))
                db.commit()
        return current

    def references_attachment(self, attachment_id: str) -> bool:
        return any(p.avatar_attachment_id == attachment_id for p in self.list())

    def referenced_attachments(self, names: set[str]) -> set[str]:
        if self.engine is None:
            return {p.avatar_attachment_id for p in self._personas.values() if p.avatar_attachment_id in names}
        with Session(self.engine) as db:
            return set(db.exec(select(PersonaRecord.avatar_attachment_id).where(PersonaRecord.avatar_attachment_id.in_(names))))
