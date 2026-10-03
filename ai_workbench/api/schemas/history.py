"""Bounded conversation and event read responses."""
from typing import Annotated, Literal
from pydantic import Field

from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp
from ai_workbench.api.schemas.chat import MessageResponse, RunResponse, RunEventResponse


class HistoryIdentity(ApiModel):
    id: str
    number: int = Field(ge=1)
    cursor: str
    created_at: ApiTimestamp


class HistoryMessage(HistoryIdentity):
    kind: Literal["message"]
    message: MessageResponse


class HistoryReply(HistoryIdentity):
    kind: Literal["reply"]
    run: RunResponse
    messages: list[MessageResponse]


class HistoryUser(HistoryIdentity):
    kind: Literal["user"]
    summary: str


class HistoryPageInfo(ApiModel):
    before_cursor: str | None
    after_cursor: str | None
    has_before: bool
    has_after: bool
    history_version: int
    active_run: RunResponse | None


class HistoryPage(HistoryPageInfo):
    items: list[Annotated[HistoryMessage | HistoryReply, Field(discriminator="kind")]]


class HistoryUsersPage(HistoryPageInfo):
    items: list[HistoryUser]


class RunEventsPage(ApiModel):
    items: list[RunEventResponse]
    next_cursor: str | None
    has_more: bool
