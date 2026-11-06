"""Characters own defaults, identity and all conversations."""

from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.openapi import request_body
from ai_workbench.api.routes.personas import _cleanup_avatar
from ai_workbench.api.routes.sessions import delete_session_data
from ai_workbench.api.schemas.chat import SessionResponse
from ai_workbench.api.schemas.common import error_responses
from ai_workbench.api.schemas.characters import (
    CharacterDeleted, CharacterResponse, CharacterPatchRequest, NormalSessionCreate,
    NormalCharacterPatch, QQBotCharacterPatch, QQSessionCreate,
)
from ai_workbench.core.schema.character import CharacterCreate
from ai_workbench.core.schema.memory import MemoryDeletionChoice
from ai_workbench.api.memory_deletion import delete_normal_owner


router = APIRouter(prefix="/api/characters", tags=["characters"])


@router.get("", response_model=list[CharacterResponse])
def list_characters(state: RuntimeState = Depends(get_state)):
    return [character.public_response() for character in state.characters.list()]


@router.post("", response_model=CharacterResponse, responses=error_responses(400, 404, 409, 422, 503))
async def create_character(payload: CharacterCreate, state: RuntimeState = Depends(get_state)):
    return state.character_service.create(payload).public_response()


@router.get("/{character_id}", response_model=CharacterResponse, responses=error_responses(404))
def get_character(character_id: str, state: RuntimeState = Depends(get_state)):
    return state.character_service.get(character_id).public_response()


@router.patch("/{character_id}", response_model=CharacterResponse,
    responses=error_responses(400, 404, 409, 422, 503), openapi_extra=request_body(CharacterPatchRequest,
        description="Update defaults for the immutable Character type. QQBot requires an explicit external model to connect."))
async def update_character(character_id: str, payload: dict, state: RuntimeState = Depends(get_state)):
    current = state.character_service.get(character_id)
    schema = NormalCharacterPatch if current.kind == "normal" else QQBotCharacterPatch
    values = schema.model_validate(payload).model_dump(exclude_unset=True)
    updated = state.character_service.update(character_id, values)
    state.qq.character_updated(current, updated)
    if current.avatar_attachment_id != updated.avatar_attachment_id:
        _cleanup_avatar(state, current.avatar_attachment_id)
    for session in state.character_service.sessions(character_id):
        state.events.emit("character_updated", session_id=session.session_id,
            payload={"character": updated.public_response()})
        state.events.emit("session_updated", session_id=session.session_id,
            payload={"session": state.chat_service.session_response(session)})
    return updated.public_response()


@router.delete("/{character_id}", response_model=CharacterDeleted, responses=error_responses(404, 409, 422))
async def delete_character(character_id: str, payload: MemoryDeletionChoice | None = None, state: RuntimeState = Depends(get_state)):
    state.character_service.assert_deletable(character_id)
    current = state.character_service.get(character_id)
    if current.kind == "normal":
        ids = delete_normal_owner(state, payload or MemoryDeletionChoice(), character_id=character_id)
        _cleanup_avatar(state, current.avatar_attachment_id)
        return {"deleted": True, "character_id": character_id, "deleted_session_ids": ids}
    ids = [session.session_id for session in state.character_service.sessions(character_id)]
    for session_id in ids:
        state.qq.assert_idle(session_id)
    for session_id in ids:
        delete_session_data(state, session_id)
    state.qq.store.delete_character_notifications(character_id)
    state.characters.delete(character_id)
    _cleanup_avatar(state, current.avatar_attachment_id)
    return {"deleted": True, "character_id": character_id, "deleted_session_ids": ids}


@router.get("/{character_id}/sessions", response_model=list[SessionResponse], response_model_exclude_unset=True,
    responses=error_responses(404))
def list_character_sessions(character_id: str, state: RuntimeState = Depends(get_state)):
    return [state.chat_service.session_response(session) for session in state.character_service.sessions(character_id)]


@router.post("/{character_id}/sessions", response_model=SessionResponse, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 409, 422, 503))
async def create_character_session(character_id: str, payload: NormalSessionCreate | QQSessionCreate,
                                   state: RuntimeState = Depends(get_state)):
    values = payload.model_dump(exclude_unset=True)
    if state.character_service.get(character_id).kind == "qqbot":
        values = QQSessionCreate.model_validate(values).model_dump()
        session = state.qq.create_session(character_id, values)
    else:
        values = NormalSessionCreate.model_validate(values).model_dump(exclude_unset=True)
        session = state.chat_service.create_session(character_id, values)
    return state.chat_service.session_response(session)
