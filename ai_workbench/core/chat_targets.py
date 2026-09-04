"""Static prompt targets used by the Phase 1 chat path."""

from __future__ import annotations

from typing import Any

from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.prompt_target import PromptTarget


class ChatTargetCatalog:
    """An explicit, non-extensible catalog.

    ``translate`` is intentionally internal: it is useful in unit tests and
    for future persona seeding, but there is no public target/agent API.
    """

    def __init__(self, targets: list[PromptTarget] | None = None) -> None:
        defaults = targets or [
            PromptTarget(
                id="chat",
                name="Chat",
                system_prompt="You are a helpful assistant.",
                context_policy=ContextPolicy(mode="session"),
                public=True,
            ),
            PromptTarget(
                id="translate",
                name="Translate",
                system_prompt="Translate the user's text accurately. Return only the translation.",
                context_policy=ContextPolicy(mode="current_message"),
                public=False,
            ),
        ]
        self._targets = {target.id: target for target in defaults}
        if "chat" not in self._targets:
            raise ValueError("ChatTargetCatalog requires chat target")

    def get(self, target_id: str) -> PromptTarget:
        try:
            return self._targets[target_id]
        except KeyError as exc:
            raise KeyError(f"unknown prompt target: {target_id}") from exc

    def list(self, *, public_only: bool = False) -> list[PromptTarget]:
        values = list(self._targets.values())
        if public_only:
            values = [target for target in values if target.public]
        return values

    def ids(self, *, public_only: bool = False) -> tuple[str, ...]:
        """Return stable target ids for diagnostics and tests."""
        return tuple(target.id for target in self.list(public_only=public_only))

    @property
    def default(self) -> PromptTarget:
        return self._targets["chat"]


# Friendly aliases for callers that use the core naming convention.
ChatTarget = PromptTarget

__all__ = ["PromptTarget", "ChatTarget", "ChatTargetCatalog"]
