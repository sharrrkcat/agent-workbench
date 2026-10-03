from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.api.schemas.common import error_responses
from ai_workbench.api.schemas.history import HistoryPage, HistoryUsersPage
from ai_workbench.core.history_page import HistoryQuery

router = APIRouter(prefix="/api/sessions/{session_id}/history", tags=["messages"])


def _page(state, session_id, query, users=False):
    try:
        state.sessions.get_session(session_id)
        return state.history_reader.page(session_id, query, users=users)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", "Session not found.")
    except ValueError:
        raise_error(422, "INVALID_HISTORY_CURSOR", "Invalid history cursor.")


@router.get("", response_model=HistoryPage, response_model_exclude_unset=True, responses=error_responses(404, 422))
def history(session_id: str, query: Annotated[HistoryQuery, Query()], state: RuntimeState = Depends(get_state)):
    return _page(state, session_id, query)


@router.get("/users", response_model=HistoryUsersPage, response_model_exclude_unset=True, responses=error_responses(404, 422))
def users(session_id: str, query: Annotated[HistoryQuery, Query()], state: RuntimeState = Depends(get_state)):
    return _page(state, session_id, query, users=True)
