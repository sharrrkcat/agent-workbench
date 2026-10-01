"""Local protocol support from resolved resources and the resident worker."""
from dataclasses import dataclass, field
from typing import Literal

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import local_engine


@dataclass(frozen=True)
class Support:
    state: Literal["supported", "unsupported", "unknown"] = "unknown"
    reason: str | None = None


@dataclass(frozen=True)
class ChatSupport:
    tools: Support = field(default_factory=Support)
    vision: Support = field(default_factory=Support)


def local_chat_support(profile, adapter=None) -> ChatSupport:
    engine = local_engine(profile)
    if engine == "llama-server":
        return ChatSupport(vision=Support("unknown" if profile._directory.mmproj_ref else "unsupported",
                                         None if profile._directory.mmproj_ref else "missing_projector"))
    if engine == "transformers" and adapter is not None:
        tools, vision = adapter.tool_calls_supported, adapter.vision_supported
        return ChatSupport(
            tools=Support("supported" if tools else "unsupported", "tool_response_template"),
            vision=Support("supported" if vision else "unsupported", "image_processor"),
        )
    return ChatSupport()


def require_chat_support(profile, support: ChatSupport, *, tools: bool, vision: bool) -> None:
    options = profile.request_options
    if tools and not options.skip_tool_capability_check and support.tools.state == "unsupported":
        raise ModelError("UNSUPPORTED_CAPABILITY", "The local model has no supported tool response template.", 422)
    if vision and not options.skip_vision_capability_check and support.vision.state == "unsupported":
        raise ModelError("UNSUPPORTED_CAPABILITY", "The local model has no supported image input path.", 422)
