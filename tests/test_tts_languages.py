"""One TTS language contract across request schemas, local engines and providers."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from jsonschema import Draft202012Validator
from pydantic import ValidationError
import pytest

from ai_workbench.core.models.schema import AudioOutput, TTSExtensions
from ai_workbench.core.models.tts_languages import PROVIDER_TTS_LANGUAGES, TTS_LANGUAGE_ALIASES
from tests.test_audio import api, upload
from tests.test_qwen_tts import inline, qwen_api
from tests.test_tts import HEADERS, api as kokoro_api, wav_bytes


def test_language_schema_and_openapi_accept_the_same_aliases():
    schema = TTSExtensions.model_json_schema()
    validator = Draft202012Validator(schema)
    language_schema = schema["properties"]["language"]["anyOf"][0]
    assert language_schema["x-canonical-values"] == list(PROVIDER_TTS_LANGUAGES)
    assert language_schema["x-aliases"] == TTS_LANGUAGE_ALIASES
    cases = {code: code for code in PROVIDER_TTS_LANGUAGES} | TTS_LANGUAGE_ALIASES
    for value, expected in cases.items():
        for variant in (value, value.upper(), " \t" + value.lower().replace("-", "_") + "\n"):
            validator.validate({"language": variant})
            assert TTSExtensions(language=variant).language == expected
    assert TTSExtensions().language is None
    assert TTSExtensions(language=None).language is None
    validator.validate({"language": None})


@pytest.mark.parametrize("value", ["", " ", "ar", "pt", "es", "en-CA", "zh-TW", "zh-Hans", "xx", "ja_JP_extra", 1, True, [], {}])
def test_unknown_languages_are_rejected_by_schema_and_openapi(value):
    assert not Draft202012Validator(TTSExtensions.model_json_schema()).is_valid({"language": value})
    with pytest.raises(ValidationError):
        TTSExtensions(language=value)


def test_kokoro_auto_aliases_and_explicit_regions(kokoro_api):
    client, profile, path = kokoro_api
    (path / "voices/bf_alice.bin").write_bytes((path / "voices/af_heart.bin").read_bytes())
    manager = client.app.state.runtime_state.model_manager
    calls = []
    class Adapter:
        async def speech(self, *values):
            calls.append(values)
            return AudioOutput(data=wav_bytes(), response_format="wav")
    @asynccontextmanager
    async def lease(_):
        yield Adapter()
    manager._lease = lease
    for voice, language, expected in [("af_heart", None, "en-US"), ("af_heart", "auto", "en-US"),
            ("af_heart", "EN", "en-US"), ("bf_alice", None, "en-GB"), ("bf_alice", "AUTO", "en-GB"),
            ("bf_alice", " en_gb ", "en-GB")]:
        response = client.post("/v1/audio/speech", headers=HEADERS, json={"model": profile["alias"],
            "input": "Hi", "voice": voice, "response_format": "wav", "tts": {"language": language}})
        assert response.status_code == 200, response.text
        assert calls[-1][-1] == expected
    count = len(calls)
    for language in ("en", "en-US", "zh", "pt-PT", "es-MX"):
        response = client.post("/v1/audio/speech", headers=HEADERS, json={"model": profile["alias"],
            "input": "Hi", "voice": "bf_alice", "tts": {"language": language}})
        assert response.status_code == 400, response.text
    assert len(calls) == count


def test_chatterbox_auto_and_english_alias(api):
    client, _, profile, adapter = api
    voice = upload(client).json()["voice_id"]
    for tts in ({}, {"language": None}, {"language": "auto"}, {"language": " EN "}, {"language": "en_us"}):
        response = client.post("/v1/audio/speech", headers=HEADERS,
            json={"model": profile.alias, "input": "Hi", "voice": voice, "tts": tts})
        assert response.status_code == 200, response.text
        assert adapter.calls[-1][0][5] == "en-US"


def test_qwen_aliases_preserve_regions_and_auto(qwen_api):
    client, _, profile, adapter = qwen_api
    voice = upload(client, alias=profile.alias).json()["voice_id"]
    for language, expected in [(None, "auto"), ("AUTO", "auto"), ("zh", "zh-CN"), ("ZH_cn", "zh-CN"),
            ("en", "en-US"), ("en_GB", "en-GB"), ("pt_BR", "pt-BR"), ("ja", "ja-JP")]:
        response = client.post("/v1/audio/speech", headers=HEADERS,
            json={"model": profile.alias, "input": "Hi", "voice": voice, "tts": {"language": language}})
        assert response.status_code == 200, response.text
        assert adapter.calls[-1][0][5] == expected


def test_unsupported_local_languages_do_not_stage_references(qwen_api, monkeypatch):
    client, manager, _, adapter = qwen_api
    stage = AsyncMock(side_effect=AssertionError("No staging for unsupported languages"))
    monkeypatch.setattr(manager, "_stage_reference", stage)
    for alias, language in [("chatterbox", "en-GB"), ("chatterbox", "zh"), ("qwen", "hi"),
            ("qwen", "pt-PT"), ("qwen", "es-MX"), ("qwen", "ar-SA")]:
        response = client.post("/v1/audio/speech", headers=HEADERS, json={"model": alias, "input": "Hi",
            "tts": {"language": language, "reference_audio": inline()}})
        assert response.status_code == 400, response.text
    stage.assert_not_called()
    assert not adapter.calls
