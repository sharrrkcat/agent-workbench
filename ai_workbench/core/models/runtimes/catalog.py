from __future__ import annotations

import hashlib
import platform
from pathlib import Path

from ai_workbench.core.models.runtimes.schema import LocalRelease, NativeRuntime, RuntimeArtifact

CATALOG_ROOT = Path(__file__).parent
LOCAL_VERSION = "1.0.0"
LLAMA_VERSION = "b10809"
PYTHON_VERSION = "3.12.11"
PYTHON_ARTIFACT = RuntimeArtifact(
    url="https://github.com/astral-sh/python-build-standalone/releases/download/20251007/cpython-3.12.11%2B20251007-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
    sha256="d2877f74b01871c82d140a9eefe57b18185c7a84128727cbedcae45dc5c9e54f", archive_format="tar.gz")
LLAMA_CPU = RuntimeArtifact(
    url=f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_VERSION}/llama-b10809-bin-win-cpu-x64.zip",
    sha256="9df3158ed228a641a4b127942d7f459f24c9e13f04682659d05c00c80099b6b5", archive_format="zip")
LLAMA_CUDA = RuntimeArtifact(
    url=f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_VERSION}/llama-b10809-bin-win-cuda-12.4-x64.zip",
    sha256="c77bfcd9ed8d91e8721a2d6a290b907fddd4fa5412a47b21c6fa1709116b85f9",
    archive_format="zip", size_bytes=253938543)
LLAMA_CUDA_DLLS = RuntimeArtifact(
    url=f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_VERSION}/cudart-llama-bin-win-cuda-12.4-x64.zip",
    sha256="8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    archive_format="zip", size_bytes=391443627)
WORKER_FILES = ["common.py", "timing.py", "server.py", "protocol.py", "tts_engine.py", "tts_catalog.py",
                "audio.py", "audio_catalog.py", "audio_engine.py", "audio_server.py",
                "transformers_server.py", "transformers_engine.py"]


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


def worker_entrypoint(engine: str) -> str:
    if engine == "transformers":
        return "transformers_server.py"
    return "server.py" if engine == "kokoro" else "audio_server.py"


def catalog(os_name: str | None = None, machine: str | None = None) -> LocalRelease:
    os_name = os_name or platform.system().lower()
    machine = (machine or platform.machine()).lower()
    supported = os_name == "windows" and machine in {"amd64", "x86_64"}
    lock = CATALOG_ROOT / "requirements-local-windows.lock"
    return LocalRelease(
        version=LOCAL_VERSION, platform=os_name, supported=supported,
        reason=None if supported else "RUNTIME_UNSUPPORTED", python_version=PYTHON_VERSION,
        requirements=lock.name if supported else None, lock_sha256=text_digest(lock) if supported else None,
        worker_files=WORKER_FILES, worker_sha256=worker_digest(WORKER_FILES),
        python_artifact=PYTHON_ARTIFACT if supported else None,
        native_cpu=NativeRuntime(artifact=LLAMA_CPU) if supported else None,
        native_cuda=NativeRuntime(artifact=LLAMA_CUDA, dependencies=[LLAMA_CUDA_DLLS]) if supported else None,
    )
