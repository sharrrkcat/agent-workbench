from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
import re

from ai_workbench.core.models.runtimes.schema import LocalRelease, NativeRuntime, RuntimeArtifact

CATALOG_ROOT = Path(__file__).parent
WORKER_ROOT = CATALOG_ROOT.resolve().parents[2] / "workers"
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


def requirements_digest(path: Path) -> str:
    """Identify exact package pins and their allowed artifacts, independent of formatting."""
    packages = {}
    requirement = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.partition("#")[0].strip()
        if not line:
            continue
        continued = line.endswith("\\")
        requirement += line.removesuffix("\\").strip() + " "
        if continued:
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]*)\s*==\s*([A-Za-z0-9][A-Za-z0-9.!+_-]*)\s+(.+)", requirement.strip())
        if match is None:
            raise ValueError("Runtime requirements must use exact package pins with SHA-256 hashes")
        name, version, hashes = match.groups()
        name = re.sub(r"[-_.]+", "-", name).lower()
        hashes = hashes.split()
        if name in packages or not all(re.fullmatch(r"--hash=sha256:[a-f0-9]{64}", item) for item in hashes):
            raise ValueError("Runtime requirements must have unique package pins and SHA-256 hashes")
        packages[name] = (version, sorted({item.removeprefix("--hash=sha256:") for item in hashes}))
        requirement = ""
    if requirement or not packages:
        raise ValueError("Runtime requirements are empty or have an unfinished continuation")
    contents = json.dumps(sorted(packages.items()), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(contents).hexdigest()


def worker_entrypoint(engine: str) -> str:
    if engine == "sentence-transformers":
        return "embedding_server.py"
    if engine == "siglip2":
        return "siglip_server.py"
    if engine == "transformers":
        return "transformers_server.py"
    return "server.py" if engine in {"kokoro", "wd14"} else "audio_server.py"


def catalog(os_name: str | None = None, machine: str | None = None) -> LocalRelease:
    os_name = os_name or platform.system().lower()
    machine = (machine or platform.machine()).lower()
    supported = os_name == "windows" and machine in {"amd64", "x86_64"}
    lock = CATALOG_ROOT / "requirements-local-windows.lock"
    return LocalRelease(
        version=LOCAL_VERSION, platform=os_name, supported=supported,
        reason=None if supported else "RUNTIME_UNSUPPORTED", python_version=PYTHON_VERSION,
        requirements=lock.name if supported else None, requirements_sha256=requirements_digest(lock) if supported else None,
        python_artifact=PYTHON_ARTIFACT if supported else None,
        native_cpu=NativeRuntime(artifact=LLAMA_CPU) if supported else None,
        native_cuda=NativeRuntime(artifact=LLAMA_CUDA, dependencies=[LLAMA_CUDA_DLLS]) if supported else None,
    )
