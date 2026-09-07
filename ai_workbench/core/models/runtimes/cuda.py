"""CUDA startup controls and diagnostics for the pinned llama-server release."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog


def llama_environment(directory: Path):
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTHON", "VIRTUAL_ENV", "LLAMA_ARG_"))
           and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}}
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
               TOKENIZERS_PARALLELISM="false")
    env["PATH"] = str(directory) + os.pathsep + env.get("PATH", "")
    return env


class LlamaCudaLog(RuntimeLog):
    # These two records are emitted by the pinned b10809 executable, before readiness.
    device_pattern = re.compile(r"^\s*(CUDA\d+):\s+(.+?)\s+\(\d+\s+MiB,.*\)\s*$")
    offload_pattern = re.compile(r"\bload_tensors:\s+offloaded (\d+)/(\d+) layers to GPU\b")

    def __init__(self, path, root, secrets=()):
        super().__init__(path, root, secrets)
        self.devices: list[tuple[str, str]] = []
        self.offload: tuple[int, int] | None = None
        self.offload_observed = asyncio.Event()

    def write(self, text):
        for line in text.splitlines():
            if match := self.device_pattern.fullmatch(line):
                device = (match[1], match[2][:256])
                if device not in self.devices:
                    self.devices.append(device)
            if match := self.offload_pattern.search(line):
                self.offload = (int(match[1]), int(match[2]))
                self.offload_observed.set()
        super().write(text)


async def probe_cuda_device(executable: Path, env: dict, log: LlamaCudaLog):
    process = await ManagedProcess.start([executable, "--list-devices"], env=env, cwd=executable.parent, log=log)
    try:
        try:
            code = await asyncio.wait_for(process.wait(), 30)
        except asyncio.TimeoutError as exc:
            raise ModelError("RUNTIME_DEVICE_UNAVAILABLE", "CUDA device detection timed out. Check the NVIDIA driver.", 503) from exc
    finally:
        await process.stop()
    if code or not log.devices:
        raise ModelError("RUNTIME_DEVICE_UNAVAILABLE", "No usable CUDA device was found. Check the NVIDIA GPU and driver.", 503)
    return log.devices[0]


def cuda_arguments(options, device_id):
    args = ["--device", device_id, "--split-mode", "none", "--main-gpu", 0,
            "--gpu-layers", options["gpu_layers"]]
    if options["gpu_layers"] == "auto":
        args.extend(["--fit", "on", "--fit-target", 1024, "--fit-ctx", options["context_size"]])
    else:
        args.extend(["--fit", "off"])
    return args


async def confirmed_offload(log: LlamaCudaLog):
    try:
        await asyncio.wait_for(log.offload_observed.wait(), 5)
    except asyncio.TimeoutError as exc:
        raise ModelError("MODEL_UNAVAILABLE", "CUDA startup did not confirm GPU layer offload. See the process log.", 503) from exc
    loaded, total = log.offload
    if not 1 <= loaded <= total:
        raise ModelError("MODEL_UNAVAILABLE", "No model layers fit on the selected GPU. Free GPU memory or adjust the model configuration.", 503)
    return loaded, total
