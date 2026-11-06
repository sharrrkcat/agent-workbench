"""User Persona management; resources and sessions belong to Characters."""

from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.schemas.chat import PersonaResponse, PersonaPatch, PersonaDeleted
from ai_workbench.api.schemas.common import error_responses
from ai_workbench.core.attachments import delete_attachment_if_unreferenced
from ai_workbench.core.schema.persona import PersonaInput


router = APIRouter(prefix="/api/personas", tags=["personas"])


@router.get("", response_model=list[PersonaResponse])
def list_personas(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [p.public_response() for p in state.personas.list()]


@router.post("", response_model=PersonaResponse, responses=error_responses(400, 422))
async def create_persona(payload: PersonaInput, state: RuntimeState = Depends(get_state)) -> dict:
    state.chat_service.validate_avatar(payload.avatar_attachment_id)
    return state.personas.create(payload).public_response()


@router.get("/{persona_id}", response_model=PersonaResponse, responses=error_responses(404))
def get_persona(persona_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    return state.chat_service.persona(persona_id).public_response()


@router.patch("/{persona_id}", response_model=PersonaResponse, responses=error_responses(400, 404, 422))
async def update_persona(persona_id: str, payload: PersonaPatch, state: RuntimeState = Depends(get_state)) -> dict:
    current = state.chat_service.persona(persona_id)
    updates = payload.model_dump(exclude_unset=True)
    values = PersonaInput.model_validate({**current.model_dump(include=set(PersonaInput.model_fields)), **updates})
    state.chat_service.validate_avatar(values.avatar_attachment_id)
    updated = state.personas.update(persona_id, updates)
    if current.avatar_attachment_id != updated.avatar_attachment_id:
        _cleanup_avatar(state, current.avatar_attachment_id)
    _notify_identity(state, persona_id, "persona_updated", {"persona": updated.public_response()})
    for session in state.sessions.list_sessions():
        if state.chat_service.selected_persona_id(session) == persona_id:
            state.events.emit("session_updated", session_id=session.session_id,
                payload={"session": state.chat_service.session_response(session)})
    return updated.public_response()


@router.delete("/{persona_id}", response_model=PersonaDeleted, responses=error_responses(404, 409))
async def delete_persona(persona_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    current = state.chat_service.delete_persona(persona_id)
    _cleanup_avatar(state, current.avatar_attachment_id)
    _notify_identity(state, persona_id, "persona_deleted", {"persona_id": persona_id})
    return {"deleted": True, "persona_id": persona_id}


def _cleanup_avatar(state, attachment_id):
    if attachment_id:
        delete_attachment_if_unreferenced({"id": attachment_id, "uri": "local://attachments/" + attachment_id},
            state.messages, persona_store=state.personas, character_store=state.characters,
            knowledge_store=state.knowledge, run_store=state.runs, qq_store=state.qq.store)


def _notify_identity(state: RuntimeState, persona_id: str, event_type: str, payload: dict) -> None:
    session_ids = state.runs.referencing_session_ids(persona_id)
    session_ids.update(state.messages.referencing_session_ids(persona_id))
    for session in state.sessions.list_sessions():
        if session.session_id in session_ids or state.chat_service.selected_persona_id(session) == persona_id:
            state.events.emit(event_type, session_id=session.session_id, payload=payload)
