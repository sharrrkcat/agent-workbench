from typing import Dict, Iterable, List

from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.schema.capability import CapabilitySchema
from ai_workbench.core.schema.command import CommandRegistration


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: Dict[str, CommandRegistration] = {}

    @classmethod
    def from_capability_registry(cls, capability_registry: CapabilityRegistry) -> "CommandRegistry":
        registry = cls()
        registry.register_capabilities(capability_registry.list())
        return registry

    def register_capabilities(self, capabilities: Iterable[CapabilitySchema]) -> None:
        for capability in capabilities:
            self.register_capability(capability)

    def register_capability(self, capability: CapabilitySchema) -> None:
        for command in capability.commands:
            self.register(
                CommandRegistration(
                    name=command.name,
                    capability_id=capability.id,
                    method=command.method,
                    description=command.description,
                    safe=command.safe,
                    confirm=command.confirm,
                    argument_suggestions=command.argument_suggestions,
                )
            )

    def register(self, command: CommandRegistration) -> None:
        if command.name in self._commands:
            existing = self._commands[command.name]
            raise ValueError(
                "duplicate command name: "
                f"{command.name} from {command.capability_id}.{command.method}; "
                f"already registered by {existing.capability_id}.{existing.method}"
            )
        self._commands[command.name] = command

    def get(self, name: str) -> CommandRegistration:
        try:
            return self._commands[name]
        except KeyError as exc:
            raise KeyError(f"unknown command name: {name}") from exc

    def list(self) -> List[CommandRegistration]:
        return list(self._commands.values())
