from typing import Annotated, Literal

from pydantic import Field, RootModel

from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp, JsonObject, patch_model, public_model
from ai_workbench.core.models.schema import (
    EmbeddingParameters, GenerationParameters, ImageEmbeddingParameters, ModelInput,
    ModelKind, ModelSettings, BackendInput, BackendProfile, ExternalConnection, RerankParameters, VisionParameters, TTSParameters,
)
from ai_workbench.core.models.runtimes.schema import (
    DownloadSettings, Installation, LlamaCPUOptions, LlamaCUDAOptions,
    PythonOptions, OnnxCPUOptions, RuntimeJob, LocalEngine,
)


class EmptyExecutionOptions(ApiModel):
    """No managed runtime is bound to this model."""


LlmExecutionOptions = EmptyExecutionOptions | LlamaCPUOptions | LlamaCUDAOptions | PythonOptions
ExecutionOptions = LlmExecutionOptions | OnnxCPUOptions | PythonOptions
Parameters = GenerationParameters | EmbeddingParameters | RerankParameters | ImageEmbeddingParameters | VisionParameters | TTSParameters
ModelFields = public_model("ModelFields", ModelInput, omit={"parameters", "execution_options"})


class LlmModel(ModelFields):
    kind: Literal["llm"]
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)
    execution_options: LlmExecutionOptions = Field(default_factory=EmptyExecutionOptions,
        description="Local options follow the inferred engine and selected cpu/cuda device. External profiles use {}.")


class EmbeddingModel(ModelFields):
    kind: Literal["embedding"]
    parameters: EmbeddingParameters = Field(default_factory=EmbeddingParameters)
    execution_options: EmptyExecutionOptions = Field(default_factory=EmptyExecutionOptions)


class RerankerModel(ModelFields):
    kind: Literal["reranker"]
    parameters: RerankParameters = Field(default_factory=RerankParameters)
    execution_options: EmptyExecutionOptions = Field(default_factory=EmptyExecutionOptions)


class ImageEmbeddingModel(ModelFields):
    kind: Literal["image_embedding"]
    parameters: ImageEmbeddingParameters = Field(default_factory=ImageEmbeddingParameters)
    execution_options: EmptyExecutionOptions = Field(default_factory=EmptyExecutionOptions)


class VisionModel(ModelFields):
    kind: Literal["vision"]
    parameters: VisionParameters = Field(default_factory=VisionParameters)
    execution_options: EmptyExecutionOptions = Field(default_factory=EmptyExecutionOptions)


class TTSModel(ModelFields):
    kind: Literal["tts"]
    parameters: TTSParameters = Field(default_factory=TTSParameters)
    execution_options: EmptyExecutionOptions | PythonOptions | OnnxCPUOptions = Field(default_factory=EmptyExecutionOptions)


class ModelCreate(RootModel[Annotated[LlmModel | EmbeddingModel | RerankerModel | ImageEmbeddingModel | VisionModel | TTSModel,
                                    Field(discriminator="kind")]]):
    """At most one backend binding; an unbound profile may be saved but cannot execute.

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
    "execution_options": (ExecutionOptions, Field(default_factory=lambda: None, description="Replaces managed options; must match the resulting runtime binding.")),
})
ConnectionPatch = patch_model("ConnectionPatch", ExternalConnection)
DownloadSettingsPatch = patch_model("DownloadSettingsPatch", DownloadSettings)
BackendPatch = patch_model("BackendPatch", BackendInput, fields={
    "connection": (ConnectionPatch | None, Field(default_factory=lambda: None, description="Merge submitted connection fields; omitted api_key is retained.")),
    "download": (DownloadSettingsPatch | None, Field(default_factory=lambda: None, description="Merge submitted local download settings.")),
})
ModelSettingsPatch = patch_model("ModelSettingsPatch", ModelSettings)
ConnectionResponse = public_model("ConnectionResponse", ExternalConnection, omit={"api_key"}, fields={"has_api_key": (bool, ...)})
BackendResponse = public_model("BackendResponse", BackendProfile, fields={"connection": (ConnectionResponse | None, None)})
ModelSettingsResponse = public_model("ModelSettingsResponse", ModelSettings, omit={"external_api_key"},
                                   fields={"has_external_api_key": (bool, ...)})
InstallationResponse = public_model("InstallationResponse", Installation, omit={"manifest_sha256"})
RuntimeJobResponse = public_model("RuntimeJobResponse", RuntimeJob, omit={"log_path"})
class EngineCatalogResponse(ApiModel):
    engine: LocalEngine
    kind: Literal["llm", "tts"]
    options_schema: JsonObject = Field(description="JSON Schema for this code-owned local engine's execution options.")


class RuntimeCatalogResponse(ApiModel):
    version: str
    platform: str
    architecture: str
    supported: bool
    reason: str | None
    engines: list[EngineCatalogResponse]


class BackendModelsResponse(ApiModel):
    models: list[str]


class ModelInventoryItem(ApiModel):
    kind: ModelKind
    name: str
    model_ref: str
    state: Literal["unavailable"]
    error_code: Literal["MODEL_UNAVAILABLE"]
