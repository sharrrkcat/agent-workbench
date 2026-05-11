import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.worldbook import (
    Worldbook,
    WorldbookCreate,
    WorldbookEntry,
    WorldbookEntryCreate,
    WorldbookEntryPatch,
    WorldbookPatch,
    WorldbookSettingsPatch,
    content_preview,
    keyword_patterns,
)


router = APIRouter(prefix="/api", tags=["worldbook"])


class EntryReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_ids: list[str] = Field(min_length=1)


class SessionWorldbooksPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worldbook_ids: list[str]


class MatchTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    worldbook_ids: list[str] | None = None
    session_id: str | None = None


@router.get("/worldbook/settings")
def get_worldbook_settings(state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    return state.worldbooks.get_settings().model_dump()


@router.patch("/worldbook/settings")
def patch_worldbook_settings(payload: dict, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    try:
        patch = WorldbookSettingsPatch.model_validate(payload)
        return state.worldbooks.patch_settings(patch.model_dump(exclude_unset=True)).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)


@router.get("/worldbooks")
def list_worldbooks(state: RuntimeState = Depends(get_state)) -> list[dict]:
    _require_store(state)
    return [item.model_dump() for item in state.worldbooks.list_worldbooks()]


@router.post("/worldbooks")
def create_worldbook(payload: WorldbookCreate, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    try:
        return state.worldbooks.create_worldbook(Worldbook.model_validate(payload.model_dump())).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)


@router.get("/worldbooks/{worldbook_id}")
def get_worldbook(worldbook_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    try:
        return state.worldbooks.get_worldbook(worldbook_id).model_dump()
    except KeyError:
        raise_error(404, "WORLDBOOK_NOT_FOUND", f"Worldbook not found: {worldbook_id}")


@router.patch("/worldbooks/{worldbook_id}")
def patch_worldbook(worldbook_id: str, payload: WorldbookPatch, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    try:
        return state.worldbooks.update_worldbook(worldbook_id, payload.model_dump(exclude_unset=True)).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)
    except KeyError:
        raise_error(404, "WORLDBOOK_NOT_FOUND", f"Worldbook not found: {worldbook_id}")


@router.delete("/worldbooks/{worldbook_id}")
def delete_worldbook(worldbook_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    try:
        deleted = state.worldbooks.delete_worldbook(worldbook_id)
        return {"deleted": True, "worldbook_id": deleted.id}
    except KeyError:
        raise_error(404, "WORLDBOOK_NOT_FOUND", f"Worldbook not found: {worldbook_id}")


@router.get("/worldbooks/{worldbook_id}/entries")
def list_entries(worldbook_id: str, state: RuntimeState = Depends(get_state)) -> list[dict]:
    _require_store(state)
    try:
        return [item.model_dump() for item in state.worldbooks.list_entries(worldbook_id)]
    except KeyError:
        raise_error(404, "WORLDBOOK_NOT_FOUND", f"Worldbook not found: {worldbook_id}")


@router.post("/worldbooks/{worldbook_id}/entries")
def create_entry(worldbook_id: str, payload: WorldbookEntryCreate, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    try:
        data = payload.model_dump()
        if data.get("sort_order") is None:
            data["sort_order"] = (len(state.worldbooks.list_entries(worldbook_id)) + 1) * 10
        return state.worldbooks.create_entry(WorldbookEntry.model_validate({**data, "worldbook_id": worldbook_id})).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)
    except ValueError as exc:
        raise_error(422, "INVALID_WORLDBOOK_ENTRY", str(exc))
    except KeyError:
        raise_error(404, "WORLDBOOK_NOT_FOUND", f"Worldbook not found: {worldbook_id}")


@router.get("/worldbook-entries/{entry_id}")
def get_entry(entry_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    try:
        return state.worldbooks.get_entry(entry_id).model_dump()
    except KeyError:
        raise_error(404, "WORLDBOOK_ENTRY_NOT_FOUND", f"Worldbook entry not found: {entry_id}")


@router.patch("/worldbook-entries/{entry_id}")
def patch_entry(entry_id: str, payload: WorldbookEntryPatch, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    try:
        return state.worldbooks.update_entry(entry_id, payload.model_dump(exclude_unset=True)).model_dump()
    except ValidationError as exc:
        _raise_validation(exc)
    except ValueError as exc:
        raise_error(422, "INVALID_WORLDBOOK_ENTRY", str(exc))
    except KeyError:
        raise_error(404, "WORLDBOOK_ENTRY_NOT_FOUND", f"Worldbook entry not found: {entry_id}")


@router.delete("/worldbook-entries/{entry_id}")
def delete_entry(entry_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    try:
        deleted = state.worldbooks.delete_entry(entry_id)
        return {"deleted": True, "entry_id": deleted.id}
    except KeyError:
        raise_error(404, "WORLDBOOK_ENTRY_NOT_FOUND", f"Worldbook entry not found: {entry_id}")


@router.patch("/worldbooks/{worldbook_id}/entries/reorder")
def reorder_entries(worldbook_id: str, payload: EntryReorderRequest, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    try:
        entries = state.worldbooks.reorder_entries(worldbook_id, payload.entry_ids)
        return {"worldbook_id": worldbook_id, "entries": [entry.model_dump() for entry in entries]}
    except ValueError:
        raise_error(422, "WORLDBOOK_REORDER_IDS_MISMATCH", "Reorder ids must exactly match entries in this worldbook.")


@router.get("/sessions/{session_id}/worldbooks")
def get_session_worldbooks(session_id: str, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    _require_session(state, session_id)
    bindings = state.worldbooks.list_session_bindings(session_id)
    worldbooks = state.worldbooks.list_worldbooks()
    return {
        "session_id": session_id,
        "enabled_worldbooks": [binding.model_dump() for binding in bindings if binding.enabled and binding.worldbook and binding.worldbook.enabled],
        "available_worldbooks": [item.model_dump() for item in worldbooks],
    }


@router.patch("/sessions/{session_id}/worldbooks")
def patch_session_worldbooks(session_id: str, payload: SessionWorldbooksPatch, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    _require_session(state, session_id)
    try:
        bindings, warnings = state.worldbooks.replace_session_bindings(session_id, payload.worldbook_ids)
        return {"session_id": session_id, "enabled_worldbooks": [binding.model_dump() for binding in bindings], "available_worldbooks": [item.model_dump() for item in state.worldbooks.list_worldbooks()], "warnings": warnings}
    except KeyError as exc:
        raise_error(404, "WORLDBOOK_NOT_FOUND", str(exc))


@router.post("/worldbooks/match-test")
def match_test(payload: MatchTestRequest, state: RuntimeState = Depends(get_state)) -> dict:
    _require_store(state)
    settings = state.worldbooks.get_settings()
    warnings: list[dict] = []
    if payload.worldbook_ids is not None:
        worldbook_ids = _dedupe(payload.worldbook_ids)
    elif payload.session_id:
        _require_session(state, payload.session_id)
        worldbook_ids = [binding.worldbook_id for binding in state.worldbooks.list_session_bindings(payload.session_id) if binding.enabled and binding.worldbook and binding.worldbook.enabled]
    else:
        raise_error(422, "WORLDBOOK_MATCH_TARGET_REQUIRED", "worldbook_ids or session_id is required.")

    flags = re.IGNORECASE if settings.worldbook_regex_case_insensitive else 0
    matched: list[dict] = []
    matched_count = 0
    total_chars = 0
    truncated = False
    for worldbook_id in worldbook_ids:
        try:
            worldbook = state.worldbooks.get_worldbook(worldbook_id)
        except KeyError:
            raise_error(404, "WORLDBOOK_NOT_FOUND", f"Worldbook not found: {worldbook_id}")
        if not worldbook.enabled:
            warnings.append({"code": "WORLDBOOK_DISABLED", "message": f"Worldbook is disabled: {worldbook_id}", "worldbook_id": worldbook_id})
            continue
        for entry in state.worldbooks.list_entries(worldbook_id):
            if not entry.enabled:
                continue
            matched_keywords = _entry_matches(entry.activation_mode, entry.keywords_text, payload.text, flags, warnings, entry.id)
            if matched_keywords is None:
                continue
            matched_count += 1
            if len(matched) >= settings.worldbook_max_entries_per_call or total_chars + len(entry.content) > settings.worldbook_max_context_chars:
                truncated = True
                continue
            total_chars += len(entry.content)
            matched.append({
                "worldbook_id": worldbook.id,
                "worldbook_name": worldbook.name,
                "entry_id": entry.id,
                "entry_name": entry.name,
                "activation_mode": entry.activation_mode,
                "matched_keywords": matched_keywords,
                "sort_order": entry.sort_order,
                "content_preview": content_preview(entry.content),
            })
    return {"matched_count": matched_count, "included_count": len(matched), "truncated": truncated, "warnings": warnings, "results": matched}


def _entry_matches(mode: Literal["always", "keyword"], keywords_text: str, text: str, flags: int, warnings: list[dict], entry_id: str) -> list[str] | None:
    if mode == "always":
        return []
    patterns = keyword_patterns(keywords_text)
    if not patterns:
        warnings.append({"code": "WORLDBOOK_KEYWORDS_EMPTY", "message": "Keyword-triggered entry has no keywords.", "entry_id": entry_id})
        return None
    matches: list[str] = []
    for pattern in patterns:
        try:
            if re.search(pattern, text or "", flags):
                matches.append(pattern)
        except re.error as exc:
            warnings.append({"code": "WORLDBOOK_INVALID_REGEX", "message": f"Invalid regex: {exc}", "entry_id": entry_id, "pattern": pattern})
    return matches or None


def _require_store(state: RuntimeState) -> None:
    if state.worldbooks is None:
        raise_error(400, "WORLDBOOK_STORE_UNAVAILABLE", "Worldbook APIs require the SQLite store.")


def _require_session(state: RuntimeState, session_id: str) -> None:
    try:
        state.sessions.get_session(session_id)
    except KeyError:
        raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {session_id}")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _raise_validation(exc: ValidationError) -> None:
    error = exc.errors()[0] if exc.errors() else {}
    code = "UNKNOWN_WORLDBOOK_FIELD" if error.get("type") == "extra_forbidden" else "INVALID_WORLDBOOK_VALUE"
    loc = ".".join(str(item) for item in error.get("loc", []))
    message = f"{loc}: {error.get('msg', 'Invalid value')}" if loc else str(error.get("msg", "Invalid value"))
    raise_error(422, code, message)
