from __future__ import annotations

from typing import Any

from ai_workbench.core.image_generation.generation import ImageGenerationService


class CapabilityRuntime:
    def __init__(self, service: ImageGenerationService | None = None) -> None:
        self.service = service or ImageGenerationService()

    def configure(
        self,
        service: ImageGenerationService | None = None,
        profile_store: Any = None,
        repo_root: Any = None,
    ) -> None:
        if service is not None:
            self.service = service
            return
        self.service.configure(profile_store=profile_store, repo_root=repo_root)

    def status(self, context: dict | None = None) -> dict:
        return self.service.status()

    def list_model_profiles(self, enabled_only: bool = False, context: dict | None = None) -> list[dict]:
        return self.service.list_model_profiles(enabled_only=enabled_only)

    def validate_txt2img(self, request: dict | None = None, context: dict | None = None, **kwargs: Any) -> dict:
        return self.service.validate_txt2img(request, **kwargs)

    async def txt2img(self, request: dict | None = None, context: dict | None = None, **kwargs: Any) -> dict:
        return await self.service.txt2img(request, context=context, **kwargs)

    def queue_status(self, context: dict | None = None) -> dict:
        return self.service.queue_status()

    def cancel(
        self,
        request_id: str | None = None,
        run_id: str | None = None,
        context: dict | None = None,
    ) -> dict:
        return self.service.cancel(request_id=request_id, run_id=run_id)

    def unload(self, profile_id_or_alias: str | None = None, context: dict | None = None) -> dict:
        return self.service.unload(profile_id_or_alias=profile_id_or_alias)


def get_runtime() -> CapabilityRuntime:
    return CapabilityRuntime()
