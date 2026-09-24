from typing import Annotated, Literal

from pydantic import Field, RootModel

from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp, JsonObject, patch_model, public_model
from ai_workbench.core.models.schema import (
    EmbeddingParameters, GenerationParameters, ImageEmbeddingParameters, ModelInput,
    ModelKind, ModelSettings, ProviderInput, ProviderProfile, ProviderSource, Lifecycle, ExternalConnection, RerankParameters, VisionParameters, TTSParameters,
)
from ai_workbench.core.models.runtimes.schema import (
    DownloadSettings, Installation, LlamaCPUOptions, LlamaCUDAOptions,
    PythonOptions, OnnxCPUOptions, SiglipOptions, RuntimeJob, LocalEngine, LocalRuntimeSettings,
)


class EmptyExecutionOptions(ApiModel):
    """Local options are populated from the selected model's engine defaults."""


LlmExecutionOptions = EmptyExecutionOptions | LlamaCPUOptions | LlamaCUDAOptions | PythonOptions
ExecutionOptions = LlmExecutionOptions | OnnxCPUOptions | SiglipOptions
Parameters = GenerationParameters | EmbeddingParameters | RerankParameters | ImageEmbeddingParameters | VisionParameters | TTSParameters
ModelFields = public_model("ModelFields", ModelInput, omit={"parameters", "source"})


class LocalModelSource(ApiModel):
    type: Literal["local"]
    execution_options: ExecutionOptions = Field(default_factory=EmptyExecutionOptions)
    lifecycle: Lifecycle = Field(default_factory=Lifecycle)


class LocalLlmSource(LocalModelSource):
    execution_options: LlmExecutionOptions = Field(default_factory=EmptyExecutionOptions)


class LocalTTSSource(LocalModelSource):
    execution_options: EmptyExecutionOptions | PythonOptions | OnnxCPUOptions = Field(default_factory=EmptyExecutionOptions)


class LocalVisionSource(LocalModelSource):
    execution_options: EmptyExecutionOptions | OnnxCPUOptions = Field(default_factory=EmptyExecutionOptions)


class LocalImageEmbeddingSource(LocalModelSource):
    execution_options: EmptyExecutionOptions | SiglipOptions = Field(default_factory=EmptyExecutionOptions)


ModelSource = ProviderSource | LocalModelSource


class LlmModel(ModelFields):
    kind: Literal["llm"]
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)
    source: ProviderSource | LocalLlmSource | None = None


class EmbeddingModel(ModelFields):
    kind: Literal["embedding"]
    parameters: EmbeddingParameters = Field(default_factory=EmbeddingParameters)
    source: ProviderSource | None = None


class RerankerModel(ModelFields):
    kind: Literal["reranker"]
    parameters: RerankParameters = Field(default_factory=RerankParameters)
    source: None = None


class ImageEmbeddingModel(ModelFields):
    kind: Literal["image_embedding"]
    parameters: ImageEmbeddingParameters = Field(default_factory=ImageEmbeddingParameters)
    source: LocalImageEmbeddingSource | None = None


class VisionModel(ModelFields):
    kind: Literal["vision"]
    parameters: VisionParameters = Field(default_factory=VisionParameters)
    source: LocalVisionSource | None = None


class TTSModel(ModelFields):
    kind: Literal["tts"]
    parameters: TTSParameters = Field(default_factory=TTSParameters)
    source: LocalTTSSource | None = None


class ModelCreate(RootModel[Annotated[LlmModel | EmbeddingModel | RerankerModel | ImageEmbeddingModel | VisionModel | TTSModel,
                                    Field(discriminator="kind")]]):
    """One local/provider source or null; unbound profiles may be saved but cannot execute.

    Parameters and execution options must match the kind and local engine.
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
    "source": (ModelSource | None, Field(default_factory=lambda: None, description="Replaces the complete source. Omission retains it; null unbinds. Local defaults apply to omitted local options.")),
})
ConnectionPatch = patch_model("ConnectionPatch", ExternalConnection)
DownloadSettingsPatch = patch_model("DownloadSettingsPatch", DownloadSettings)
ProviderPatch = patch_model("ProviderPatch", ProviderInput, fields={
    "connection": (ConnectionPatch, Field(default_factory=lambda: None, description="Merge submitted connection fields; omitted api_key is retained.")),
})
LocalRuntimeSettingsPatch = patch_model("LocalRuntimeSettingsPatch", LocalRuntimeSettings, fields={
    "download": (DownloadSettingsPatch, Field(default_factory=lambda: None, description="Merge submitted download settings; null or empty URLs clear individual overrides.")),
})
ModelSettingsPatch = patch_model("ModelSettingsPatch", ModelSettings)
ConnectionResponse = public_model("ConnectionResponse", ExternalConnection, omit={"api_key"}, fields={"has_api_key": (bool, ...)})
ProviderResponse = public_model("ProviderResponse", ProviderProfile, fields={"connection": (ConnectionResponse, ...)})
ModelSettingsResponse = public_model("ModelSettingsResponse", ModelSettings, omit={"external_api_key"},
                                   fields={"has_external_api_key": (bool, ...)})
InstallationResponse = public_model("InstallationResponse", Installation, omit={"manifest_sha256"})
RuntimeJobResponse = public_model("RuntimeJobResponse", RuntimeJob, omit={"log_path"})
class EngineCatalogResponse(ApiModel):
    engine: LocalEngine
    kind: Literal["llm", "tts", "vision", "image_embedding"]
    options_schema: JsonObject = Field(description="JSON Schema for this code-owned local engine's execution options.")


class RuntimeCatalogResponse(ApiModel):
    version: str
    platform: str
    architecture: str
    supported: bool
    reason: str | None
    engines: list[EngineCatalogResponse]


class ProviderModelsResponse(ApiModel):
    models: list[str]


class ModelInventoryItem(ApiModel):
    kind: ModelKind
    name: str
    model_ref: str
    mmproj_refs: list[str] = Field(default_factory=list)
    state: Literal["unavailable"]
    error_code: Literal["MODEL_UNAVAILABLE"]
