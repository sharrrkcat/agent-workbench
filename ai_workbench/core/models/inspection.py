"""Lightweight directory information, independent of runtime installation and loading."""
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import StrictModel
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers.siglip_catalog import CONFIG_FILES, STRUCTURES, model_directory, model_file, read_config

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
