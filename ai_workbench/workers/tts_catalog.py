"""Kokoro's fixed file and voice contract, shared without inference imports."""
import json
import math
from pathlib import Path
import struct

SAMPLE_RATE = 24000
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_INPUT_CHARS = 4096
MAX_TOKENS = 510
VOICE_BYTES = MAX_TOKENS * 256 * 4
LANGUAGES = {
    "a": "en-US", "b": "en-GB", "j": "ja-JP", "z": "zh-CN",
    "e": "es-ES", "f": "fr-FR", "h": "hi-IN", "i": "it-IT", "p": "pt-BR",
}
VOICE_IDS = tuple(sorted((
    "af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky "
    "am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa "
    "bf_alice bf_emma bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis "
    "ef_dora em_alex em_santa ff_siwis hf_alpha hf_beta hm_omega hm_psi if_sara im_nicola "
    "jf_alpha jf_gongitsune jf_nezumi jf_tebukuro jm_kumo pf_dora pm_alex pm_santa "
    "zf_xiaobei zf_xiaoni zf_xiaoxiao zf_xiaoyi zm_yunjian zm_yunxi zm_yunxia zm_yunyang"
).split()))
FORMATS = {"mp3": "audio/mpeg", "wav": "audio/wav"}


def model_files(path: Path) -> bool:
    try:
        for name in ("config.json", "tokenizer.json", "tokenizer_config.json", "model.onnx"):
            file = path / name
            if not file.resolve().is_relative_to(path.resolve()) or not file.is_file():
                return False
        config = json.loads((path / "config.json").read_text(encoding="utf-8"))
        return config.get("model_type") == "style_text_to_speech_2"
    except (OSError, ValueError, AttributeError):
        return False


def voice_file(path: Path, voice_id: str) -> Path:
    if voice_id not in VOICE_IDS:
        raise ValueError("Unsupported voice ID")
    file = path / "voices" / (voice_id + ".bin")
    if not file.resolve().is_relative_to(path.resolve()):
        raise ValueError("Voice file escapes model directory")
    return file


def valid_voice(path: Path, voice_id: str) -> bool:
    try:
        file = voice_file(path, voice_id)
        if file.stat().st_size != VOICE_BYTES:
            return False
        with file.open("rb") as stream:
            raw = stream.read(VOICE_BYTES + 1)
        return len(raw) == VOICE_BYTES and all(math.isfinite(v[0]) for v in struct.iter_unpack("<f", raw))
    except (OSError, ValueError, struct.error):
        return False


def voices(path: Path | None) -> list[dict]:
    return [{"id": voice_id, "source": "preset", "language": LANGUAGES[voice_id[0]],
             "expires_at": None, "available": path is not None and valid_voice(path, voice_id)}
            for voice_id in VOICE_IDS]
