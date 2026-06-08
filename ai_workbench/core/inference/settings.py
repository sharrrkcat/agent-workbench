from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StatelessInferenceSettings:
    enabled: bool = False
    require_api_key: bool = True
    max_request_mb: int = 10
    api_key: str | None = None

    @property
    def max_request_bytes(self) -> int:
        return self.max_request_mb * 1024 * 1024


def resolve_inference_settings(app_settings_store: Any) -> StatelessInferenceSettings:
    settings = app_settings_store.get()
    return StatelessInferenceSettings(
        enabled=bool(getattr(settings, "inference_service_enabled", False)),
        require_api_key=bool(getattr(settings, "inference_service_require_api_key", True)),
        max_request_mb=int(getattr(settings, "inference_service_max_request_mb", 10)),
        api_key=getattr(settings, "inference_service_api_key", None) or None,
    )
