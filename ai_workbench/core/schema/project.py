"""Project types share metadata, with distinct Workspace and Timeline settings."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, StrictBool, TypeAdapter, field_serializer, field_validator

from ai_workbench.core.models.schema import StrictModel, ImageGenerationControls
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.persona import USER_PERSONA_ID
from ai_workbench.core.session import ChatSettings
from ai_workbench.core.time import isoformat_utc, utc_now


class ProjectInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    context_policy: ContextPolicy
    model_profile_id: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Project name must not be empty")
        return value.strip()


class WorkspaceInput(ProjectInput):
    kind: Literal["workspace"]
    agent_persona_id: str
    cogita_persona_id: Literal[USER_PERSONA_ID]
    harness_enabled: StrictBool
    tools_allowed: list[str] = Field(max_length=128)
    system_prompt: str = Field(default="", max_length=100000)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("tools_allowed")
    @classmethod
    def unique_tools(cls, value: list[str]) -> list[str]:
        return ChatSettings.unique_tools(value)


class TimelineInput(ProjectInput):
    kind: Literal["timeline"]
    character_persona_id: str
    user_persona_id: str
    worldbook_ids: list[str] = Field(default_factory=list, max_length=128)


QQ_DEFAULT_PROMPT = (
    "Participate naturally in the current QQ conversation. Stay on the latest topic and reply briefly in the other "
    "participants' language. Usually finish in one message; add another only when necessary. Follow the selected "
    "persona when present; otherwise be friendly and natural. Avoid repetition, unrelated follow-ups and speaking for others. "
    "Prefer text with qq_send_message; most replies need no image. When qq_send_image is available, choose an asset_id "
    "from the favorite candidates for fitting emotional interaction. Tags are candidate data; a topic match alone is not "
    "a reason to send. Avoid routine illustrations and consecutive unsolicited images; use at most one image per reply. "
    "Use qq_generate_image only when available and explicitly asked to create a new picture, passing only a drawing prompt. "
    "Discussing animation, scenes, generating text, or declining images is not an image request. Each confirmed image uses "
    "one reply slot. Do not send duplicate links or delivery announcements. If an image fails before sending, you may reply with text."
)


class QQBotInput(ProjectInput):
    kind: Literal["qqbot"]
    bot_account: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    websocket_url: str = Field(max_length=2048)
    access_token: str = Field(default="", max_length=4096, repr=False)
    connection_enabled: StrictBool = False
    image_input_enabled: StrictBool = False
    image_description_model_profile_id: str | None = None
    image_generation_model_profile_id: str | None = None
    image_generation_options: ImageGenerationControls = Field(default_factory=ImageGenerationControls)
    agent_persona_id: str | None = None
    system_prompt: str = Field(default=QQ_DEFAULT_PROMPT, max_length=100000)
    reasoning: StrictBool = True
    group_reply_mode: Literal["keyword"] = "keyword"
    keywords: list[str] = Field(default_factory=list, max_length=128)
    batch_message_limit: int = Field(default=20, ge=1, le=200, strict=True)
    reply_message_limit: int = Field(default=4, ge=1, le=20, strict=True)
    icebreaker_enabled: StrictBool = False
    icebreaker_cold_seconds: int = Field(default=7200, ge=1, strict=True)
    icebreaker_wait_seconds: int = Field(default=120, ge=1, strict=True)
    icebreaker_cooldown_seconds: int = Field(default=10800, ge=1, strict=True)

    @field_validator("websocket_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use a ws/wss URL without credentials, query or fragment")
        if parsed.port == 0:
            raise ValueError("Use a valid WebSocket port")
        return value

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("Keywords must contain 1..200 characters")
        return list(dict.fromkeys(value.strip().casefold() for value in values))


ProjectCreate = Annotated[WorkspaceInput | TimelineInput | QQBotInput, Field(discriminator="kind")]


class ProjectMetadata(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime) -> str:
        return isoformat_utc(value) or ""


class WorkspaceProject(WorkspaceInput, ProjectMetadata):
    pass


class TimelineProject(TimelineInput, ProjectMetadata):
    pass


class QQBotProject(QQBotInput, ProjectMetadata):
    def public_response(self) -> dict:
        return {**self.model_dump(mode="json", exclude={"access_token"}), "has_access_token": bool(self.access_token)}


Project = Annotated[WorkspaceProject | TimelineProject | QQBotProject, Field(discriminator="kind")]
project_adapter = TypeAdapter(Project)
