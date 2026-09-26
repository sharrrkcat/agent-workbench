"""Lightweight directory information, independent of runtime installation and loading."""
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import StrictModel
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers.siglip_catalog import CONFIG_FILES, STRUCTURES, model_directory, model_file, read_config
from ai_workbench.workers.embedding_catalog import inspect_embedding
from ai_workbench.workers.reranker_catalog import inspect_reranker as inspect_reranker_directory
from ai_workbench.workers.asr_catalog import inspect_asr as inspect_asr_directory
from ai_workbench.workers.model_catalog import inspect_directory

PositiveInt = Annotated[int, Field(gt=0, strict=True)]
Number = Annotated[float, Field(strict=True)]


class InspectionDiagnostic(StrictModel):
    file: str
    code: Literal["missing_config", "invalid_config", "invalid_field", "unknown_structure"]
    message: str


class SiglipProcessorInfo(StrictModel):
    image_processor_type: str | None = None
    do_resize: bool | None = None
    size: PositiveInt | dict[str, PositiveInt] | None = None
    resample: int | None = None
    do_rescale: bool | None = None
    rescale_factor: Number | None = None
    do_normalize: bool | None = None
    image_mean: list[Number] | Number | None = None
    image_std: list[Number] | Number | None = None
    do_convert_rgb: bool | None = None
    patch_size: PositiveInt | None = None
    max_num_patches: PositiveInt | None = None


class SiglipImageInfo(StrictModel):
    dimensions: PositiveInt | None = None
    image_size: PositiveInt | None = None
    patch_size: PositiveInt | None = None


class SiglipTextInfo(StrictModel):
    dimensions: PositiveInt | None = None
    hidden_size: PositiveInt | None = None
    max_position_embeddings: PositiveInt | None = None
    tokenizer_class: str | None = None
    tokenizer_max_length: PositiveInt | None = None
    do_lower_case: bool | None = None
    add_bos_token: bool | None = None
    add_eos_token: bool | None = None


class SiglipInspection(StrictModel):
    kind: Literal["image_embedding"] = "image_embedding"
    model_ref: str
    model_type: str | None
    structure: Literal["fixres", "naflex"] | None
    image: SiglipImageInfo
    text: SiglipTextInfo
    processor: SiglipProcessorInfo
    diagnostics: list[InspectionDiagnostic]


class TextEmbeddingDiagnostic(StrictModel):
    file: str
    code: Literal["missing_config", "invalid_config", "invalid_field", "unsupported_configuration",
                  "invalid_prompt", "ambiguous_prompt", "missing_pipeline", "remote_code",
                  "missing_token_limit", "missing_pooling"]
    message: str
    blocking: bool


class TextEmbeddingModule(StrictModel):
    name: str
    path: str
    type: str


class TextEmbeddingPooling(StrictModel):
    module: str
    modes: list[str]
    include_prompt: bool | None


class TextEmbeddingInspection(StrictModel):
    kind: Literal["embedding"] = "embedding"
    model_ref: str
    model_type: str | None
    modules: list[TextEmbeddingModule]
    pooling: list[TextEmbeddingPooling]
    normalize: bool | None
    dimensions: PositiveInt | None
    max_seq_length: PositiveInt | None
    similarity: Literal["cosine", "dot"] | None
    prompts: dict[str, str]
    query_prompt_name: str | None
    document_prompt_name: str | None
    diagnostics: list[TextEmbeddingDiagnostic]


class RerankerDiagnostic(StrictModel):
    file: str
    code: Literal["missing_config", "invalid_config", "invalid_field", "unsupported_configuration",
                  "remote_code", "missing_scoring", "missing_template", "missing_token_limit"]
    message: str
    blocking: bool


class RerankerScoring(StrictModel):
    method: Literal["sequence_classification", "logit_score", "dense"] | None
    activation: str | None


class RerankerInspection(StrictModel):
    kind: Literal["reranker"] = "reranker"
    model_ref: str
    architecture: Literal["cross-encoder"] | None
    model_type: str | None
    modules: list[TextEmbeddingModule]
    scoring: RerankerScoring
    max_seq_length: PositiveInt | None
    has_chat_template: bool
    default_prompt_name: str | None
    diagnostics: list[RerankerDiagnostic]


class ASRDiagnostic(StrictModel):
    file: str
    code: Literal["missing_config", "invalid_config", "invalid_field", "unsupported_configuration", "remote_code"]
    message: str
    blocking: bool


class ASRInspection(StrictModel):
    kind: Literal["asr"] = "asr"
    model_ref: str
    architecture: Literal["whisper"] | None
    processor: str | None
    sample_rate: PositiveInt | None
    feature_size: PositiveInt | None
    window_seconds: PositiveInt | None
    multilingual: bool | None
    languages: list[str]
    segment_timestamps: bool
    diagnostics: list[ASRDiagnostic]


class DirectoryDiagnostic(StrictModel):
    file: str
    code: Literal["missing_directory", "missing_file", "invalid_config", "unsupported_configuration",
                  "ambiguous_model", "ambiguous_projector", "incomplete_shards"]
    message: str
    blocking: bool


class LLMInspection(StrictModel):
    kind: Literal["llm"] = "llm"
    model_ref: str
    engine: Literal["llama-server", "transformers"] | None
    architecture: str | None
    main_model_ref: str | None
    mmproj_ref: str | None
    model_files: list[str]
    diagnostics: list[DirectoryDiagnostic]


class TTSInspection(StrictModel):
    kind: Literal["tts"] = "tts"
    model_ref: str
    engine: Literal["kokoro", "chatterbox", "qwen3tts"] | None
    architecture: Literal["kokoro", "chatterbox", "qwen3tts"] | None
    diagnostics: list[DirectoryDiagnostic]


class VisionInspection(StrictModel):
    kind: Literal["vision"] = "vision"
    model_ref: str
    engine: Literal["wd14"] | None
    architecture: Literal["wd14"] | None
    backbone: str | None
    diagnostics: list[DirectoryDiagnostic]


class ProcessorInspection(StrictModel):
    kind: Literal["processor"] = "processor"
    model_ref: str
    engine: Literal["dlss5nr"] = "dlss5nr"
    task: Literal["image_processing"] = "image_processing"
    diagnostics: list[DirectoryDiagnostic]


ModelInspection = Annotated[SiglipInspection | TextEmbeddingInspection | RerankerInspection | ASRInspection
                           | LLMInspection | TTSInspection | VisionInspection | ProcessorInspection, Field(discriminator="kind")]


def inspect_processor(repo_root: Path, model_ref: str) -> ProcessorInspection:
    from ai_workbench.core.models.processing import processor_resource
    try:
        processor_resource(repo_root, model_ref)
    except ValueError as exc:
        raise ModelError("INVALID_REQUEST", "Use a safe relative path under data/models.", 422) from exc
    except ModelError as exc:
        if exc.code != "MODEL_NOT_FOUND":
            raise
        return ProcessorInspection(model_ref=model_ref, diagnostics=[DirectoryDiagnostic(
            file="nvngx_dlssnr.dll", code="missing_file", message=exc.message, blocking=True)])
    return ProcessorInspection(model_ref=model_ref, diagnostics=[])


def inspect_local_directory(repo_root: Path, kind: str, model_ref: str):
    try:
        info = inspect_directory(repo_root / "data/models", kind, model_ref)
    except WorkerError as exc:
        raise ModelError(exc.code, "Use a model directory with a safe relative path under data/models.", exc.status) from exc
    if any(item["code"] == "missing_directory" for item in info.diagnostics):
        raise ModelError("MODEL_NOT_FOUND", "The model directory does not exist.", 404)
    values = dict(model_ref=model_ref, engine=info.engine, architecture=info.architecture, diagnostics=info.diagnostics)
    if kind == "llm":
        return LLMInspection(**values, main_model_ref=info.main_model_ref, mmproj_ref=info.mmproj_ref, model_files=info.model_files)
    if kind == "vision":
        return VisionInspection(**{**values, "architecture": info.engine}, backbone=info.architecture)
    return TTSInspection(**values)


def inspect_asr(repo_root: Path, model_ref: str) -> ASRInspection:
    try:
        return ASRInspection.model_validate(inspect_asr_directory(repo_root / "data/models", model_ref))
    except WorkerError as exc:
        raise ModelError(exc.code, "Use an existing directory with a safe relative path under data/models.", exc.status) from exc


def inspect_reranker(repo_root: Path, model_ref: str) -> RerankerInspection:
    try:
        return RerankerInspection.model_validate(inspect_reranker_directory(repo_root / "data/models", model_ref))
    except WorkerError as exc:
        raise ModelError(exc.code, "Use an existing directory with a safe relative path under data/models.", exc.status) from exc


def inspect_text_embedding(repo_root: Path, model_ref: str, parameters: dict | None = None) -> TextEmbeddingInspection:
    try:
        return TextEmbeddingInspection.model_validate(inspect_embedding(repo_root / "data/models", model_ref, parameters))
    except WorkerError as exc:
        raise ModelError(exc.code, "Use an existing directory with a safe relative path under data/models.", exc.status) from exc


def _information(schema, values, filename, diagnostics):
    values = {key: value for key, value in values.items() if key in schema.model_fields}
    try:
        return schema.model_validate(values, strict=True)
    except ValidationError as exc:
        for field in sorted({error["loc"][0] for error in exc.errors()}):
            values.pop(field, None)
            diagnostics.append(InspectionDiagnostic(file=filename, code="invalid_field",
                message=f"The declared {field} value cannot be interpreted."))
        return schema.model_validate(values, strict=True)


def inspect_siglip(repo_root: Path, model_ref: str) -> SiglipInspection:
    diagnostics, configs = [], {}
    try:
        path = model_directory(repo_root / "data" / "models", model_ref)
        for name in CONFIG_FILES:
            source = model_file(path, name)
            try:
                configs[name] = read_config(source)
            except FileNotFoundError:
                diagnostics.append(InspectionDiagnostic(file=name, code="missing_config",
                    message="Configuration is missing; information will be determined when loading."))
            except (OSError, ValueError):
                diagnostics.append(InspectionDiagnostic(file=name, code="invalid_config",
                    message="Configuration could not be read as a JSON object."))
    except WorkerError as exc:
        raise ModelError(exc.code, "Use an existing directory with a safe relative path under data/models.", exc.status) from exc
    config = configs.get("config.json", {})
    tokenizer = configs.get("tokenizer_config.json", {})
    model_type = config.get("model_type")
    model_type = model_type if isinstance(model_type, str) else None
    structure = STRUCTURES.get(model_type)
    if structure is None:
        diagnostics.append(InspectionDiagnostic(file="config.json", code="unknown_structure",
            message="No supported SigLIP FixRes-compatible or SigLIP2 NaFlex structure was identified."))
    sections = {}
    for name in ("vision_config", "text_config"):
        section = config.get(name, {})
        if not isinstance(section, dict):
            diagnostics.append(InspectionDiagnostic(file="config.json", code="invalid_field",
                message=f"The declared {name} is not an object."))
            section = {}
        sections[name] = section
    vision, text = sections["vision_config"], sections["text_config"]
    return SiglipInspection(model_ref=model_ref, model_type=model_type, structure=structure,
        image=_information(SiglipImageInfo, {"dimensions": vision.get("hidden_size"),
            "image_size": vision.get("image_size"), "patch_size": vision.get("patch_size")}, "config.json", diagnostics),
        text=_information(SiglipTextInfo, {"dimensions": text.get("projection_size"),
            "hidden_size": text.get("hidden_size"), "max_position_embeddings": text.get("max_position_embeddings"),
            "tokenizer_max_length": tokenizer.get("model_max_length"),
            **{key: tokenizer.get(key) for key in ("tokenizer_class", "do_lower_case", "add_bos_token", "add_eos_token")}},
            "config.json / tokenizer_config.json", diagnostics),
        processor=_information(SiglipProcessorInfo, configs.get("preprocessor_config.json", {}),
            "preprocessor_config.json", diagnostics), diagnostics=diagnostics)
