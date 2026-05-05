from fastapi import APIRouter, Depends, Query

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error


router = APIRouter(prefix="/api/commands", tags=["commands"])


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


@router.get("/detail")
def get_command(name: str = Query(...), state: RuntimeState = Depends(get_state)) -> dict:
    try:
        command = state.commands.get(name)
        return serialize_command(command, capability_enabled=state.capability_configs.is_enabled(command.capability_id))
    except KeyError:
        raise_error(404, "COMMAND_NOT_FOUND", f"Command not found: {name}")
