"""Strict settings and subscription metadata; downloaded rules stay private."""
from datetime import datetime

from pydantic import Field, field_validator

from ai_workbench.core.network_policy import NetworkPolicy
from ai_workbench.core.web_filter_defaults import MAX_FILTER_BYTES
from ai_workbench.core.web_schemas import NonblankText, WebModel


class WebFilterIssue(WebModel):
    code: str
    message: str
    line: int | None = None


class WebSubscriptionCreate(WebModel):
    name: NonblankText = Field(max_length=160)
    url: NonblankText = Field(max_length=4096)

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        return NetworkPolicy().validate_url(value, resolve_dns=False)


class WebSubscriptionPatch(WebModel):
    enabled: bool


class WebFilterPatch(WebModel):
    custom_rules: str

    @field_validator("custom_rules")
    @classmethod
    def bounded_rules(cls, value):
        if len(value.encode("utf-8")) > MAX_FILTER_BYTES:
            raise ValueError("Custom rules exceed the 16 MiB limit")
        return value


class WebSubscriptionInfo(WebModel):
    id: str
    name: str
    url: str
    enabled: bool
    rule_count: int
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    error: WebFilterIssue | None


class WebFilterSettingsResponse(WebModel):
    custom_rules: str
    next_update_at: datetime | None
    subscriptions: list[WebSubscriptionInfo]

