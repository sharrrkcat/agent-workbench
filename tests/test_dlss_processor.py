"""Processor API and bundled-component boundaries without GPU or model imports."""
import asyncio
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
import pytest
from pydantic import ValidationError
from sqlalchemy import text

from ai_workbench.api.main import create_app
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.inspection import inspect_processor
from ai_workbench.core.models.inventory import inventory
from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.processing import prepare_process_image, validate_process_output
from ai_workbench.core.models.runtimes.schema import ComponentInstallation, RuntimeJob
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.schema import ImageProcessRequest, ModelProfile, ProcessorParameters
from ai_workbench.core.models.store import ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine
from tests.test_phase2b_runtime import supervisor

REF = "processors/dlss5-nr"


def profile(**values):
    return ModelProfile(**{ "name": "DLSS", "alias": "dlss", "kind": "processor", "model_ref": REF,
        "external_enabled": True, **values})


def image_bytes(size=(17, 13), mode="RGBA", format="PNG", **kwargs):
    image = Image.new(mode, size, (210, 40, 10, 91) if mode == "RGBA" else (210, 40, 10))
    output = BytesIO()
    image.save(output, format, **kwargs)
    return output.getvalue()


async def component_service(tmp_path, store=None):
    service = supervisor(tmp_path, store=store)
    manager = ModelManager(ModelProfileStore(store.engine if store else None), ProviderProfileStore(),
        ModelSettingsStore(), runtime_supervisor=service)
    await service.submit("install")
    await service.task
    async def check(args, env, cwd, log):
        assert args[1:3] == ["-I", "-B"] and args[4] == "--self-check"
        assert all(Path(args[i]).is_file() for i in (0, 3, 5, 6))
        assert not (tmp_path / "data/models" / REF / "nvngx_dlssnr.dll").exists()
    service._command = check
    return service, manager


@pytest.mark.parametrize("memory", [True, False])
def test_component_lifecycle_bootstrap_and_independent_identity(tmp_path, memory):
    async def scenario():
        engine = None if memory else get_engine(f"sqlite:///{tmp_path / 'app.db'}")
        if engine:
            migrations.upgrade(engine)
        service, manager = await component_service(tmp_path, RuntimeStore(engine))
        base = service.installation().model_dump()
        resources = tmp_path / "data/models" / REF
        resources.mkdir(parents=True)
        witness = resources / "keep.txt"
        witness.write_text("user resource")
        manager.profiles.create(profile(alias="dlss5-nr"))
        try:
            job = await service.submit("install", "dlss5nr")
            await service.task
            assert service.store.job(job.id).state == "completed"
            value = service.component()
            default = manager.profiles.get(value.default_profile_id)
            assert default.alias == "dlss5-nr-2" and default.name == "DLSS 5 NR"
            assert default.source.execution_options == {"device": "d3d12", "gpu_index": 0}
            assert default.source.lifecycle.unload == "manual" and not default.external_enabled
            assert default.parameters == ProcessorParameters().model_dump()
            assert manager.status(default.id).error_code == "MODEL_NOT_FOUND"
            assert not manager._slots and service.installation().model_dump() == base
            manager.profiles.update(default.id, {"name": "Edited", "alias": "edited", "parameters": {"intensity": 0}})
            repeated = await service.submit("install", "dlss5nr")
            assert repeated.stage == "already_installed"
            assert manager.profiles.get(default.id).parameters["intensity"] == 0
            await service.submit("repair", "dlss5nr")
            await service.task
            assert manager.profiles.get(default.id).name == "Edited"
            assert service.installation().model_dump() == base
            entry = service.component_entries()["bridge"]
            entry.unlink()
            assert service.component().state == "broken" and service.installation().state == "installed"
            with pytest.raises(ModelError, match="Install or repair"):
                await service.submit("install", "dlss5nr")
            await service.submit("repair", "dlss5nr")
            await service.task
            assert entry.is_file()
            manager.profiles.delete(default.id)
            await service.submit("install", "dlss5nr")
            recreated = manager.profiles.get(service.component().default_profile_id)
            assert recreated.id != default.id and recreated.alias == "dlss5-nr-2"
            await service.submit("uninstall", "dlss5nr")
            await service.task
            assert service.component().state == "not_installed" and not entry.exists()
            assert witness.read_text() == "user resource" and manager.profiles.get(recreated.id)
            await service.submit("install", "dlss5nr")
            await service.task
            async def native_check(args, *_args):
                assert args[1:] == ["--version"]
            service._command = native_check
            await service.submit("repair")
            await service.task
            assert service.component().state == "installed" and entry.is_file()
            await service.submit("uninstall")
            await service.task
            assert not entry.exists() and witness.read_text() == "user resource"
            assert service.component().state == service.installation().state == "not_installed"
        finally:
            await manager.close()
            await service.close()
    asyncio.run(scenario())


def test_component_archive_self_check_cancellation_and_restart(tmp_path):
    async def scenario():
        service, manager = await component_service(tmp_path)
        original = service.component_release
        service.component_release = original.model_copy(update={"archive_sha256": "0" * 64})
        job = await service.submit("install", "dlss5nr")
        await service.task
        assert service.store.job(job.id).error_code == "RUNTIME_CHECKSUM_MISMATCH"
        assert service.installation().state == "installed" and not manager.profiles.list()
        service.component_release = original
        entered = asyncio.Event()
        async def wait_check(*_args):
            entered.set()
            await asyncio.Future()
        service._command = wait_check
        job = await service.submit("repair", "dlss5nr")
        await entered.wait()
        with pytest.raises(ModelError) as busy:
            await service.submit("repair")
        assert busy.value.code == "RUNTIME_INSTALLING"
        await service.cancel(job.id)
        assert service.store.job(job.id).state == "cancelled" and not service.blocked
        assert not (service.base / ".staging" / job.id).exists()
        assert service.installation().state == "installed"
        interrupted = RuntimeJob(component_id="dlss5nr", version="0.1.1", operation="install", state="running")
        service.store.save_job(interrupted)
        service.store.save_component(ComponentInstallation(version="0.1.1", state="installing", job_id=interrupted.id))
        staging = service.base / ".staging" / interrupted.id
        staging.mkdir(parents=True)
        restarted = RuntimeSupervisor(tmp_path, service.store, service.settings, release=service.release)
        assert restarted.component().state == "interrupted" and not staging.exists()
        assert restarted.installation().state == "installed"
        await manager.close()
        await restarted.close()
    asyncio.run(scenario())


def test_component_update_and_entry_containment(tmp_path):
    async def scenario():
        service, manager = await component_service(tmp_path)
        await service.submit('install', 'dlss5nr')
        await service.task
        value = service.component()
        original_id = value.default_profile_id
        old = service.component_directory('0.1.0')
        current = service.component_directory(value.version)
        assert old.resolve().is_relative_to(service.base.resolve()) and current.resolve().is_relative_to(service.base.resolve())
        current.rename(old)
        marker = old / 'installation.json'
        manifest = json.loads(marker.read_text())
        manifest['version'] = value.version = '0.1.0'
        marker.write_text(json.dumps(manifest))
        from ai_workbench.core.models.runtimes.supervisor import sha256
        value.manifest_sha256 = sha256(marker)
        service.store.save_component(value)
        await service.submit('install', 'dlss5nr')
        await service.task
        assert service.component().version == '0.1.1' and service.component().default_profile_id == original_id
        assert current.is_dir() and not old.exists()
        for bad in ('../1.0.0', '../../../models', 'C:/outside'):
            with pytest.raises(ModelError):
                service.component_directory(bad)
        await manager.close()
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("values", [{"source": None}, {"source": {"type": "provider", "provider_profile_id": "x"}},
    {"source": {"type": "local", "execution_options": {"device": "cuda"}}},
    {"source": {"type": "local", "execution_options": {"gpu_index": 16}}},
    {"parameters": {"task": "generate"}}, {"parameters": {"temporal": False}},
    {"parameters": {"intensity": "1"}}, {"parameters": {"auto_mask": 1}}])
def test_processor_requires_strict_local_source_and_parameters(values):
    with pytest.raises(ValidationError):
        profile(**values)


@pytest.mark.parametrize("patch", [{"style": "other"}, {"preset": True}, {"preset": 4}, {"preset": -1},
    {"intensity": float("nan")}, {"tone": float("inf")}, {"structure": -0.1}, {"skin": -2},
    {"channel_order": "rgb"}, {"auto_mask": "false"}, {"gpu_index": 0}])
def test_request_controls_reject_invalid_values(patch):
    with pytest.raises(ValidationError):
        ImageProcessRequest(**patch)


@pytest.mark.parametrize("format,mode", [("PNG", "RGBA"), ("JPEG", "RGB"), ("WEBP", "RGBA")])
def test_static_images_preserve_oriented_dimensions_and_exact_alpha(format, mode):
    exif = Image.Exif()
    exif[274] = 6
    data = image_bytes(mode=mode, format=format, exif=exif)
    result = prepare_process_image(data)
    assert (result.width, result.height) == (13, 17)
    output = Image.open(BytesIO(result.data))
    assert output.mode == "RGBA" and output.getchannel("A").getextrema() == ((91, 91) if mode == "RGBA" else (255, 255))
    assert validate_process_output(result.data, result) == result
    with pytest.raises(ValueError):
        validate_process_output(image_bytes((13, 17), mode="RGB"), result)


def test_bad_animated_and_oversized_images_are_rejected_without_resizing():
    images = [b"not an image", image_bytes(mode="RGB", format="BMP")]
    animated = BytesIO()
    Image.new("RGBA", (2, 2), "red").save(animated, "PNG", save_all=True, append_images=[Image.new("RGBA", (2, 2), "blue")], duration=100)
    images.append(animated.getvalue())
    for data in images:
        with pytest.raises(ModelError) as error:
            prepare_process_image(data)
        assert error.value.code == "INVALID_IMAGE"
    for size in [(16385, 1), (4096, 2049)]:
        with pytest.raises(ModelError) as error:
            prepare_process_image(image_bytes(size))
        assert error.value.code == "REQUEST_TOO_LARGE"


def test_exif_rotates_each_alpha_pixel_and_worker_cannot_change_it():
    source = Image.new('RGBA', (3, 2), (210, 40, 10, 0))
    source.putalpha(Image.frombytes('L', (3, 2), bytes([0, 17, 80, 129, 230, 255])))
    exif = Image.Exif()
    exif[274] = 6
    encoded = BytesIO()
    source.save(encoded, 'PNG', exif=exif)
    prepared = prepare_process_image(encoded.getvalue())
    actual = Image.open(BytesIO(prepared.data))
    assert actual.getchannel('A').tobytes() == bytes([129, 0, 230, 17, 255, 80])
    actual.putpixel((0, 0), (210, 40, 10, 128))
    changed = BytesIO()
    actual.save(changed, 'PNG')
    with pytest.raises(ValueError):
        validate_process_output(changed.getvalue(), prepared)


@pytest.mark.parametrize("memory", [True, False])
def test_profile_routes_inspection_discovery_and_openapi(tmp_path, memory):
    with TestClient(create_app(root=tmp_path, use_memory=memory, database_url=f"sqlite:///{tmp_path / 'app.db'}")) as caller:
        response = caller.post("/api/models/profiles", json=profile().model_dump(mode="json", exclude={"id", "created_at", "updated_at"}))
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["parameters"]["task"] == "image_processing"
        assert caller.get("/api/models/inspect", params={"kind": "processor", "model_ref": REF}).json()["diagnostics"][0]["code"] == "missing_file"
        directory = tmp_path / "data/models" / REF
        directory.mkdir(parents=True)
        (directory / "nvngx_dlssnr.dll").write_bytes(b"must not be loaded or hashed")
        assert not inspect_processor(tmp_path, REF).diagnostics
        assert inventory(tmp_path, "processor")[0]["model_ref"] == REF
        component = caller.get("/api/models/local-runtime/components").json()[0]
        assert component["bundled_version"] == "0.1.1" and component["state"] == "not_installed"
        failed = caller.post("/api/models/local-runtime/components/dlss5nr/install")
        assert failed.status_code == 503
        assert caller.patch("/api/models/profiles/" + saved["id"], json={"model_ref": "processors/missing"}).status_code == 200
        assert caller.patch("/api/models/profiles/" + saved["id"], json={"source": None}).status_code == 422
        document = caller.get("/openapi.json").json()
        operation = document["paths"]["/v1/images/process"]["post"]
        reference = operation["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
        schema = document["components"]["schemas"][reference.rsplit("/", 1)[-1]]
        assert set(schema["required"]) == {"model", "image"} and schema["additionalProperties"] is False
        assert set(schema["properties"]) == {"model", "image", *ImageProcessRequest.model_fields}
        assert set(operation["responses"]["200"]["content"]) == {"image/png"}
        assert operation["security"] == [{"BearerAuth": []}, {"ApiKeyAuth": []}]


def test_revision_preserves_base_identity_and_all_resource_directories(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'app.db'}")
    migrations.upgrade(engine, migrations.PROJECTS_REVISION)
    with engine.begin() as db:
        db.execute(text("INSERT INTO runtime_installations (id,version,state,manifest_sha256,updated_at) VALUES ('local','1.0.0','installed','identity',CURRENT_TIMESTAMP)"))
    keep = tmp_path / "data/models" / REF / "nvngx_dlssnr.dll"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"resource")
    migrations.upgrade(engine)
    migrations.upgrade(engine)
    with engine.connect() as db:
        assert db.execute(text("SELECT version,state,manifest_sha256 FROM runtime_installations")).one() == ("1.0.0", "installed", "identity")
        assert db.execute(text("SELECT COUNT(*) FROM runtime_components")).scalar() == 0
    assert keep.read_bytes() == b"resource"
