"""Local protocol support from resolved resources and the resident worker."""
from dataclasses import dataclass, field
from typing import Literal

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import local_engine
from ai_workbench.workers.reasoning import skip_reasoning_check


@dataclass(frozen=True)
class Support:
    state: Literal["supported", "unsupported", "unknown"] = "unknown"
    reason: str | None = None


@dataclass(frozen=True)
class ChatSupport:
    tools: Support = field(default_factory=Support)
    vision: Support = field(default_factory=Support)
    instant: Support = field(default_factory=Support)
    reasoning: Support = field(default_factory=Support)


def local_chat_support(profile, adapter=None) -> ChatSupport:
    engine = local_engine(profile)
    modes = {key: Support(value, "chat_template") for key, value in adapter.reasoning_support.items()} if adapter is not None else {}
    if engine == "llama-server":
        return ChatSupport(vision=Support("unknown" if profile._directory.mmproj_ref else "unsupported",
                                         None if profile._directory.mmproj_ref else "missing_projector"), **modes)
    if engine == "transformers" and adapter is not None:
        tools, vision = adapter.tool_calls_supported, adapter.vision_supported
        return ChatSupport(
            tools=Support("supported" if tools else "unsupported", "tool_response_template"),
            vision=Support("supported" if vision else "unsupported", "image_processor"),
            **modes,
        )
    return ChatSupport()


def skips_reasoning(profile, reasoning: bool) -> bool:
    options = profile.request_options
    return skip_reasoning_check(reasoning, options.skip_instant_capability_check, options.skip_reasoning_capability_check)


def chat_reasoning_mode(profile, support: ChatSupport, requested: bool) -> bool:
    if not skips_reasoning(profile, requested):
        selected, alternative = (support.reasoning, support.instant) if requested else (support.instant, support.reasoning)
        if selected.state == "unsupported" and alternative.state == "supported":
            return not requested
    return requested


def require_chat_support(profile, support: ChatSupport, *, tools: bool, vision: bool, reasoning: bool | None = None) -> None:
    options = profile.request_options
    if tools and not options.skip_tool_capability_check and support.tools.state == "unsupported":
        raise ModelError("UNSUPPORTED_CAPABILITY", "The local model has no supported tool response template.", 422)
    if vision and not options.skip_vision_capability_check and support.vision.state == "unsupported":
        raise ModelError("UNSUPPORTED_CAPABILITY", "The local model has no supported image input path.", 422)
    if reasoning is not None and not skips_reasoning(profile, reasoning):
        mode = support.reasoning if reasoning else support.instant
        if mode.state == "unsupported":
            raise ModelError("UNSUPPORTED_CAPABILITY", f"The local model does not support {'reasoning' if reasoning else 'instant'} mode.", 422)
