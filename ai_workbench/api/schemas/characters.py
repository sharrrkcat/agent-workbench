"""Strict Character and owned Session HTTP inputs and responses."""

from typing import Annotated, Literal

from pydantic import Field, RootModel

from ai_workbench.api.schemas.common import ApiModel, patch_model, public_model
from ai_workbench.core.schema.character import NormalCharacterInput, NormalCharacter, QQBotInput, QQBotCharacter
from ai_workbench.core.schema.chat_config import SessionOverrides


_protected = {"is_protected": (bool, Field(json_schema_extra={"readOnly": True}))}
NormalCharacterResponse = public_model("NormalCharacterResponse", NormalCharacter, fields=_protected)
QQBotCharacterResponse = public_model("QQBotCharacterResponse", QQBotCharacter, omit={"access_token"},
    fields={**_protected, "has_access_token": (bool, ...)})
CharacterResponse = Annotated[NormalCharacterResponse | QQBotCharacterResponse, Field(discriminator="kind")]
NormalCharacterPatch = patch_model("NormalCharacterPatch", NormalCharacterInput, omit={"kind"})
QQBotCharacterPatch = patch_model("QQBotCharacterPatch", QQBotInput, omit={"kind"})


class CharacterPatchRequest(RootModel[NormalCharacterPatch | QQBotCharacterPatch]):
    pass


class CharacterDeleted(ApiModel):
    deleted: bool
    character_id: str
    deleted_session_ids: list[str]


class NormalSessionCreate(ApiModel):
    title: str = Field(default="", max_length=120)
    overrides: SessionOverrides = Field(default_factory=SessionOverrides)


class QQSessionCreate(ApiModel):
    title: str = Field(default="", max_length=120)
    target_kind: Literal["group", "friend"]
    target_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
