"""Read-only speech capabilities derived from the model service's own contracts."""
from __future__ import annotations

import hashlib
import json
from typing import Literal, TYPE_CHECKING

from pydantic import Field

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.resolution import configure_profile, require_directory, TTS_SCHEMAS
from ai_workbench.core.models.runtimes.schema import local_engine
from ai_workbench.core.models.schema import (
    ProviderSource, ProviderTTSParameters, ReferenceTranscript, SpeechOutputParameters,
    SpeechRequest, StrictModel,
)
from ai_workbench.core.models.tts_languages import PROVIDER_TTS_LANGUAGES
from ai_workbench.workers.audio_catalog import MAX_REFERENCE_BYTES, MAX_REFERENCE_SECONDS, QWEN3TTS_LANGUAGES
from ai_workbench.workers.tts_catalog import MAX_AUDIO_BYTES

if TYPE_CHECKING:
    from ai_workbench.core.models.manager import ModelManager
    from ai_workbench.core.models.schema import ModelProfile


class TTSLanguageCapability(StrictModel):
    id: str
    display_name: str


class TTSVoiceCapability(StrictModel):
    id: str
    display_name: str
    languages: list[str] = Field(description="Accepted fixed languages for this voice; derived from model languages when the voice has no language restriction.")


class TTSNamedCapability(StrictModel):
    supported: bool
    selection: Literal["catalog", "custom"] = "catalog"
    default_voice_id: str | None = None
    voices: list[TTSVoiceCapability] = Field(default_factory=list)


class TTSClonedCapability(StrictModel):
    supported: bool
    min_reference_pairs: int = Field(default=0, ge=0)
    max_reference_pairs: int | None = Field(default=None, ge=1)
    reference_text_mode: Literal["unsupported", "optional", "required"] = "unsupported"


class TTSSynthesisLimits(StrictModel):
    max_text_scalars: int = Field(ge=1)
    max_reference_bytes: int | None = Field(default=None, ge=1)
    max_reference_duration_ms: int | None = Field(default=None, ge=1)
    max_reference_text_scalars: int | None = Field(default=None, ge=1)
    max_audio_bytes: int = Field(ge=1)


class TTSParameterCapability(StrictModel):
    key: str
    value_type: Literal["boolean", "integer", "number", "string"]
    required: bool = False
    nullable: bool
    default_value: bool | int | float | str | None
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False
    exclusive_maximum: bool = False
    choices: list[bool | int | float | str | None] = Field(default_factory=list)
    affects_output: bool = True
    wire_target: Literal["speed", "model_options"]


class TTSModelCapability(StrictModel):
    id: str = Field(description="Public model alias used by audio/speech and voice-references.")
    display_name: str
    available: bool
    binding_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$", description="Opaque identity of the model and non-secret execution source; excludes display names, credentials, lifecycle and parameter defaults.")
    languages: list[TTSLanguageCapability]
    supports_auto_language: bool
    supports_seed: bool
    named: TTSNamedCapability
    cloned: TTSClonedCapability
    limits: TTSSynthesisLimits
    response_formats: list[Literal["mp3", "wav"]]
    parameters: list[TTSParameterCapability]


class TTSCatalogIssue(StrictModel):
    model: str
    code: str
    message: str


class TTSCapabilityCatalog(StrictModel):
    object: Literal["list"] = "list"
    contract_version: Literal[1] = 1
    data: list[TTSModelCapability] = Field(default_factory=list)
    issues: list[TTSCatalogIssue] = Field(default_factory=list)


def _parameter_fields(schema: type[StrictModel], defaults: dict) -> list[TTSParameterCapability]:
    fields = []
    for key, field in schema.model_json_schema()["properties"].items():
        if key in {"architecture", "voice", "response_format"}:
            continue
        variants = field.get("anyOf", [field])
        value = next(item for item in variants if item.get("type") != "null")
        fields.append(TTSParameterCapability(
            key=key, value_type=value["type"], nullable=any(item.get("type") == "null" for item in variants),
            default_value=defaults[key], minimum=value.get("minimum", value.get("exclusiveMinimum")),
            maximum=value.get("maximum", value.get("exclusiveMaximum")),
            exclusive_minimum="exclusiveMinimum" in value, exclusive_maximum="exclusiveMaximum" in value,
            choices=value.get("enum", []), wire_target="speed" if key == "speed" else "model_options",
        ))
    return fields


def _describe(manager: ModelManager, profile: ModelProfile) -> TTSModelCapability:
    profile = configure_profile(manager._resolve(profile))
    online = isinstance(profile.source, ProviderSource)
    engine = local_engine(profile)
    cloned = not online and engine in {"chatterbox", "qwen3tts"}
    binding = {"id": profile.id, "model_ref": profile.model_ref, "source": profile.source.type}
    available = True
    if online:
        provider = manager.providers.get(profile.source.provider_profile_id)
        binding.update(provider_id=provider.id, base_url=provider.connection.base_url,
                       architecture=profile.parameters["architecture"])
        available = provider.enabled
        schema = ProviderTTSParameters
        language_ids = [code for code in PROVIDER_TTS_LANGUAGES if code != "auto"]
    else:
        require_directory(profile)
        if engine not in TTS_SCHEMAS:
            raise ModelError("UNSUPPORTED_CAPABILITY", "The local TTS engine could not be determined.")
        schema = TTS_SCHEMAS[engine]
        binding.update(engine=engine, execution_options=profile.source.execution_options,
                       release=manager.runtime_supervisor.release.version if manager.runtime_supervisor else None)
        language_ids = ([code for code in QWEN3TTS_LANGUAGES if code != "auto"] if engine == "qwen3tts"
                        else ["en-US"] if engine == "chatterbox" else [])
    voices = [voice for voice in manager.voice_list(profile.id) if voice["available"]] if not cloned else []
    if not online and engine == "kokoro":
        language_ids = sorted({voice["language"] for voice in voices})
        available = bool(voices)
    named = TTSNamedCapability(
        supported=not cloned,
        selection="custom" if online and profile.parameters["architecture"] == "customize" else "catalog",
        default_voice_id=profile.parameters.get("voice") if online else None,
        voices=[TTSVoiceCapability(id=voice["id"], display_name=voice["id"],
                                  languages=[voice["language"]] if voice["language"] else language_ids)
                for voice in voices],
    )
    limits = TTSSynthesisLimits(
        max_text_scalars=SpeechRequest.model_json_schema()["properties"]["input"]["maxLength"],
        max_audio_bytes=MAX_AUDIO_BYTES,
        max_reference_bytes=MAX_REFERENCE_BYTES if cloned else None,
        max_reference_duration_ms=MAX_REFERENCE_SECONDS * 1000 if cloned else None,
        max_reference_text_scalars=(ReferenceTranscript.model_json_schema()["properties"]["reference_text"]["anyOf"][0]["maxLength"]
                                    if engine == "qwen3tts" else None),
    )
    return TTSModelCapability(
        id=profile.alias, display_name=profile.name, available=available,
        binding_fingerprint=hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        languages=[TTSLanguageCapability(id=code, display_name=code) for code in language_ids],
        supports_auto_language=True, supports_seed=cloned, named=named,
        cloned=TTSClonedCapability(supported=cloned, min_reference_pairs=1 if cloned else 0,
                                  max_reference_pairs=1 if cloned else None,
                                  reference_text_mode="optional" if engine == "qwen3tts" else "unsupported"),
        limits=limits,
        response_formats=SpeechOutputParameters.model_json_schema()["properties"]["response_format"]["enum"],
        parameters=_parameter_fields(schema, profile.parameters),
    )


def capability_catalog(manager: ModelManager, model: str | None = None) -> TTSCapabilityCatalog:
    if model is not None:
        profile = manager.profiles.find_by_alias(model)
        if profile is None or not profile.enabled or not profile.external_enabled or profile.kind != "tts":
            raise ModelError("MODEL_NOT_FOUND", "Model alias is not available to the external TTS service.", 404)
        profiles = [profile]
    else:
        profiles = [profile for profile in manager.profiles.list("tts") if profile.enabled and profile.external_enabled]
    result = TTSCapabilityCatalog()
    for profile in profiles:
        try:
            descriptor = _describe(manager, profile)
        except ModelError as exc:
            result.issues.append(TTSCatalogIssue(model=profile.alias, code=exc.code, message=exc.message))
        except KeyError:
            result.issues.append(TTSCatalogIssue(model=profile.alias, code="MODEL_UNAVAILABLE",
                                                message="The model's configured provider or defaults are unavailable."))
        else:
            result.data.append(descriptor)
            if not descriptor.available:
                result.issues.append(TTSCatalogIssue(model=profile.alias, code="MODEL_UNAVAILABLE",
                                                    message="The provider is disabled or no usable preset voice is present."))
    return result
