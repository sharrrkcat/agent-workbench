"""Provider-independent web tool inputs, results and settings."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ai_workbench.core.network_policy import NetworkPolicy


NonblankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"\S")]
ApiKey = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[\x21-\x7E]*$")]


class WebModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class WebSearchArguments(WebModel):
    query: NonblankText


class WebSearchOptions(WebModel):
    max_results: int = Field(default=10, ge=1, le=10)
    zone: Literal["cn", "intl"] | None = None
    language: NonblankText | None = None


class WebSearchRequest(WebSearchOptions, WebSearchArguments):
    pass


class WebFetchArguments(WebModel):
    url: NonblankText = Field(pattern=r"^https?://", description="Public absolute HTTP or HTTPS URL, without credentials.")


class WebPage(WebModel):
    url: str
    title: str
    snippet: str | None = None
    content: str | None = None
    source_id: str | None = None

    @field_validator("url")
    @classmethod
    def public_url(cls, value: str) -> str:
        # The provider fetches the target and owns its DNS/redirect checks.
        return NetworkPolicy().validate_url(value, resolve_dns=False)


class WebSource(WebModel):
    source_id: str
    url: str
    title: str


class WebSearchResult(WebModel):
    provider: str
    query: str
    results: list[WebPage]
    request_id: str | None = None
    search_time_ms: float | None = None


class WebFetchResult(WebPage):
    provider: str
    content: str
    request_id: str | None = None


class WebToolsSettings(WebSearchOptions):
    provider: Literal["anysearch"] = "anysearch"
    api_key: ApiKey = ""


class WebToolsSettingsPatch(WebSearchOptions):
    api_key: ApiKey = Field(default="", description="Omission retains the key; an empty string clears it.",
                            json_schema_extra={"writeOnly": True})


class WebToolsSettingsResponse(WebSearchOptions):
    provider: Literal["anysearch"]
    has_api_key: bool
