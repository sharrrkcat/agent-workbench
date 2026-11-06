"""Separate administrative memory management from the Session recall view."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.schemas.common import DeletedResponse, error_responses
from ai_workbench.core.schema.memory import (
    MemoryEntry, MemoryCreate, MemoryEdit, MemoryRevision, MemoryPage, MemoryDeletionPreview,
)


router = APIRouter(tags=["memory"])
errors = error_responses(404, 409, 422)


class MemoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pool: Literal["character", "general"] | None = None
    character_id: str | None = None
    persona_id: str | None = None
    session_id: str | None = None
    origin_session_id: str | None = None
    status: Literal["active", "needs_review"] | None = None
    q: str = Field(default="", max_length=4000)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=20)


class SessionMemoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(default="", max_length=4000)
    own: bool = False
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=20)


@router.get("/api/memories", response_model=MemoryPage, responses=errors)
def list_memories(query: MemoryQuery = Query(), state: RuntimeState = Depends(get_state)):
    filters = query.model_dump(exclude={"q", "offset", "limit"}, exclude_none=True)
    return state.memory.list(filters=filters, query=query.q, offset=query.offset, limit=query.limit)


@router.post("/api/memories", response_model=MemoryEntry, responses=errors)
async def create_memory(payload: MemoryCreate, state: RuntimeState = Depends(get_state)):
    return state.memory.create(payload)


@router.get("/api/memories/{memory_id}", response_model=MemoryEntry, responses=errors)
def get_memory(memory_id: str, state: RuntimeState = Depends(get_state)):
    return state.memory.get(memory_id)


@router.patch("/api/memories/{memory_id}", response_model=MemoryEntry, responses=errors)
async def edit_memory(memory_id: str, payload: MemoryEdit, state: RuntimeState = Depends(get_state)):
    return state.memory.edit(memory_id, payload)


@router.delete("/api/memories/{memory_id}", response_model=DeletedResponse, responses=errors)
async def delete_memory(memory_id: str, payload: MemoryRevision, state: RuntimeState = Depends(get_state)):
    state.memory.delete(memory_id, payload.expected_revision)
    return {"deleted": True}


@router.post("/api/memories/{memory_id}/publish", response_model=MemoryEntry, responses=errors)
async def publish_memory(memory_id: str, payload: MemoryRevision, state: RuntimeState = Depends(get_state)):
    return state.memory.publish(memory_id, payload.expected_revision)


@router.get("/api/sessions/{session_id}/memories", response_model=MemoryPage, responses=errors)
def list_session_memories(session_id: str, query: SessionMemoryQuery = Query(), state: RuntimeState = Depends(get_state)):
    return state.memory.list(session_id=session_id, filters={"session_id": session_id} if query.own else None,
        query=query.q, offset=query.offset, limit=query.limit)


@router.get("/api/sessions/{session_id}/memories/{memory_id}", response_model=MemoryEntry, responses=errors)
def read_session_memory(session_id: str, memory_id: str, state: RuntimeState = Depends(get_state)):
    return state.memory.get(memory_id, session_id=session_id)


@router.get("/api/sessions/{session_id}/memory-deletion-preview", response_model=MemoryDeletionPreview, responses=errors)
def session_deletion_preview(session_id: str, state: RuntimeState = Depends(get_state)):
    return state.memory.deletion_preview(session_id=session_id)


@router.get("/api/characters/{character_id}/memory-deletion-preview", response_model=MemoryDeletionPreview, responses=errors)
def character_deletion_preview(character_id: str, state: RuntimeState = Depends(get_state)):
    return state.memory.deletion_preview(character_id=character_id)
