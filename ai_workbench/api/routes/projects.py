from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.openapi import request_body
from ai_workbench.api.routes.personas import KnowledgeBindingsPatch, WorldbookBindingsPatch
from ai_workbench.api.routes.sessions import delete_session_data
from ai_workbench.api.schemas.chat import KnowledgeBindingsResponse, WorldbookBindingsResponse, SessionResponse
from ai_workbench.api.schemas.common import error_responses
from ai_workbench.api.schemas.projects import (
    ProjectDeleted, ProjectResponse, ProjectPatchRequest, WorkspaceSessionCreate,
    WorkspaceProjectPatch, TimelineProjectPatch,
)
from ai_workbench.core.schema.project import ProjectCreate


router = APIRouter(prefix="/api/projects", tags=["projects"])


def _notify_sessions(state: RuntimeState, project_id: str) -> None:
    for session in state.sessions.list_sessions():
        if session.project_id == project_id:
            state.events.emit("session_updated", session_id=session.session_id,
                              payload={"session": state.chat_service.session_response(session)})


@router.get("", response_model=list[ProjectResponse], response_model_exclude_unset=True)
def list_projects(state: RuntimeState = Depends(get_state)):
    return [project.model_dump(mode="json") for project in state.projects.list()]


@router.post("", response_model=ProjectResponse, response_model_exclude_unset=True, responses=error_responses(400, 404, 422, 503))
async def create_project(payload: ProjectCreate, state: RuntimeState = Depends(get_state)):
    return state.project_service.create(payload).model_dump(mode="json")


@router.get("/{project_id}", response_model=ProjectResponse, response_model_exclude_unset=True, responses=error_responses(404))
def get_project(project_id: str, state: RuntimeState = Depends(get_state)):
    return state.project_service.get(project_id).model_dump(mode="json")


@router.patch("/{project_id}", response_model=ProjectResponse, response_model_exclude_unset=True,
              responses=error_responses(400, 404, 422, 503), openapi_extra=request_body(ProjectPatchRequest,
              description="Merge submitted settings for this Project type. Type and identity are immutable; null model/temperature inherits defaults."))
async def update_project(project_id: str, payload: dict, state: RuntimeState = Depends(get_state)):
    project = state.project_service.get(project_id)
    schema = WorkspaceProjectPatch if project.kind == "workspace" else TimelineProjectPatch
    values = schema.model_validate(payload).model_dump(exclude_unset=True)
    updated = state.project_service.update(project_id, values)
    _notify_sessions(state, project_id)
    return updated.model_dump(mode="json")


@router.delete("/{project_id}", response_model=ProjectDeleted, responses=error_responses(404, 409))
async def delete_project(project_id: str, state: RuntimeState = Depends(get_state)):
    state.project_service.assert_idle(project_id)
    ids = [session.session_id for session in state.sessions.list_sessions() if session.project_id == project_id]
    for session_id in ids:
        delete_session_data(state, session_id)
    state.projects.delete(project_id)
    return {"deleted": True, "project_id": project_id, "deleted_session_ids": ids}


@router.get("/{project_id}/knowledge-bases", response_model=KnowledgeBindingsResponse, responses=error_responses(404, 422))
def get_project_knowledge(project_id: str, state: RuntimeState = Depends(get_state)):
    return {"knowledge_base_ids": state.project_service.for_resource(project_id, "knowledge").knowledge_base_ids}


@router.patch("/{project_id}/knowledge-bases", response_model=KnowledgeBindingsResponse, responses=error_responses(400, 404, 422))
async def update_project_knowledge(project_id: str, payload: KnowledgeBindingsPatch, state: RuntimeState = Depends(get_state)):
    state.project_service.for_resource(project_id, "knowledge")
    updated = state.project_service.update(project_id, payload.model_dump())
    _notify_sessions(state, project_id)
    return {"knowledge_base_ids": updated.knowledge_base_ids}


@router.get("/{project_id}/worldbooks", response_model=WorldbookBindingsResponse, responses=error_responses(404, 422))
def get_project_worldbooks(project_id: str, state: RuntimeState = Depends(get_state)):
    return {"worldbook_ids": state.project_service.for_resource(project_id, "worldbook").worldbook_ids}


@router.patch("/{project_id}/worldbooks", response_model=WorldbookBindingsResponse, responses=error_responses(400, 404, 422))
async def update_project_worldbooks(project_id: str, payload: WorldbookBindingsPatch, state: RuntimeState = Depends(get_state)):
    state.project_service.for_resource(project_id, "worldbook")
    return {"worldbook_ids": state.project_service.update(project_id, payload.model_dump()).worldbook_ids}


@router.get("/{project_id}/sessions", response_model=list[SessionResponse], response_model_exclude_unset=True, responses=error_responses(404, 409))
def list_project_sessions(project_id: str, state: RuntimeState = Depends(get_state)):
    return [state.chat_service.session_response(session) for session in state.project_service.sessions(project_id)]


@router.post("/{project_id}/sessions", response_model=SessionResponse, response_model_exclude_unset=True, responses=error_responses(400, 404, 409, 422, 503))
async def create_project_session(project_id: str, payload: WorkspaceSessionCreate, state: RuntimeState = Depends(get_state)):
    session = state.chat_service.create_workspace_session(project_id, payload.model_dump(exclude_unset=True))
    return state.chat_service.session_response(session)
