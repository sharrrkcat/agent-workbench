from typing import Annotated, Literal

from pydantic import Field, RootModel

from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp, JsonObject, patch_model, public_model
from ai_workbench.core.models.schema import (
    EmbeddingParameters, GenerationParameters, ImageEmbeddingParameters, ModelInput,
    ModelKind, ModelSettings, ProviderInput, ProviderProfile, RerankParameters, VisionParameters, TTSParameters,
)
from ai_workbench.core.models.runtimes.schema import (
    CatalogEntry, DownloadSettings, Installation, LlamaCPUOptions, LlamaCUDAOptions, LlamaOptions,
    PythonOptions, OnnxCPUOptions, RuntimeJob,
)


class EmptyRuntimeOptions(ApiModel):
    """No managed runtime is bound to this model."""


LlamaRuntimeOptions = EmptyRuntimeOptions | LlamaCPUOptions | LlamaCUDAOptions | LlamaOptions
WorkerRuntimeOptions = EmptyRuntimeOptions | PythonOptions
RuntimeOptions = LlamaRuntimeOptions | PythonOptions
Parameters = GenerationParameters | EmbeddingParameters | RerankParameters | ImageEmbeddingParameters | VisionParameters | TTSParameters
ModelFields = public_model("ModelFields", ModelInput, omit={"parameters", "runtime_options"})


class LlmModel(ModelFields):
    kind: Literal["llm"]
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)
    runtime_options: LlamaRuntimeOptions = Field(default_factory=EmptyRuntimeOptions,
        description="Managed options follow runtime_variant: cpu, cuda or vulkan. External profiles use {}.")


class EmbeddingModel(ModelFields):
    kind: Literal["embedding"]
    parameters: EmbeddingParameters = Field(default_factory=EmbeddingParameters)
    runtime_options: WorkerRuntimeOptions = Field(default_factory=EmptyRuntimeOptions)


class RerankerModel(ModelFields):
    kind: Literal["reranker"]
    parameters: RerankParameters = Field(default_factory=RerankParameters)
    runtime_options: WorkerRuntimeOptions = Field(default_factory=EmptyRuntimeOptions)


class ImageEmbeddingModel(ModelFields):
    kind: Literal["image_embedding"]
    parameters: ImageEmbeddingParameters = Field(default_factory=ImageEmbeddingParameters)
    runtime_options: WorkerRuntimeOptions = Field(default_factory=EmptyRuntimeOptions)


class VisionModel(ModelFields):
    kind: Literal["vision"]
    parameters: VisionParameters = Field(default_factory=VisionParameters)
    runtime_options: WorkerRuntimeOptions = Field(default_factory=EmptyRuntimeOptions)


class TTSModel(ModelFields):
    kind: Literal["tts"]
    parameters: TTSParameters = Field(default_factory=TTSParameters)
    runtime_options: EmptyRuntimeOptions | OnnxCPUOptions = Field(default_factory=EmptyRuntimeOptions)


class ModelCreate(RootModel[Annotated[LlmModel | EmbeddingModel | RerankerModel | ImageEmbeddingModel | VisionModel | TTSModel,
                                    Field(discriminator="kind")]]):
    """At most one backend binding; an unbound profile may be saved but cannot execute.

    Parameters and managed options must match kind and runtime variant.
    """


class ProfileIdentity(ApiModel):
    id: str
    created_at: ApiTimestamp
    updated_at: ApiTimestamp


class LlmProfile(LlmModel, ProfileIdentity):
    pass


class EmbeddingProfile(EmbeddingModel, ProfileIdentity):
    pass


class RerankerProfile(RerankerModel, ProfileIdentity):
    pass


class ImageEmbeddingProfile(ImageEmbeddingModel, ProfileIdentity):
    pass


class VisionProfile(VisionModel, ProfileIdentity):
    pass


class TTSProfile(TTSModel, ProfileIdentity):
    pass


ModelProfileResponse = Annotated[LlmProfile | EmbeddingProfile | RerankerProfile | ImageEmbeddingProfile | VisionProfile | TTSProfile,
                                 Field(discriminator="kind")]
ModelPatch = patch_model("ModelPatch", ModelInput, fields={
    "parameters": (Parameters, Field(default_factory=lambda: None, description="Replaces parameters; must match the saved model kind.")),
    "runtime_options": (RuntimeOptions, Field(default_factory=lambda: None, description="Replaces managed options; must match the resulting runtime binding.")),
})
ProviderPatch = patch_model("ProviderPatch", ProviderInput)
ModelSettingsPatch = patch_model("ModelSettingsPatch", ModelSettings)
DownloadSettingsPatch = patch_model("DownloadSettingsPatch", DownloadSettings)
ProviderResponse = public_model("ProviderResponse", ProviderProfile, omit={"api_key"}, fields={"has_api_key": (bool, ...)})
ModelSettingsResponse = public_model("ModelSettingsResponse", ModelSettings, omit={"external_api_key"},
                                   fields={"has_external_api_key": (bool, ...)})
InstallationResponse = public_model("InstallationResponse", Installation, omit={"manifest_sha256"})
RuntimeJobResponse = public_model("RuntimeJobResponse", RuntimeJob, omit={"log_path"})
CatalogEntryResponse = public_model("CatalogEntryResponse", CatalogEntry, fields={
    "options_schema": (JsonObject, Field(description="JSON Schema for the catalog entry's runtime options.")),
})


class ProviderModelsResponse(ApiModel):
    models: list[str]


class ModelInventoryItem(ApiModel):
    kind: ModelKind
    name: str
    model_ref: str
    state: Literal["unavailable"]
    error_code: Literal["MODEL_UNAVAILABLE"]
