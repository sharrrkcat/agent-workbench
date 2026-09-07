import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from ai_workbench.core.events import EventBus
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes.catalog import catalog
from ai_workbench.core.models.runtimes.cuda import cuda_arguments, llama_environment
from ai_workbench.core.models.runtimes.schema import CatalogEntry, LlamaCUDAOptions, RuntimeArtifact
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from tests.test_phase2b_runtime import archive_bytes


def cuda_supervisor(root, *, main=None, extra=None):
    main = main if main is not None else archive_bytes({"bin/llama-server.exe": b"fixture"})
    extra = extra if extra is not None else archive_bytes({"nested/cublas64_12.dll": b"cuda", "LICENSE": b"license"})
    dependency = RuntimeArtifact(url="https://runtime.test/cudart.zip", sha256=hashlib.sha256(extra).hexdigest(),
                                 archive_format="zip", size_bytes=len(extra))
    entry = CatalogEntry(runtime_id="llama-server", variant="cuda", version="fixture", platform="windows", supported=True,
        url="https://runtime.test/cuda.zip", sha256=hashlib.sha256(main).hexdigest(), archive_format="zip",
        executable="llama-server.exe", kinds=["llm"], size_bytes=len(main), additional_artifacts=[dependency])
    requests = []

    def transport(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=extra if request.url.path == "/cudart.zip" else main)

    service = RuntimeSupervisor(root, RuntimeStore(), EventBus(), [entry], httpx.MockTransport(transport))

    async def command(args, env, cwd, log):
        assert args[1:] == ["--version"]
        assert Path(args[0]).is_file() and (Path(args[0]).parent / "cublas64_12.dll").is_file()
        assert env["PATH"].startswith(str(cwd))

    service._command = command
    return service, requests, len(main) + len(extra)


def test_cuda_catalog_is_pinned_to_windows_x64_and_two_artifacts():
    entry = next(entry for entry in catalog("windows", "amd64") if entry.variant == "cuda")
    assert entry.supported and entry.version == "b10809" and len(entry.additional_artifacts) == 1
    assert entry.sha256 == "c77bfcd9ed8d91e8721a2d6a290b907fddd4fa5412a47b21c6fa1709116b85f9"
    assert entry.additional_artifacts[0].sha256 == "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"
    assert entry.options_schema["properties"]["gpu_layers"]["default"] == "auto"
    for system, machine in (("linux", "x86_64"), ("windows", "arm64"), ("darwin", "arm64")):
        assert not next(entry for entry in catalog(system, machine) if entry.variant == "cuda").supported
    assert not any(entry.supported for entry in catalog("windows", "amd64") if entry.variant in {"vulkan", "torch-cu128", "onnx-gpu"})


@pytest.mark.parametrize("value", [0, -1, 1000, True, 1.0, "1", "all", None])
def test_cuda_layers_reject_non_strict_or_out_of_range_values(value):
    with pytest.raises(ValidationError):
        ModelProfile(name="cuda", alias="cuda", kind="llm", runtime_id="llama-server", runtime_variant="cuda",
                     model_ref="llms/model.gguf", runtime_options={"gpu_layers": value})


def test_cuda_defaults_and_manual_arguments_preserve_context_and_device(tmp_path, monkeypatch):
    automatic = LlamaCUDAOptions(context_size=8192).model_dump()
    args = cuda_arguments(automatic, "CUDA2")
    assert args == ["--device", "CUDA2", "--split-mode", "none", "--main-gpu", 0,
                    "--gpu-layers", "auto", "--fit", "on", "--fit-target", 1024, "--fit-ctx", 8192]
    manual = cuda_arguments(LlamaCUDAOptions(gpu_layers=7).model_dump(), "CUDA0")
    assert manual[-4:] == ["--gpu-layers", 7, "--fit", "off"]
    assert "--fit-ctx" not in manual
    monkeypatch.setenv("LLAMA_ARG_N_GPU_LAYERS", "0")
    monkeypatch.setenv("PYTHONPATH", "outside")
    monkeypatch.setenv("HTTP_PROXY", "http://unused")
    import os
    original_path = os.environ["PATH"]
    env = llama_environment(tmp_path)
    assert env["PATH"].startswith(str(tmp_path)) and os.environ["PATH"] == original_path
    assert not {"LLAMA_ARG_N_GPU_LAYERS", "PYTHONPATH", "HTTP_PROXY"} & env.keys()


def test_cuda_dual_artifact_install_progress_manifest_and_uninstall(tmp_path):
    async def scenario():
        service, requests, total = cuda_supervisor(tmp_path)
        preserved = tmp_path / "data/runtimes/llama-server/fixture/cpu/keep"
        preserved.parent.mkdir(parents=True)
        preserved.write_bytes(b"cpu")
        job = await service.submit("llama-server", "cuda", "install")
        await service.task
        assert service.store.job(job.id).state == "completed"
        assert requests == ["https://runtime.test/cuda.zip", "https://runtime.test/cudart.zip"]
        progress = [event.payload["job"] for event in service.events.list_events()
                    if event.type == "runtime_job_updated" and event.payload["job"]["stage"] == "downloading"]
        assert all(value["progress_total"] == total for value in progress)
        assert [value["progress_current"] for value in progress] == sorted(value["progress_current"] for value in progress)
        assert progress[-1]["progress_current"] == total
        executable = await service.verify(service.entries[0])
        assert (executable.parent / "cublas64_12.dll").read_bytes() == b"cuda"
        manifest = json.loads((service.directory(service.entries[0]) / "installation.json").read_text())
        assert manifest["additional_artifact_sha256"] == [service.entries[0].additional_artifacts[0].sha256]
        assert "bin/cublas64_12.dll" in manifest["files"] and "dependencies/1/LICENSE" in manifest["files"]
        (executable.parent / "cublas64_12.dll").write_bytes(b"changed")
        with pytest.raises(ModelError) as invalid:
            await service.verify(service.entries[0])
        assert invalid.value.code == "RUNTIME_BROKEN"
        await service.submit("llama-server", "cuda", "uninstall")
        await service.task
        assert not executable.exists() and preserved.read_bytes() == b"cpu"
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["checksum", "collision", "missing_dll"])
def test_cuda_additional_artifact_failure_never_promotes(tmp_path, failure):
    async def scenario():
        main = archive_bytes({"bin/llama-server.exe": b"fixture", "bin/cublas64_12.dll": b"conflict"}) if failure == "collision" else None
        extra = archive_bytes({"LICENSE": b"license"}) if failure == "missing_dll" else None
        service, _, _ = cuda_supervisor(tmp_path, main=main, extra=extra)
        if failure == "checksum":
            service.entries[0].additional_artifacts[0].sha256 = "0" * 64
        job = await service.submit("llama-server", "cuda", "install")
        await service.task
        value = service.store.job(job.id)
        assert value.state == "failed"
        assert value.error_code == ("RUNTIME_CHECKSUM_MISMATCH" if failure == "checksum" else "RUNTIME_BROKEN")
        assert not service.directory(service.entries[0]).exists()
        assert not list((service.base / ".staging").iterdir())
        await service.close()
    asyncio.run(scenario())


def test_cuda_cancel_during_second_download_cleans_both_artifacts(tmp_path):
    async def scenario():
        service, _, _ = cuda_supervisor(tmp_path)
        first = archive_bytes({"bin/llama-server.exe": b"fixture"})
        started, closed = asyncio.Event(), asyncio.Event()

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"partial"
                started.set()
                await asyncio.Event().wait()

            async def aclose(self):
                closed.set()

        service.transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream())
            if request.url.path == "/cudart.zip" else httpx.Response(200, content=first))
        job = await service.submit("llama-server", "cuda", "install")
        await asyncio.wait_for(started.wait(), 5)
        result = await service.cancel(job.id)
        assert result.state == "cancelled" and closed.is_set()
        assert service.active_job is None and not service.directory(service.entries[0]).exists()
        assert not list((service.base / ".staging").iterdir())
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("device,offload,expected", [(True, 4, None), (False, None, "RUNTIME_DEVICE_UNAVAILABLE"),
                                                     (True, 0, "MODEL_UNAVAILABLE"), (True, None, "MODEL_UNAVAILABLE")])
def test_cuda_startup_requires_device_and_positive_offload_and_releases_processes(tmp_path, monkeypatch, device, offload, expected):
    from ai_workbench.core.models.runtimes.process import ManagedProcess

    async def scenario():
        service, _, _ = cuda_supervisor(tmp_path)
        await service.submit("llama-server", "cuda", "install")
        await service.task
        weight = tmp_path / "data/models/llms/fixture.gguf"
        weight.parent.mkdir(parents=True)
        weight.write_bytes(b"fixture")
        manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=service)
        profile = manager.profiles.create(ModelProfile(name="cuda", alias="cuda", kind="llm", model_ref="llms/fixture.gguf",
            runtime_id="llama-server", runtime_variant="cuda"))
        processes = []

        class Process:
            def __init__(self, probe, args):
                self.process = self
                self.probe, self.args, self.stopping = probe, args, False
                self.returncode = 0 if probe else None
                self.exited = asyncio.Event()

            async def wait(self):
                if not self.probe:
                    await self.exited.wait()
                return 0

            async def stop(self):
                self.stopping, self.returncode = True, 0
                self.exited.set()

        async def start(args, *, env, cwd, log):
            probe = "--list-devices" in args
            process = Process(probe, args)
            processes.append(process)
            if probe and device:
                log.write("Available devices:\n  CUDA0: First GPU (4096 MiB, 3072 MiB free)\n  CUDA1: Second GPU (8192 MiB, 6144 MiB free)")
            if not probe:
                assert args[args.index("--log-verbosity") + 1] == 4
                assert args[args.index("--log-colors") + 1] == "off"
                log.write(f"load_tensors: offloaded {offload}/8 layers to GPU")
            return process

        real_client = httpx.AsyncClient

        def client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(200,
                json={"data": [{"id": "managed"}]} if request.url.path.endswith("/models") else {"status": "ok"}))
            return real_client(*args, **kwargs)

        monkeypatch.setattr(ManagedProcess, "start", start)
        monkeypatch.setattr(httpx, "AsyncClient", client)
        assert manager.status(profile.id).runtime.device_name is None and not processes
        if expected:
            with pytest.raises(ModelError) as failure:
                await manager.load(profile.id)
            assert failure.value.code == expected
            status = manager.status(profile.id)
            assert status.state == "failed" and status.error_code == expected
            assert status.runtime.device_name is None
        else:
            status = await manager.load(profile.id)
            assert status.runtime.device_name == "First GPU" and status.runtime.gpu_layers_loaded == 4
            assert manager.status(profile.id).runtime.gpu_layers_loaded == 4
            args = processes[-1].args
            assert args[args.index("--device") + 1] == "CUDA0"
            assert args[args.index("--fit-ctx") + 1] == profile.runtime_options["context_size"]
            await manager.unload(profile.id)
            assert manager.status(profile.id).runtime.device_name is None
        assert all(process.stopping for process in processes)
        assert not list((service.base / ".processes").iterdir())
        await manager.close()
        await service.close()

    asyncio.run(scenario())
