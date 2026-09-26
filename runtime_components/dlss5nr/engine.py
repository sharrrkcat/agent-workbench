"""Standalone still-image DLSS NR engine. NumPy/Pillow are supplied by Local Runtime."""
import base64
import ctypes
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image

MAX_PIXELS = 8_388_608
STYLES = {"natural": 0, "cinematic": 1, "default": 2, **{str(i): i for i in range(3, 7)}}


class WorkerError(Exception):
    def __init__(self, code, status=422):
        self.code, self.status = code, status


def fields(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise WorkerError("INVALID_REQUEST")


def load_bridge(path):
    bridge = ctypes.CDLL(str(path))
    bridge.dlss5nr_init.argtypes = [ctypes.c_int, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                  ctypes.c_wchar_p, ctypes.c_char_p, ctypes.c_int]
    bridge.dlss5nr_init.restype = ctypes.c_int
    pointer = ctypes.POINTER(ctypes.c_float)
    bridge.dlss5nr_process.argtypes = [pointer, pointer, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_float, ctypes.c_float, ctypes.c_float,
        ctypes.c_float, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    bridge.dlss5nr_process.restype = ctypes.c_int
    bridge.dlss5nr_shutdown.argtypes = []
    bridge.dlss5nr_shutdown.restype = None
    bridge.dlss5nr_version.argtypes = []
    bridge.dlss5nr_version.restype = ctypes.c_char_p
    bridge.dlss5nr_gpu_name.argtypes = []
    bridge.dlss5nr_gpu_name.restype = ctypes.c_char_p
    if bridge.dlss5nr_version() != b"cogita-dlss5nr-0.1.1":
        raise WorkerError("RUNTIME_COMPONENT_INCOMPATIBLE", 503)
    return bridge


def controls(values):
    fields(values, {"style", "preset", "intensity", "tone", "structure", "skin", "auto_mask", "channel_order"})
    if (values["style"] not in STYLES or type(values["preset"]) is not int or not 0 <= values["preset"] <= 3
            or type(values["auto_mask"]) is not bool or values["channel_order"] not in {"auto", "RGBA", "BGRA"}):
        raise WorkerError("INVALID_REQUEST")
    for key in ("intensity", "tone", "structure", "skin"):
        value = values[key]
        if type(value) not in {int, float} or not math.isfinite(value) or not (-1 if key == "skin" else 0) <= value <= 2:
            raise WorkerError("INVALID_REQUEST")
    return values


def correct_channels(raw, source, order):
    if order == "RGBA":
        return raw
    swapped = raw[..., [2, 1, 0]]
    if order == "BGRA":
        return swapped
    height, width = source.shape[:2]
    sample = (slice(None, None, max(1, height // 128)), slice(None, None, max(1, width // 128)))
    reference = source[sample]
    def score(value):
        current = value[sample]
        return float(np.mean(np.abs(current - reference))) + float(np.mean(np.abs(current.mean(axis=(0, 1)) - reference.mean(axis=(0, 1)))))
    return raw if score(raw) <= score(swapped) else swapped


class Engine:
    def __init__(self, models_root, bridge_path, caller_path, work_dir):
        self.models_root = Path(models_root).resolve()
        self.caller_path, self.work_dir = str(caller_path), str(work_dir)
        self.bridge = load_bridge(bridge_path)
        self.profile_id = None

    def load(self, value):
        fields(value, {"profile_id", "kind", "model_ref", "parameters", "options"})
        options = value["options"]
        fields(options, {"device", "gpu_index"})
        ref = value["model_ref"]
        if (value["kind"] != "processor" or not isinstance(value["profile_id"], str)
                or options["device"] != "d3d12" or type(options["gpu_index"]) is not int or not 0 <= options["gpu_index"] <= 15
                or not isinstance(ref, str) or "\\" in ref or ":" in ref or any(p in {"", ".", ".."} for p in ref.split("/"))):
            raise WorkerError("INVALID_REQUEST")
        resource = (self.models_root / ref / "nvngx_dlssnr.dll").resolve()
        if not resource.is_relative_to(self.models_root):
            raise WorkerError("INVALID_REQUEST")
        if not resource.is_file():
            raise WorkerError("MODEL_NOT_FOUND", 404)
        if self.profile_id is not None:
            raise WorkerError("MODEL_BUSY", 409)
        error = ctypes.create_string_buffer(4096)
        if not self.bridge.dlss5nr_init(options["gpu_index"], str(resource.parent), self.caller_path, self.work_dir, error, len(error)):
            print("DLSS NR initialization failed: " + error.value.decode("utf-8", "replace"), flush=True)
            raise WorkerError("RUNTIME_DEVICE_UNAVAILABLE", 503)
        self.profile_id = value["profile_id"]
        return {"device_name": self.bridge.dlss5nr_gpu_name().decode("utf-8", "replace")}

    def process(self, value):
        fields(value, {"profile_id", "image", "options"})
        if self.profile_id is None or value["profile_id"] != self.profile_id:
            raise WorkerError("MODEL_NOT_FOUND", 404)
        options = controls(value["options"])
        data = base64.b64decode(value["image"], validate=True)
        with Image.open(io.BytesIO(data)) as image:
            if (image.format != "PNG" or image.mode != "RGBA" or getattr(image, "is_animated", False)
                    or max(image.size) > 16384 or image.width * image.height > MAX_PIXELS):
                raise WorkerError("INVALID_IMAGE")
            alpha = image.getchannel("A")
            rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
        output = np.empty_like(rgb)
        error = ctypes.create_string_buffer(4096)
        pointer = ctypes.POINTER(ctypes.c_float)
        ok = self.bridge.dlss5nr_process(rgb.ctypes.data_as(pointer), output.ctypes.data_as(pointer),
            rgb.shape[1], rgb.shape[0], STYLES[options["style"]], options["preset"],
            options["intensity"], options["tone"], options["structure"], options["skin"],
            int(options["auto_mask"]), 1, 0, error, len(error))
        if not ok:
            print("DLSS NR processing failed: " + error.value.decode("utf-8", "replace"), flush=True)
            raise WorkerError("MODEL_UNAVAILABLE", 503)
        if not np.isfinite(output).all():
            raise WorkerError("MODEL_UNAVAILABLE", 503)
        corrected = correct_channels(output, rgb, options["channel_order"])
        result = Image.fromarray(np.rint(np.clip(corrected, 0, 1) * 255).astype(np.uint8))
        result.putalpha(alpha)
        encoded = io.BytesIO()
        result.save(encoded, format="PNG")
        return encoded.getvalue()
