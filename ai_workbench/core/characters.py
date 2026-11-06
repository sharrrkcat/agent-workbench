"""Memory and SQLite persistence for Characters and their default configuration."""

import json

from sqlmodel import Session, select

from ai_workbench.core.schema.character import Character, character_adapter
from ai_workbench.db.models import CharacterRecord


class CharacterStore:
    def __init__(self, engine=None):
        self.engine = engine
        self._characters: dict[str, Character] = {}

    @staticmethod
    def _decode(row: CharacterRecord) -> Character:
        values = row.model_dump()
        values.update(json.loads(values.pop("configuration_json")))
        return character_adapter.validate_python(values)

    def list(self) -> list[Character]:
        if self.engine is None:
            return sorted((p.model_copy(deep=True) for p in self._characters.values()),
                          key=lambda p: (p.updated_at, p.created_at, p.id), reverse=True)
        with Session(self.engine) as db:
            return [self._decode(row) for row in db.exec(select(CharacterRecord).order_by(
                CharacterRecord.updated_at.desc(), CharacterRecord.created_at.desc(), CharacterRecord.id.desc())).all()]

    def get(self, character_id: str) -> Character:
        if self.engine is None:
            return self._characters[character_id].model_copy(deep=True)
        with Session(self.engine) as db:
            row = db.get(CharacterRecord, character_id)
            if row is None:
                raise KeyError(character_id)
            return self._decode(row)

    def save(self, character: Character) -> Character:
        if self.engine is None:
            self._characters[character.id] = character.model_copy(deep=True)
        else:
            values = character.model_dump()
            metadata = {key: values.pop(key) for key in ("id", "name", "kind", "created_at", "updated_at")}
            metadata["configuration_json"] = json.dumps(values, ensure_ascii=False)
            with Session(self.engine) as db:
                row = db.get(CharacterRecord, character.id)
                if row is None:
                    row = CharacterRecord(**metadata)
                else:
                    for name, value in metadata.items():
                        setattr(row, name, value)
                db.add(row)
                db.commit()
        return character.model_copy(deep=True)

    def delete(self, character_id: str) -> None:
        if self.engine is None:
            del self._characters[character_id]
        else:
            with Session(self.engine) as db:
                db.delete(db.get(CharacterRecord, character_id))
                db.commit()

    def references_persona(self, persona_id: str) -> bool:
        return any(p.kind == "normal" and p.persona_id == persona_id for p in self.list())

    def references_resource(self, kind: str, resource_id: str) -> bool:
        field = "knowledge_base_ids" if kind == "knowledge" else "worldbook_ids"
        return any(p.kind == "normal" and resource_id in getattr(p, field) for p in self.list())

    def references_attachment(self, attachment_id: str) -> bool:
        return any(p.avatar_attachment_id == attachment_id for p in self.list())

    def referenced_attachments(self, names: set[str]) -> set[str]:
        return {p.avatar_attachment_id for p in self.list() if p.avatar_attachment_id in names}
