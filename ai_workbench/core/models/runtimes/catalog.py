from __future__ import annotations

import hashlib
import platform
from pathlib import Path

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import CatalogEntry, PythonOptions, RuntimeArtifact, llama_options

CATALOG_ROOT = Path(__file__).parent
LLAMA_VERSION = "b10809"
WORKER_VERSION = "1.0.0"
PYTHON_VERSION = "3.12.11"
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


def worker_digest(root: Path | None = None) -> str:
    root = root or CATALOG_ROOT.parents[2] / "workers"
    digest = hashlib.sha256()
    for source in sorted(root.glob("*.py")):
        digest.update(source.name.encode("utf-8"))
        digest.update(source.read_text(encoding="utf-8").encode("utf-8"))
    return digest.hexdigest()


def catalog(os_name: str | None = None, machine: str | None = None) -> list[CatalogEntry]:
    os_name = os_name or platform.system().lower()
    machine = (machine or platform.machine()).lower()
    x64 = machine in {"amd64", "x86_64"}
    result = []
    for variant in ("cpu", "cuda", "vulkan"):
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
    for variant in ("torch-cpu", "torch-cu128", "onnx-gpu"):
        lock = CATALOG_ROOT / f"requirements-{os_name}.lock"
        supported = x64 and os_name in {"windows", "linux"} and variant == "torch-cpu" and lock.is_file()
        result.append(CatalogEntry(
            runtime_id="python-worker", variant=variant, version=WORKER_VERSION,
            platform=os_name, supported=supported,
            reason=None if supported else "RUNTIME_UNSUPPORTED", archive_format="venv",
            executable="Scripts/python.exe" if os_name == "windows" else "bin/python",
            requirements=lock.name if supported else None,
            sha256=text_digest(lock) if supported else None,
            worker_sha256=worker_digest() if supported else None,
            python_version=PYTHON_VERSION, kinds=["embedding", "reranker", "image_embedding", "vision"],
            options_schema=PythonOptions.model_json_schema()))
    return result


def find_entry(entries: list[CatalogEntry], runtime_id: str, variant: str) -> CatalogEntry:
    for entry in entries:
        if (entry.runtime_id, entry.variant) == (runtime_id, variant):
            return entry
    raise ModelError("RUNTIME_UNSUPPORTED", "Unknown runtime or variant.", 422)
