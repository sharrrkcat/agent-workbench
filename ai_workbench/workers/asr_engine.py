"""Offline native Whisper transcription, including complete long-form inputs."""
from copy import deepcopy
from pathlib import Path

if __package__:
    from .audio_engine import device_for, require_offline
    from .common import WorkerError
    from .timing import stage
else:
    from audio_engine import device_for, require_offline
    from common import WorkerError
    from timing import stage


def decode_audio(path: Path):
    import numpy as np
    import soundfile as sf
    try:
        with sf.SoundFile(path) as source:
            if (source.format not in ("WAV", "WAVEX", "MP3")
                    or (path.suffix == ".mp3") != (source.format == "MP3")):
                raise WorkerError("INVALID_AUDIO")
            rate = source.samplerate
            audio = source.read(dtype="float32", always_2d=True)
        if not len(audio) or not np.isfinite(audio).all():
            raise WorkerError("INVALID_AUDIO")
        return audio.mean(axis=1, dtype=np.float32), rate
    except (OSError, ValueError, RuntimeError) as exc:
        raise WorkerError("INVALID_AUDIO") from exc


class ASREngine:
    def __init__(self, path, options, information):
        require_offline()
        with stage("engine_imports"):
            import torch
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.device, self.device_name = device_for(options)
        self.dtype = torch.float32 if self.device == "cpu" else torch.float16
        self.information = information
        with stage("processor"):
            self.processor = WhisperProcessor.from_pretrained(path, local_files_only=True)
        with stage("weights"):
            self.model = WhisperForConditionalGeneration.from_pretrained(path, local_files_only=True,
                dtype=self.dtype, attn_implementation="eager").to(self.device).eval()
        self.language_codes = {identifier: token[2:-2]
            for token, identifier in getattr(self.model.generation_config, "lang_to_id", {}).items()}

    def transcribe(self, path, options):
        import librosa
        import torch
        language = options["language"]
        if language != "auto" and language not in self.information["languages"]:
            raise WorkerError("UNSUPPORTED_CAPABILITY")
        audio, rate = decode_audio(path)
        duration = len(audio) / rate
        target_rate = self.processor.feature_extractor.sampling_rate
        if rate != target_rate:
            audio = librosa.resample(audio, orig_sr=rate, target_sr=target_rate)
        # Native language detection needs a full window even for short clips.
        # Padding fills short inputs; truncation=False preserves complete long inputs.
        inputs = self.processor(audio, sampling_rate=target_rate, return_tensors="pt",
            truncation=False, padding="max_length", return_attention_mask=True)
        frame_window = (self.model.model.encoder.conv1.stride[0]
            * self.model.model.encoder.conv2.stride[0] * self.model.config.max_source_positions)
        verbose = options["response_format"] == "verbose_json"
        configuration = deepcopy(self.model.generation_config)
        # Native language=None inherits the checkpoint field; auto must clear it.
        configuration.language = None
        configuration.task = None
        generation = {"generation_config": configuration, "temperature": options["temperature"],
            "return_timestamps": verbose or inputs.input_features.shape[-1] > frame_window,
            "return_segments": True, "return_dict_in_generate": False, "force_unique_generate_call": False}
        if self.information["multilingual"]:
            generation.update(task="transcribe", language=None if language == "auto" else language)
        if options["prompt"]:
            generation["prompt_ids"] = self.processor.get_prompt_ids(options["prompt"], return_tensors="pt").to(self.device)
        with torch.inference_mode():
            output = self.model.generate(inputs.input_features.to(self.device, dtype=self.dtype),
                attention_mask=inputs.attention_mask.to(self.device), **generation)
        native_segments = output["segments"][0]
        detected = language if language != "auto" else "en" if not self.information["multilingual"] else None
        if detected is None and native_segments:
            first = native_segments[0]["result"]
            sequence = first["sequences"] if isinstance(first, dict) else first
            detected = next((self.language_codes[token] for token in sequence.reshape(-1).tolist()
                if token in self.language_codes), None)
        segments = [{"id": index, "start": float(item["start"]), "end": float(item["end"]),
            "text": self.processor.decode(item["tokens"], skip_special_tokens=True).strip()}
            for index, item in enumerate(native_segments)] if verbose else None
        return {"response_format": options["response_format"], "task": "transcribe",
            "language": detected, "duration": duration,
            "text": self.processor.batch_decode(output["sequences"], skip_special_tokens=True)[0].strip(),
            "segments": segments}
