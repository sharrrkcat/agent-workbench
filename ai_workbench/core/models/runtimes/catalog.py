from __future__ import annotations

import hashlib
import platform
from pathlib import Path

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import AudioOptions, CatalogEntry, OnnxCPUOptions, TransformersOptions, RuntimeArtifact, llama_options

CATALOG_ROOT = Path(__file__).parent
LLAMA_VERSION = "b10809"
ONNX_VERSION = "1.0.2"
TRANSFORMERS_VERSION = "1.0.2"
AUDIO_VERSION = "1.1.2"
PYTHON_VERSION = "3.12.11"
# Exact interpreter artifacts selected by the application's pinned uv 0.11.8.
PYTHON_ARTIFACTS = {
    "windows": RuntimeArtifact(
        url="https://github.com/astral-sh/python-build-standalone/releases/download/20251007/cpython-3.12.11%2B20251007-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
        sha256="d2877f74b01871c82d140a9eefe57b18185c7a84128727cbedcae45dc5c9e54f", archive_format="tar.gz"),
    "linux": RuntimeArtifact(
        url="https://github.com/astral-sh/python-build-standalone/releases/download/20251007/cpython-3.12.11%2B20251007-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
        sha256="f98121eb1fb2b05a25c1f3d2fe7cf08c3a2468c350785df3d84c2516e7280d3f", archive_format="tar.gz"),
}
ONNX_FILES = ["common.py", "timing.py", "server.py", "protocol.py", "tts_engine.py", "tts_catalog.py", "audio.py"]
TRANSFORMERS_FILES = ["common.py", "timing.py", "transformers_server.py", "transformers_engine.py"]
AUDIO_FILES = ["common.py", "timing.py", "server.py", "protocol.py", "tts_catalog.py", "audio.py",
               "audio_catalog.py", "audio_engine.py", "audio_server.py"]
# GitHub release asset digests, verified from ggml-org/llama.cpp b10809.
LLAMA_ASSETS = {
    "windows": ("llama-b10809-bin-win-cpu-x64.zip", "9df3158ed228a641a4b127942d7f459f24c9e13f04682659d05c00c80099b6b5", "llama-server.exe"),
    "linux": ("llama-b10809-bin-ubuntu-x64.tar.gz", "5e34434ddc6d03cd1584f403201aff0d4bd1a5793a72ff7e286532dfd1e4b941", "llama-server"),
}
LLAMA_CUDA_ASSET = RuntimeArtifact(
    url=f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_VERSION}/llama-b10809-bin-win-cuda-12.4-x64.zip",
    sha256="c77bfcd9ed8d91e8721a2d6a290b907fddd4fa5412a47b21c6fa1709116b85f9",
    archive_format="zip", size_bytes=253938543)
LLAMA_CUDA_DLLS = RuntimeArtifact(
    url=f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_VERSION}/cudart-llama-bin-win-cuda-12.4-x64.zip",
    sha256="8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    archive_format="zip", size_bytes=391443627)


def text_digest(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def worker_digest(files: list[str], root: Path | None = None) -> str:
    root = root or CATALOG_ROOT.parents[2] / "workers"
    digest = hashlib.sha256()
    for name in sorted(files):
        source = root / name
        digest.update(source.name.encode("utf-8"))
        digest.update(source.read_text(encoding="utf-8").encode("utf-8"))
    return digest.hexdigest()


def catalog(os_name: str | None = None, machine: str | None = None) -> list[CatalogEntry]:
    os_name = os_name or platform.system().lower()
    machine = (machine or platform.machine()).lower()
    x64 = machine in {"amd64", "x86_64"}
    result = []
    for variant in ("cpu", "cuda"):
        asset = LLAMA_ASSETS.get(os_name)
        cuda = os_name == "windows" and variant == "cuda"
        supported = x64 and (cuda or asset is not None and variant == "cpu")
        result.append(CatalogEntry(
            runtime_id="llama-server", variant=variant, version=LLAMA_VERSION,
            platform=os_name, supported=supported,
            reason=None if supported else "RUNTIME_UNSUPPORTED",
            url=LLAMA_CUDA_ASSET.url if cuda else f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_VERSION}/{asset[0]}" if asset and variant == "cpu" else None,
            sha256=LLAMA_CUDA_ASSET.sha256 if cuda else asset[1] if asset and variant == "cpu" else None,
            size_bytes=LLAMA_CUDA_ASSET.size_bytes if cuda else None,
            additional_artifacts=[LLAMA_CUDA_DLLS] if cuda else [],
            archive_format="zip" if os_name == "windows" else "tar.gz",
            executable=asset[2] if asset else "llama-server",
            kinds=["llm"], options_schema=llama_options(variant).model_json_schema()))
    for variant in ("onnx-cpu", "transformers-cuda", "infinity-cuda", "audio-cuda"):
        onnx = variant == "onnx-cpu"
        transformers = variant == "transformers-cuda"
        audio = variant == "audio-cuda"
        implemented = onnx or transformers or audio
        family = "onnx" if onnx else "audio" if audio else "transformers"
        lock = CATALOG_ROOT / f"requirements-{family}-{os_name}.lock"
        supported = x64 and lock.is_file() and (onnx and os_name in {"windows", "linux"} or (transformers or audio) and os_name == "windows")
        files = ONNX_FILES if onnx else TRANSFORMERS_FILES if transformers else AUDIO_FILES if audio else []
        kinds = {"onnx-cpu": ["tts"], "transformers-cuda": ["llm"],
                 "infinity-cuda": ["embedding", "reranker", "image_embedding"], "audio-cuda": ["tts"]}[variant]
        result.append(CatalogEntry(
            runtime_id="python-worker", variant=variant,
            version=ONNX_VERSION if onnx else TRANSFORMERS_VERSION if transformers else AUDIO_VERSION if audio else "pending",
            platform=os_name, supported=supported,
            reason=None if supported else "RUNTIME_UNSUPPORTED" if implemented else "RUNTIME_NOT_IMPLEMENTED", archive_format="venv",
            executable="Scripts/python.exe" if os_name == "windows" else "bin/python",
            requirements=lock.name if supported else None,
            sha256=text_digest(lock) if supported else None,
            worker_sha256=worker_digest(files) if supported else None,
            worker_files=files, worker_entrypoint="server.py" if onnx else "transformers_server.py" if transformers else "audio_server.py" if audio else None,
            python_version=PYTHON_VERSION if implemented else None,
            python_key=f"cpython-{PYTHON_VERSION}-{os_name}-x86_64-{'none' if os_name == 'windows' else 'gnu'}" if supported else None,
            python_artifact=PYTHON_ARTIFACTS.get(os_name) if supported else None,
            pytorch_index_url="https://download.pytorch.org/whl/cu128" if transformers else "https://download.pytorch.org/whl/cu124" if audio else None,
            kinds=kinds,
            options_schema=(OnnxCPUOptions if onnx else AudioOptions if audio else TransformersOptions).model_json_schema() if implemented else {}))
    return result


def find_entry(entries: list[CatalogEntry], runtime_id: str, variant: str) -> CatalogEntry:
    for entry in entries:
        if (entry.runtime_id, entry.variant) == (runtime_id, variant):
            return entry
    raise ModelError("RUNTIME_UNSUPPORTED", "Unknown runtime or variant.", 422)
