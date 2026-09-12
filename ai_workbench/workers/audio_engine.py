"""Offline engines sharing the Windows Audio dependency environment."""
from pathlib import Path
from io import BytesIO
import re
import sys
import types
import wave

if __package__:
    from .audio import validate_audio
    from .audio_catalog import CHATTERBOX_DEFAULTS, MAX_DECODED_BYTES, MAX_REFERENCE_SECONDS, QWEN3TTS_DEFAULTS, QWEN3TTS_LANGUAGES, QWEN3TTS_SUBTALKER
    from .common import WorkerError
    from .tts_catalog import MAX_AUDIO_BYTES, SAMPLE_RATE
    from .timing import stage
else:
    from audio import validate_audio
    from audio_catalog import CHATTERBOX_DEFAULTS, MAX_DECODED_BYTES, MAX_REFERENCE_SECONDS, QWEN3TTS_DEFAULTS, QWEN3TTS_LANGUAGES, QWEN3TTS_SUBTALKER
    from common import WorkerError
    from tts_catalog import MAX_AUDIO_BYTES, SAMPLE_RATE
    from timing import stage

_network_blocked = False


def encode_pcm16(pcm: bytes, response_format: str) -> tuple[bytes, str]:
    if not pcm or len(pcm) > MAX_AUDIO_BYTES or len(pcm) % 2:
        raise ValueError("Invalid PCM size")
    if response_format == "wav":
        stream = BytesIO()
        with wave.open(stream, "wb") as output:
            output.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
            output.writeframes(pcm)
        result = stream.getvalue()
    elif response_format == "mp3":
        import lameenc
        encoder = lameenc.Encoder()
        encoder.set_bit_rate(128)
        encoder.set_in_sample_rate(SAMPLE_RATE)
        encoder.set_channels(1)
        encoder.set_quality(2)
        result = bytes(encoder.encode(pcm) + encoder.flush())
    else:
        raise ValueError("Unsupported audio format")
    validate_audio(result, response_format)
    return result, "audio/wav" if response_format == "wav" else "audio/mpeg"


def require_offline():
    global _network_blocked
    if not _network_blocked:
        def reject_network(event, _args):
            if event in {"socket.connect", "socket.getaddrinfo"}:
                print("Audio worker network access rejected", flush=True)
                raise RuntimeError("Audio worker network access is disabled")
        sys.addaudithook(reject_network)
        _network_blocked = True


def decode_audio(path: Path, *, max_seconds=MAX_REFERENCE_SECONDS):
    """Count decoded frames before resampling or model feature extraction."""
    require_offline()
    import numpy as np
    import soundfile as sf
    try:
        blocks, count = [], 0
        with sf.SoundFile(path) as source:
            if source.format not in {"WAV", "WAVEX", "MP3"} or source.channels not in {1, 2} or not 8000 <= source.samplerate <= 192000:
                raise WorkerError("INVALID_AUDIO")
            if (path.suffix.lower() == ".mp3") != (source.format == "MP3"):
                raise WorkerError("INVALID_AUDIO")
            rate = source.samplerate
            while True:
                block = source.read(65536, dtype="float32", always_2d=True)
                if not len(block):
                    break
                count += len(block)
                if count > max_seconds * rate:
                    raise WorkerError("AUDIO_TOO_LONG")
                if count * source.channels * 4 > MAX_DECODED_BYTES:
                    raise WorkerError("AUDIO_TOO_LARGE", 413)
                if not np.isfinite(block).all():
                    raise WorkerError("INVALID_AUDIO")
                blocks.append(block.mean(axis=1, dtype=np.float32))
        if not count:
            raise WorkerError("INVALID_AUDIO")
        return np.concatenate(blocks), rate
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, WorkerError):
            raise
        raise WorkerError("INVALID_AUDIO") from exc


def device_for(options):
    with stage("device_init"):
        import torch
        torch.set_num_threads(options["intraop_threads"])
        if options["device"] == "cpu":
            return "cpu", "CPU"
        try:
            if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
                raise RuntimeError("CUDA unavailable")
            torch.cuda.set_device(0)
            torch.empty(1, device="cuda:0")
            return "cuda", torch.cuda.get_device_name(0)
        except Exception as exc:
            raise WorkerError("RUNTIME_DEVICE_UNAVAILABLE", 503) from exc


def text_chunks(text, limit=250):
    current = ""
    for word in re.findall(r"\S+\s*", text):
        if len(word.rstrip()) > limit:
            raise WorkerError("INVALID_REQUEST")
        if len(current) + len(word) > limit and current:
            yield current.strip()
            current = ""
        current += word
        if re.search(r"[.!?][\"']?\s+$", word):
            yield current.strip()
            current = ""
    if current.strip():
        yield current.strip()


def encode_waveform(audio, rate, speed, response_format):
    import librosa
    import numpy as np
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not audio.size or not np.isfinite(audio).all():
        raise WorkerError("MODEL_UNAVAILABLE", 503)
    if rate != SAMPLE_RATE:
        audio = librosa.resample(audio, orig_sr=rate, target_sr=SAMPLE_RATE)
    if speed != 1:
        audio = librosa.effects.time_stretch(audio, rate=speed)
    if audio.size * 2 > MAX_AUDIO_BYTES:
        raise WorkerError("AUDIO_TOO_LARGE", 413)
    try:
        return encode_pcm16((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes(), response_format)
    except ValueError as exc:
        raise WorkerError("AUDIO_TOO_LARGE", 413) from exc


def patch_chatterbox_f32(model):
    # Voicebox 51f49dea: these two upstream entry points can receive float64.
    tokenizer = model.s3gen.tokenizer
    original_mel = tokenizer.log_mel_spectrogram.__func__
    def log_mel(self, audio, padding=0):
        import torch
        return original_mel(self, audio.float() if torch.is_tensor(audio) else audio, padding)
    tokenizer.log_mel_spectrogram = types.MethodType(log_mel, tokenizer)
    encoder = model.ve
    original_forward = encoder.forward.__func__
    def forward(self, mels):
        return original_forward(self, mels.float())
    encoder.forward = types.MethodType(forward, encoder)


class ChatterboxEngine:
    def __init__(self, path, options):
        require_offline()
        with stage("engine_imports"):
            from chatterbox.tts import ChatterboxTTS
        self.device, self.device_name = device_for(options)
        with stage("model_from_local"):
            self.model = ChatterboxTTS.from_local(path, device=self.device)
        with stage("post_load"):
            if self.device == "cpu":
                self.model.t3.float()
                self.model.s3gen.float()
                self.model.ve.float()
            transformer = self.model.t3.tfmr
            transformer.config._attn_implementation = "eager"
            for layer in getattr(transformer, "layers", []):
                layer.self_attn._attn_implementation = "eager"
            patch_chatterbox_f32(self.model)
            self.model.conds = None
            self.dtype = next(self.model.t3.parameters()).dtype

    def speech(self, text, reference, speed, response_format, model_options):
        import numpy as np
        import torch
        decode_audio(reference)
        values = {**CHATTERBOX_DEFAULTS, **model_options}
        parts, size = [], 0
        try:
            self.model.conds = None
            with torch.inference_mode():
                self.model.prepare_conditionals(str(reference), exaggeration=values["exaggeration"])
                for chunk in text_chunks(text):
                    audio = self.model.generate(chunk, **values).detach().cpu().numpy().reshape(-1)
                    size += audio.size
                    if size * 2 / speed > MAX_AUDIO_BYTES:
                        raise WorkerError("AUDIO_TOO_LARGE", 413)
                    parts.append(audio)
            return encode_waveform(np.concatenate(parts), self.model.sr, speed, response_format)
        finally:
            # An invalid or cancelled request must never inherit another voice.
            self.model.conds = None


class QwenTTSEngine:
    """Qwen3-TTS 12Hz Base with request-scoped voice conditioning."""
    def __init__(self, path, options):
        require_offline()
        with stage("engine_imports"):
            import torch
            from qwen_tts import Qwen3TTSModel
        self.device, self.device_name = device_for(options)
        with stage("model_from_pretrained"):
            self.model = Qwen3TTSModel.from_pretrained(str(path), device_map=self.device,
                dtype=torch.float32 if self.device == "cpu" else torch.bfloat16,
                attn_implementation="sdpa", local_files_only=True, trust_remote_code=False, use_safetensors=True)
        with stage("post_load"):
            self.dtype = self.model.model.dtype

    def speech(self, text, reference, speed, response_format, model_options, *, language=None, reference_text=None):
        audio, reference_rate = decode_audio(reference)
        waves, rate = self.model.generate_voice_clone(text=text, language=QWEN3TTS_LANGUAGES[language or "auto"],
            ref_audio=(audio, reference_rate), ref_text=reference_text, x_vector_only_mode=reference_text is None,
            **{**QWEN3TTS_DEFAULTS, **model_options, **QWEN3TTS_SUBTALKER})
        return encode_waveform(waves[0], rate, speed, response_format)


class WhisperEngine:
    """Short-form package acceptance engine; no public ASR endpoint."""
    def __init__(self, path, options):
        require_offline()
        with stage("engine_imports"):
            import torch
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.device, self.device_name = device_for(options)
        self.dtype = torch.float32 if self.device == "cpu" else torch.float16
        with stage("processor"):
            self.processor = WhisperProcessor.from_pretrained(path, local_files_only=True)
        with stage("weights"):
            self.model = WhisperForConditionalGeneration.from_pretrained(path, local_files_only=True,
                torch_dtype=self.dtype, attn_implementation="eager").to(self.device).eval()

    def transcribe(self, reference):
        import librosa
        import torch
        audio, rate = decode_audio(reference, max_seconds=30)
        if rate != 16000:
            audio = librosa.resample(audio, orig_sr=rate, target_sr=16000)
        features = self.processor(audio, sampling_rate=16000, return_tensors="pt").input_features
        with torch.inference_mode():
            tokens = self.model.generate(features.to(self.device, dtype=self.dtype), task="transcribe")
        return {"text": self.processor.batch_decode(tokens, skip_special_tokens=True)[0]}
