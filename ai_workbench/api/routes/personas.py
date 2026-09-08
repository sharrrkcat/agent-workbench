from fastapi import APIRouter, Depends
from pydantic import Field

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.openapi import request_body
from ai_workbench.api.schemas.common import error_responses
from ai_workbench.api.schemas.chat import (
    PersonaResponse, PersonaPatch, PersonaDeleted, KnowledgeBindingsResponse, WorldbookBindingsResponse,
)
from ai_workbench.core.attachments import delete_attachment_if_unreferenced
from ai_workbench.core.models.schema import StrictModel
from ai_workbench.core.schema.persona import PersonaInput


router = APIRouter(prefix="/api/personas", tags=["personas"])


class KnowledgeBindingsPatch(StrictModel):
    knowledge_base_ids: list[str] = Field(max_length=128)


class WorldbookBindingsPatch(StrictModel):
    worldbook_ids: list[str] = Field(max_length=128)


@router.get("", response_model=list[PersonaResponse], response_model_exclude_unset=True)
def list_personas(state: RuntimeState = Depends(get_state)) -> list[dict]:
    return [p.model_dump(mode="json") for p in state.personas.list()]


@router.post("", response_model=PersonaResponse, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 422))
async def create_persona(payload: PersonaInput, state: RuntimeState = Depends(get_state)) -> dict:
    state.chat_service.validate_persona(payload)
    return state.personas.create(payload).model_dump(mode="json")


@router.get("/{persona_id}", response_model=PersonaResponse, response_model_exclude_unset=True,
    responses=error_responses(404))
def get_persona(persona_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    return state.chat_service.persona(persona_id).model_dump(mode="json")


@router.patch("/{persona_id}", response_model=PersonaResponse, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 422),
    openapi_extra=request_body(PersonaPatch, description="Omitted fields are preserved. null clears the avatar; an empty avatar id is invalid. system_prompt may be empty but not null."))
async def update_persona(persona_id: str, payload: dict, state: RuntimeState = Depends(get_state)) -> dict:
    current = state.chat_service.persona(persona_id)
    values = PersonaInput.model_validate({**current.model_dump(include=set(PersonaInput.model_fields)), **payload})
    state.chat_service.validate_persona(values)
    updated = state.personas.update(persona_id, payload)
    if current.avatar_attachment_id != updated.avatar_attachment_id:
        _cleanup_avatar(state, current.avatar_attachment_id)
    _notify_sessions(state, persona_id)
    return updated.model_dump(mode="json")


@router.delete("/{persona_id}", response_model=PersonaDeleted, response_model_exclude_unset=True,
    responses=error_responses(404, 409))
async def delete_persona(persona_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    current = state.chat_service.delete_persona(persona_id)
    _cleanup_avatar(state, current.avatar_attachment_id)
    return {"deleted": True, "persona_id": persona_id}


@router.get("/{persona_id}/knowledge-bases", response_model=KnowledgeBindingsResponse, response_model_exclude_unset=True,
    responses=error_responses(404))
def get_knowledge_bindings(persona_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    state.chat_service.persona(persona_id)
    return {"knowledge_base_ids": state.personas.binding_ids(persona_id, "knowledge")}


@router.patch("/{persona_id}/knowledge-bases", response_model=KnowledgeBindingsResponse, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 422))
async def set_knowledge_bindings(persona_id: str, payload: KnowledgeBindingsPatch, state: RuntimeState = Depends(get_state)) -> dict:
    state.chat_service.persona(persona_id)
    state.chat_service.validate_bindings("knowledge", payload.knowledge_base_ids)
    ids = state.personas.replace_bindings(persona_id, "knowledge", payload.knowledge_base_ids)
    _notify_sessions(state, persona_id)
    return {"knowledge_base_ids": ids}


@router.get("/{persona_id}/worldbooks", response_model=WorldbookBindingsResponse, response_model_exclude_unset=True,
    responses=error_responses(404))
def get_worldbook_bindings(persona_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    state.chat_service.persona(persona_id)
    return {"worldbook_ids": state.personas.binding_ids(persona_id, "worldbook")}


@router.patch("/{persona_id}/worldbooks", response_model=WorldbookBindingsResponse, response_model_exclude_unset=True,
    responses=error_responses(400, 404, 422))
async def set_worldbook_bindings(persona_id: str, payload: WorldbookBindingsPatch, state: RuntimeState = Depends(get_state)) -> dict:
    state.chat_service.persona(persona_id)
    state.chat_service.validate_bindings("worldbook", payload.worldbook_ids)
    ids = state.personas.replace_bindings(persona_id, "worldbook", payload.worldbook_ids)
    _notify_sessions(state, persona_id)
    return {"worldbook_ids": ids}


def _cleanup_avatar(state, attachment_id):
    if attachment_id:
        delete_attachment_if_unreferenced({"id": attachment_id, "uri": "local://attachments/" + attachment_id},
            state.messages, persona_store=state.personas, run_store=state.runs, knowledge_store=state.knowledge)


def _notify_sessions(state, persona_id):
    for session in state.sessions.list_sessions():
        if any(m.persona_id == persona_id for m in session.personas):
            state.events.emit("session_updated", session_id=session.session_id,
                payload={"session": state.chat_service.session_response(session)})
