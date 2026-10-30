"""Provider-independent web tool inputs, results and settings."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ai_workbench.core.network_policy import NetworkPolicy


NonblankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"\S")]
ApiKey = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[\x21-\x7E]*$")]


class WebModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class WebSearchQuery(WebModel):
    query: NonblankText
    recency: Literal["any", "week", "month", "year"] = "any"


class WebSearchArguments(WebModel):
    searches: list[WebSearchQuery] = Field(min_length=1, max_length=4)


class WebSearchOptions(WebModel):
    max_results: int = Field(default=5, ge=1, le=10)
    zone: Literal["cn", "intl"] | None = None
    language: NonblankText | None = None


class WebSearchRequest(WebSearchOptions):
    query: NonblankText


class WebFetchArguments(WebModel):
    url: NonblankText = Field(pattern=r"^https?://", description="Public absolute HTTP or HTTPS URL, without credentials.")
    focus: NonblankText | None = Field(default=None, description="Specific information to find, not a request to summarize.")
    page: int = Field(default=1, ge=1)


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


class ProviderSearchResult(WebModel):
    provider: str
    query: str
    results: list[WebPage]
    request_id: str | None = None
    search_time_ms: float | None = None


class ProviderFetchResult(WebPage):
    provider: str
    content: str
    request_id: str | None = None


class WebLimits(WebModel):
    search_calls_per_run: int = Field(default=4, ge=1, le=16)
    fetch_calls_per_run: int = Field(default=6, ge=1, le=16)
    cache_ttl_hours: int = Field(default=24, ge=1, le=168)
    cache_retention_days: int = Field(default=30, ge=1, le=365)


class WebRunBudget(WebModel):
    search_limit: int = Field(default=4, ge=1, le=16)
    fetch_limit: int = Field(default=6, ge=1, le=16)
    searches_used: int = Field(default=0, ge=0)
    fetches_used: int = Field(default=0, ge=0)
    searched_queries: list[str] = Field(default_factory=list)

    def remaining(self) -> dict[str, int]:
        return {"search": max(0, self.search_limit - self.searches_used),
                "fetch": max(0, self.fetch_limit - self.fetches_used)}


class WebDate(WebModel):
    value: str | None = None
    precision: Literal["day", "month"] | None = None
    source: Literal["url", "content"] | None = None
    uncertain: bool = False


class WebLink(WebModel):
    text: str
    url: str
    offset: int = 0


class WebSearchStatus(WebSearchQuery):
    status: Literal["success", "error", "duplicate"]
    error_code: str | None = None
    request_id: str | None = None
    http_status: int | None = None
    search_time_ms: float | None = None


class WebSearchStats(WebModel):
    candidates: int = 0
    source_chars: int = 0
    duplicates: int = 0
    expired: int = 0
    unrelated: int = 0
    omitted: int = 0


class WebSearchPage(WebModel):
    url: str
    title: str
    source_id: str | None = None
    content: str
    content_chars: int
    content_limited: bool
    matched_queries: list[int]
    date: WebDate


class WebSearchResult(WebModel):
    searches: list[WebSearchStatus]
    results: list[WebSearchPage]
    stats: WebSearchStats
    retrieved_at: str
    remaining: dict[str, int]
    truncated: bool = False


class WebFetchResult(WebModel):
    url: str
    title: str
    source_id: str | None = None
    content: str
    content_chars: int
    content_hash: str
    date: WebDate
    links: list[WebLink]
    page: int
    total_pages: int
    order: Literal["document", "relevance"]
    cache_hit: bool
    cached_at: str
    retrieved_at: str
    remaining: dict[str, int]
    notice: Literal["no_more_content", "no_focus_match"] | None = None
    truncated: bool = False
    request_id: str | None = None


class WebToolsSettings(WebSearchOptions, WebLimits):
    provider: Literal["anysearch"] = "anysearch"
    api_key: ApiKey = ""


class WebToolsSettingsPatch(WebSearchOptions, WebLimits):
    api_key: ApiKey = Field(default="", description="Omission retains the key; an empty string clears it.",
                            json_schema_extra={"writeOnly": True})


class WebToolsSettingsResponse(WebSearchOptions, WebLimits):
    provider: Literal["anysearch"]
    has_api_key: bool
