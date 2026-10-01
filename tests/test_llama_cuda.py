import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes.catalog import catalog
from ai_workbench.core.models.runtimes.cuda import CUDA_DLL_NAMES, TORCH_LIBRARY_PATH, cuda_arguments, llama_environment
from ai_workbench.core.models.runtimes.schema import NativeRuntime, LlamaCUDAOptions, RuntimeArtifact
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from tests.test_phase2b_runtime import archive_bytes, supervisor
from tests.test_runtime_maintenance import link_directory


def cuda_supervisor(root, *, main=None):
    cpu = archive_bytes({"bin/llama-server.exe": b"cpu fixture"})
    main = main if main is not None else archive_bytes({"bin/llama-server.exe": b"fixture"})
    native = NativeRuntime(artifact=RuntimeArtifact(url="https://runtime.test/cuda.zip",
        sha256=hashlib.sha256(main).hexdigest(), archive_format="zip", size_bytes=len(main)))
    requests = []

    def transport(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=cpu if request.url.path == "/cpu.zip" else main)

    service = supervisor(root, data=cpu)
    service.release.native_cpu.artifact.url = "https://runtime.test/cpu.zip"
    service.release.native_cuda = native
    service.transport = httpx.MockTransport(transport)

    async def command(args, env, cwd, log):
        assert args[1:] == ["--version"]
        assert Path(args[0]).is_file()
        if "cuda" in Path(args[0]).parts:
            directory = Path(env["PATH"].split(os.pathsep)[1])
            assert directory == Path(args[0]).parents[3] / "env" / TORCH_LIBRARY_PATH
            assert all((directory / name).is_file() and not (cwd / name).exists() for name in CUDA_DLL_NAMES)
        assert env["PATH"].startswith(str(cwd))

    service._command = command
    return service, requests, len(main)


def test_cuda_catalog_is_pinned_to_windows_x64_main_artifact():
    release = catalog("windows", "amd64")
    native = release.native_cuda
    assert release.supported and "b10809" in native.artifact.url and "cuda-12.4" in native.artifact.url
    assert native.artifact.sha256 == "c77bfcd9ed8d91e8721a2d6a290b907fddd4fa5412a47b21c6fa1709116b85f9"
    assert "dependencies" not in native.model_dump()
    assert LlamaCUDAOptions().gpu_layers == "auto"
    for system, machine in (("linux", "x86_64"), ("windows", "arm64"), ("darwin", "arm64")):
        assert not catalog(system, machine).supported


@pytest.mark.parametrize("value", [0, -1, 1000, True, 1.0, "1", "all", None])
def test_cuda_layers_reject_non_strict_or_out_of_range_values(value):
    with pytest.raises(ValidationError):
        ModelProfile(name='cuda', alias='cuda', kind='llm', model_ref='llms/model', source={'type': 'local', 'execution_options': {'device': 'cuda', 'gpu_layers': value}})


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
    original_path = os.environ["PATH"]
    directory = tmp_path / "shared CUDA libraries"
    env = llama_environment(tmp_path, directory)
    assert env["PATH"] == os.pathsep.join([str(tmp_path), str(directory), original_path])
    assert llama_environment(tmp_path)["PATH"] == str(tmp_path) + os.pathsep + original_path
    assert os.environ["PATH"] == original_path
    assert not {"LLAMA_ARG_N_GPU_LAYERS", "PYTHONPATH", "HTTP_PROXY"} & env.keys()


def test_cuda_shared_libraries_install_progress_repair_and_uninstall(tmp_path):
    async def scenario():
        service, requests, total = cuda_supervisor(tmp_path)
        preserved = tmp_path / "data/models/llms/keep/model.gguf"
        preserved.parent.mkdir(parents=True)
        preserved.write_bytes(b"cpu")
        job = await service.submit('install')
        await service.task
        assert service.store.job(job.id).state == "completed"
        assert requests == ["https://runtime.test/cpu.zip", "https://runtime.test/cuda.zip"]
        progress = [event.payload["job"] for event in service.events.list_events()
                    if event.type == "runtime_job_updated" and event.payload["job"]["stage"] == "downloading" and event.payload["job"]["progress_total"] == total]
        assert all(value["progress_total"] == total for value in progress)
        assert [value["progress_current"] for value in progress] == sorted(value["progress_current"] for value in progress)
        assert progress[-1]["progress_current"] == total
        service.assert_available()
        executable = service.executable("llama-server", "cuda")
        assert all(not (executable.parent / name).exists() for name in CUDA_DLL_NAMES)
        directory = service.cuda_directory()
        manifest = json.loads((service.directory() / "installation.json").read_text())
        assert manifest["dependencies"]["native_cuda"] == service.release.native_cuda.artifact.sha256
        assert set(manifest) == {"dependencies", "executables"}
        (directory / "cublas64_12.dll").write_bytes(b"changed")
        service.assert_available()
        await service.submit('repair')
        await service.task
        assert service.installation().state == "installed" and len(requests) == 2
        assert (directory / "cublas64_12.dll").read_bytes() == b"CUDA 12.8 fixture"
        await service.submit('uninstall')
        await service.task
        assert not executable.exists() and preserved.read_bytes() == b"cpu"
        assert (service.base / ".cache/cogita-artifacts" / service.release.native_cuda.artifact.sha256).is_file()
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["checksum", "missing_dll", "escaping_dll_directory"])
def test_cuda_artifact_or_shared_library_failure_never_promotes(tmp_path, failure):
    async def scenario():
        service, _, _ = cuda_supervisor(tmp_path)
        if failure == "checksum":
            service.release.native_cuda.artifact.sha256 = "0" * 64
        else:
            install = service._install_python
            async def incomplete(entry, target, job, log):
                await install(entry, target, job, log)
                directory = (target / entry.python_executable).parent / TORCH_LIBRARY_PATH
                if failure == "missing_dll":
                    (directory / CUDA_DLL_NAMES[0]).unlink()
                else:
                    outside = tmp_path / "outside"
                    directory.rename(outside)
                    link_directory(directory, outside)
            service._install_python = incomplete
        job = await service.submit('install')
        await service.task
        value = service.store.job(job.id)
        assert value.state == "failed"
        assert value.error_code == ("RUNTIME_CHECKSUM_MISMATCH" if failure == "checksum" else "RUNTIME_BROKEN")
        assert not service.directory().exists()
        assert not list((service.base / ".staging").iterdir())
        if failure == "escaping_dll_directory":
            assert (tmp_path / "outside" / CUDA_DLL_NAMES[0]).is_file()
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("damage", [*CUDA_DLL_NAMES, "escaping_directory"])
def test_shared_cuda_library_damage_blocks_entry_and_restoring_recovers(tmp_path, damage):
    async def scenario():
        service, _, _ = cuda_supervisor(tmp_path)
        await service.submit('install')
        await service.task
        directory = service.cuda_directory()
        original = service.store.installations()
        if damage == "escaping_directory":
            outside = tmp_path / "outside"
            directory.rename(outside)
            link_directory(directory, outside)
        else:
            (directory / damage).unlink()
        assert service.installation().state == "broken"
        with pytest.raises(ModelError) as error:
            service.executable("llama-server", "cuda")
        assert error.value.code == "RUNTIME_BROKEN"
        assert service.store.installations() == original
        if damage == "escaping_directory":
            directory.rmdir() if os.name == "nt" else directory.unlink()
            outside.rename(directory)
        else:
            (directory / damage).write_bytes(b"restored")
        assert service.installation().state == "installed"
        await service.close()
    asyncio.run(scenario())


def test_cuda_cancel_during_main_download_cleans_staging(tmp_path):
    async def scenario():
        service, _, _ = cuda_supervisor(tmp_path)
        cpu = archive_bytes({"bin/llama-server.exe": b"cpu fixture"})
        started, closed = asyncio.Event(), asyncio.Event()

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"partial"
                started.set()
                await asyncio.Event().wait()

            async def aclose(self):
                closed.set()

        service.transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream())
            if request.url.path == "/cuda.zip" else httpx.Response(200, content=cpu))
        job = await service.submit('install')
        await asyncio.wait_for(started.wait(), 5)
        result = await service.cancel(job.id)
        assert result.state == "cancelled" and closed.is_set()
        assert service.active_job is None and not service.directory().exists()
        assert not list((service.base / ".staging").iterdir())
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("device,offload,expected", [(True, 4, None), (False, None, "RUNTIME_DEVICE_UNAVAILABLE"),
                                                     (True, 0, "MODEL_UNAVAILABLE"), (True, None, "MODEL_UNAVAILABLE")])
def test_cuda_startup_requires_device_and_positive_offload_and_releases_processes(tmp_path, monkeypatch, device, offload, expected):
    from ai_workbench.core.models.runtimes.process import ManagedProcess

    async def scenario():
        service, _, _ = cuda_supervisor(tmp_path)
        await service.submit('install')
        await service.task
        weight = tmp_path / "data/models/llms/fixture/model.gguf"
        weight.parent.mkdir(parents=True)
        weight.write_bytes(b"fixture")
        manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=service)
        profile = manager.profiles.create(ModelProfile(name='cuda', alias='cuda', kind='llm', model_ref='llms/fixture', source={'type': 'local'}))
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
            assert env["PATH"].split(os.pathsep)[:2] == [str(cwd), str(service.cuda_directory())]
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
            def handle(request):
                if request.url.path.endswith("/models"):
                    body = {"data": [{"id": "managed"}]}
                elif request.url.path == "/props":
                    body = {"chat_template": "Fixture template"}
                elif request.url.path == "/apply-template":
                    body = {"prompt": "Fixture prompt"}
                else:
                    body = {"status": "ok"}
                return httpx.Response(200, json=body)
            kwargs["transport"] = httpx.MockTransport(handle)
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
            assert args[args.index("--fit-ctx") + 1] == manager.profile(profile.id).source.execution_options["context_size"]
            await manager.unload(profile.id)
            assert manager.status(profile.id).runtime.device_name is None
        assert all(process.stopping for process in processes)
        assert not list((service.base / ".processes").iterdir())
        await manager.close()
        await service.close()

    asyncio.run(scenario())
