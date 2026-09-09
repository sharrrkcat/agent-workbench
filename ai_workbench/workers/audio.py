"""Bounded binary audio validation; no inference or codec imports."""
from io import BytesIO
import wave

if __package__:
    from .tts_catalog import MAX_AUDIO_BYTES, SAMPLE_RATE
else:
    from tts_catalog import MAX_AUDIO_BYTES, SAMPLE_RATE


def _validate_audio(data: bytes, response_format: str) -> None:
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_AUDIO_BYTES:
        raise ValueError("Invalid audio size")
    if response_format == "wav":
        with wave.open(BytesIO(data), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, SAMPLE_RATE, "NONE"):
                raise ValueError("Invalid WAV format")
            frames = audio.getnframes()
            if not frames or frames * 2 > MAX_AUDIO_BYTES or len(audio.readframes(frames)) != frames * 2:
                raise ValueError("Incomplete WAV data")
        if data[:4] != b"RIFF" or int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise ValueError("Invalid WAV length")
    elif response_format == "mp3":
        offset = 0
        while offset < len(data):
            if len(data) - offset < 4:
                raise ValueError("Incomplete MP3 header")
            header = int.from_bytes(data[offset:offset + 4], "big")
            # LAME emits MPEG-2 layer III, 128 kbps, 24 kHz, mono frames.
            if (header >> 21, (header >> 19) & 3, (header >> 17) & 3,
                (header >> 12) & 15, (header >> 10) & 3, (header >> 6) & 3) != (2047, 2, 1, 12, 1, 3):
                raise ValueError("Invalid MP3 format")
            offset += 384 + ((header >> 9) & 1)
        if offset != len(data):
            raise ValueError("Incomplete MP3 frame")
    else:
        raise ValueError("Unsupported audio format")


def validate_audio(data: bytes, response_format: str) -> None:
    try:
        _validate_audio(data, response_format)
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid WAV data") from exc
