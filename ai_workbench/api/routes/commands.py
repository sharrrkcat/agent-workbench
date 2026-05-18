from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from capabilities.pet import PetError


router = APIRouter(prefix="/api/commands", tags=["commands"])


class CommandArgumentSuggestionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    args: list[str] = Field(default_factory=list)
    prefix: str = ""
    session_id: str | None = None

    @field_validator("args")
    @classmethod
    def args_must_be_strings(cls, value):
        if not all(isinstance(item, str) for item in value):
            raise ValueError("args must be an array of strings")
        return value


def serialize_command(command, capability_enabled: bool = True) -> dict:
    data = command.model_dump()
    data["capability_enabled"] = capability_enabled
    data["enabled"] = capability_enabled
    return data


@router.get("")
def list_commands(state: RuntimeState = Depends(get_state)) -> list:
    return [
        serialize_command(command, capability_enabled=state.capability_configs.is_enabled(command.capability_id))
        for command in state.commands.list()
    ]


@router.post("/argument-suggestions")
def get_argument_suggestions(
    payload: CommandArgumentSuggestionsRequest,
    state: RuntimeState = Depends(get_state),
) -> dict:
    try:
        command = state.commands.get(payload.command)
    except KeyError:
        return {"suggestions": []}

    provider = _next_suggestions_provider(command, payload.args)
    if provider is None:
        return {"suggestions": []}
    if provider == "pet_ids":
        return {"suggestions": _pet_id_suggestions(state, payload.prefix)}
    return {"suggestions": []}


@router.get("/detail")
def get_command(name: str = Query(...), state: RuntimeState = Depends(get_state)) -> dict:
    try:
        command = state.commands.get(name)
        return serialize_command(command, capability_enabled=state.capability_configs.is_enabled(command.capability_id))
    except KeyError:
        raise_error(404, "COMMAND_NOT_FOUND", f"Command not found: {name}")


def _next_suggestions_provider(command: Any, args: list[str]) -> str | None:
    if len(args) != 1:
        return None
    first_arg = args[0]
    for suggestion in command.argument_suggestions:
        if suggestion.value != first_arg:
            continue
        next_suggestions = suggestion.next_suggestions
        return next_suggestions.provider if next_suggestions else None
    return None


def _pet_id_suggestions(state: RuntimeState, prefix: str) -> list[dict[str, str]]:
    try:
        pets = state.runtimes.get_runtime("pet").list_pets(context=_pet_context(state)).get("pets", [])
    except (KeyError, PetError, OSError, ValueError):
        return []

    normalized_prefix = prefix.lower()
    suggestions: list[dict[str, str]] = []
    for pet in pets:
        if not pet.get("valid"):
            continue
        pet_id = str(pet.get("id") or "")
        if not pet_id:
            continue
        display_name = str(pet.get("display_name") or pet_id)
        if normalized_prefix and not (
            pet_id.lower().startswith(normalized_prefix)
            or display_name.lower().startswith(normalized_prefix)
        ):
            continue
        suggestions.append(
            {
                "value": pet_id,
                "label": display_name,
                "description": f"Select and wake {display_name}",
            }
        )
    suggestions.sort(key=lambda item: (item["label"].lower(), item["value"].lower()))
    return suggestions[:20]


def _pet_context(state: RuntimeState) -> dict:
    capability = state.capabilities.get("pet")
    stored = state.capability_configs.get_config("pet")
    return {
        "repo_root": Path(state.repo_root).resolve(),
        "capability_config": stored.get("user_config", {}),
        "capability_config_store": state.capability_configs,
        "config_schema": capability.config_schema,
    }
