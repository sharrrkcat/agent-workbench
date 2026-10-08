"""Project TTS language identifiers and explicit OpenAI-compatible provider mapping."""
from typing import Annotated

from pydantic import AfterValidator, Field


PROVIDER_TTS_LANGUAGES = {
    "auto": "auto", "en-US": "en", "en-GB": "en", "zh-CN": "zh", "ja-JP": "ja",
    "ko-KR": "ko", "fr-FR": "fr", "de-DE": "de", "hi-IN": "hi", "id-ID": "id",
    "it-IT": "it", "ru-RU": "ru", "bn-BD": "bn", "tr-TR": "tr", "vi-VN": "vi",
    "ar-EG": "ar-EG", "ar-SA": "ar-SA", "ar-AE": "ar-AE", "pt-BR": "pt-BR",
    "pt-PT": "pt-PT", "es-MX": "es-MX", "es-ES": "es-ES",
}
TTS_LANGUAGE_ALIASES = {
    "en": "en-US", "zh": "zh-CN", "ja": "ja-JP", "ko": "ko-KR", "fr": "fr-FR",
    "de": "de-DE", "hi": "hi-IN", "id": "id-ID", "it": "it-IT", "ru": "ru-RU",
    "bn": "bn-BD", "tr": "tr-TR", "vi": "vi-VN",
}
_LANGUAGE_INPUTS = {code.lower(): code for code in PROVIDER_TTS_LANGUAGES} | TTS_LANGUAGE_ALIASES
# Explicit letter classes keep the pattern valid in both JSON Schema and Pydantic.
_LANGUAGE_PATTERN = r"^\s*(?:" + "|".join(
    "".join("[-_]" if char == "-" else f"[{char}{char.upper()}]" for char in code)
    for code in _LANGUAGE_INPUTS
) + r")\s*$"


def normalize_tts_language(value: str) -> str:
    return _LANGUAGE_INPUTS[value.strip().replace("_", "-").lower()]


TTS_LANGUAGE_DESCRIPTION = (
    "Project TTS language code. Standard codes: " + ", ".join(PROVIDER_TTS_LANGUAGES) + ". "
    "Short aliases: " + ", ".join(f"{alias}={code}" for alias, code in TTS_LANGUAGE_ALIASES.items()) + ". "
    "Surrounding whitespace, case and underscore separators are normalized. Regions remain distinct; "
    "bare ar/pt/es and unknown regions are rejected. Omitted/null/auto uses provider or Qwen automatic selection, "
    "the Kokoro preset language, or Chatterbox en-US. The selected local model must support the language. "
    "Providers receive native codes (e.g. zh-CN to zh, en-US/en-GB to en) without an accent guarantee."
)
TTSLanguage = Annotated[str, Field(strict=True, pattern=_LANGUAGE_PATTERN,
    json_schema_extra={"x-canonical-values": list(PROVIDER_TTS_LANGUAGES), "x-aliases": TTS_LANGUAGE_ALIASES}),
    AfterValidator(normalize_tts_language)]
