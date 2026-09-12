"""Offline Kokoro ONNX execution, imported only inside the managed worker."""
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import sys
import wave

if __package__:
    from .protocol import WorkerError
    from .tts_catalog import FORMATS, LANGUAGES, MAX_AUDIO_BYTES, MAX_TOKENS, SAMPLE_RATE, valid_voice, voice_file
    from .audio import validate_audio
    from .timing import stage
else:
    from protocol import WorkerError
    from tts_catalog import FORMATS, LANGUAGES, MAX_AUDIO_BYTES, MAX_TOKENS, SAMPLE_RATE, valid_voice, voice_file
    from audio import validate_audio
    from timing import stage

_network_blocked = False


def require_offline():
    global _network_blocked
    if _network_blocked:
        return
    def reject_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            print("ONNX worker network access rejected", flush=True)
            raise RuntimeError("ONNX worker network access is disabled")
    sys.addaudithook(reject_network)
    _network_blocked = True


def phoneme_chunks(phonemes: str, encode):
    """Split on phoneme word boundaries without tokenizer truncation."""
    current = ""
    for word in re.findall(r"\S+\s*", phonemes):
        candidate = current + word
        if len(encode(candidate)) > MAX_TOKENS + 2:
            if current.strip():
                yield encode(current)
            current = word
            if len(encode(current)) > MAX_TOKENS + 2:
                raise WorkerError("INVALID_REQUEST")
        else:
            current = candidate
    if current.strip():
        yield encode(current)


def language_processors():
    with stage("language_imports"):
        with stage("language_imports.importlib_metadata"):
            import importlib.metadata
        with stage("language_imports.spacy"):
            import spacy
        with stage("language_imports.misaki.en"):
            from misaki import en
        with stage("language_imports.misaki.espeak"):
            from misaki import espeak
        with stage("language_imports.misaki.zh"):
            from misaki import zh
        with stage("language_imports.misaki.cutlet"):
            from misaki.cutlet import Cutlet
        with stage("language_imports.jieba"):
            import jieba
    with stage("language_resources"):
        if importlib.metadata.version("en-core-web-sm") != "3.7.1" or not spacy.util.is_package("en_core_web_sm"):
            raise WorkerError("RUNTIME_BROKEN", 503)
    logging.getLogger("jieba").setLevel(logging.ERROR)
    jieba.setLogLevel(logging.ERROR)
    processors = {}
    for code, build in (
        ("a", lambda: en.G2P(trf=False, british=False, fallback=espeak.EspeakFallback(british=False))),
        ("b", lambda: en.G2P(trf=False, british=True, fallback=espeak.EspeakFallback(british=True))),
        ("j", Cutlet), ("z", lambda: zh.ZHG2P(version=None)),
    ):
        with stage(f"language.{LANGUAGES[code]}.build"):
            processors[code] = build()
    for code, language in {"e": "es", "f": "fr-fr", "h": "hi", "i": "it", "p": "pt-br"}.items():
        with stage(f"language.{LANGUAGES[code]}.build"):
            processors[code] = espeak.EspeakG2P(language=language)
    # Construct every frontend before ready, including its packaged dictionaries.
    for code, text in {"a": "hello", "b": "hello", "j": "\u3053\u3093\u306b\u3061\u306f", "z": "\u4f60\u597d",
                       "e": "hola", "f": "bonjour", "h": "\u0928\u092e\u0938\u094d\u0924\u0947", "i": "ciao", "p": "ola"}.items():
        with stage(f"language.{LANGUAGES[code]}.warmup"):
            if not processors[code](text)[0]:
                raise WorkerError("RUNTIME_BROKEN", 503)
    return processors


class TTSEngine:
    def __init__(self, path: Path, kind, params, options):
        require_offline()
        with stage("engine_imports"):
            with stage("engine_imports.numpy"):
                import numpy as np
            with stage("engine_imports.onnxruntime"):
                import onnxruntime as ort
            with stage("engine_imports.tokenizers"):
                from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, Regex
            with stage("engine_imports.lameenc"):
                import lameenc
        self.path, self.kind, self.params, self.options = path, kind, params, options
        self.np, self.lameenc = np, lameenc
        with stage("tokenizer"):
            config = json.loads((path / "tokenizer.json").read_text(encoding="utf-8"))
            vocab = config["model"]["vocab"]
            if vocab.get("$") != 0 or not all(isinstance(v, int) and v >= 0 for v in vocab.values()):
                raise WorkerError("MODEL_UNAVAILABLE", 503)
            # The supplied Transformers.js tokenizer omits Rust tokenizer type tags.
            self.tokenizer = Tokenizer(models.WordLevel(vocab, unk_token="$"))
            self.tokenizer.normalizer = normalizers.Replace(Regex(config["normalizer"]["pattern"]["Regex"]), "")
            self.tokenizer.pre_tokenizer = pre_tokenizers.Split(Regex(""), behavior="isolated")
            self.tokenizer.no_truncation()
        with stage("onnx_session"):
            settings = ort.SessionOptions()
            settings.intra_op_num_threads = options["intraop_threads"]
            settings.log_severity_level = 3
            self.model = ort.InferenceSession(str(path / "model.onnx"), sess_options=settings, providers=["CPUExecutionProvider"])
            inputs = [(v.name, v.type, v.shape) for v in self.model.get_inputs()]
            outputs = self.model.get_outputs()
            if (len(inputs) != 3 or [v[:2] for v in inputs] != [("input_ids", "tensor(int64)"), ("style", "tensor(float)"), ("speed", "tensor(float)")]
                    or inputs[0][2][0] != 1 or len(inputs[0][2]) != 2 or inputs[1][2] != [1, 256] or inputs[2][2] != [1]
                    or len(outputs) != 1 or outputs[0].name != "waveform" or outputs[0].type != "tensor(float)"
                    or len(outputs[0].shape) != 2 or outputs[0].shape[0] != 1):
                raise WorkerError("MODEL_UNAVAILABLE", 503)
        with stage("language_frontends"):
            self.processors = language_processors()
        self.voices = {}

    def speech(self, text, voice, speed, response_format, language):
        np = self.np
        if not valid_voice(self.path, voice):
            raise WorkerError("VOICE_UNAVAILABLE", 404)
        if language is not None and language != LANGUAGES[voice[0]]:
            raise WorkerError("INVALID_REQUEST")
        if voice not in self.voices:
            self.voices[voice] = np.fromfile(voice_file(self.path, voice), dtype="<f4").reshape(MAX_TOKENS, 1, 256)
        pcm = bytearray()
        encode = lambda text: [0, *self.tokenizer.encode(text, add_special_tokens=False).ids, 0]
        for sentence in re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s*|\n+", text):
            if not sentence.strip():
                continue
            phonemes = self.processors[voice[0]](sentence)[0]
            for ids in phoneme_chunks(phonemes, encode):
                count = len(ids) - 2
                if not 1 <= count <= MAX_TOKENS or ids[0] != 0 or ids[-1] != 0:
                    raise WorkerError("INVALID_REQUEST")
                audio = self.model.run(["waveform"], {"input_ids": np.asarray([ids], dtype=np.int64),
                    "style": self.voices[voice][count - 1], "speed": np.asarray([speed], dtype=np.float32)})[0]
                if audio.ndim != 2 or audio.shape[0] != 1 or not audio.size or not np.isfinite(audio).all():
                    raise WorkerError("MODEL_UNAVAILABLE", 503)
                if len(pcm) + audio.size * 2 > MAX_AUDIO_BYTES:
                    raise WorkerError("AUDIO_TOO_LARGE", 413)
                pcm.extend((np.clip(audio[0], -1, 1) * 32767).astype("<i2").tobytes())
        if not pcm:
            raise WorkerError("INVALID_REQUEST")
        if response_format == "wav":
            stream = BytesIO()
            with wave.open(stream, "wb") as output:
                output.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
                output.writeframes(pcm)
            result = stream.getvalue()
        else:
            encoder = self.lameenc.Encoder()
            encoder.set_bit_rate(128)
            encoder.set_in_sample_rate(SAMPLE_RATE)
            encoder.set_channels(1)
            encoder.set_quality(2)
            result = bytes(encoder.encode(bytes(pcm)) + encoder.flush())
        if len(result) > MAX_AUDIO_BYTES:
            raise WorkerError("AUDIO_TOO_LARGE", 413)
        try:
            validate_audio(result, response_format)
        except ValueError as exc:
            raise WorkerError("MODEL_UNAVAILABLE", 503) from exc
        return result, FORMATS[response_format]
