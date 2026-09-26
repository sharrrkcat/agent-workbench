"""Real private worker transport, using a synthetic engine instead of a GPU."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import shutil

import httpx
import pytest

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import ComponentInstallation
from ai_workbench.core.models.runtimes.supervisor import sha256
from ai_workbench.core.models.schema import ImageProcessRequest
from tests.test_dlss_processor import REF, image_bytes, profile
from tests.test_text_embedding_runtime import runtime as existing_runtime
from tests.test_wd14_runtime import wait_for

FAKE_ENGINE = '''
import base64, json, os, time
class WorkerError(Exception):
    def __init__(self, code, status=422): self.code, self.status = code, status
def fields(value, keys):
    if set(value) != set(keys): raise WorkerError('INVALID_REQUEST')
def load_bridge(path): pass
class Engine:
    def __init__(self, models_root, bridge, caller, work):
        assert not work.startswith(models_root)
    def load(self, value):
        assert value['options'] == {'device':'d3d12','gpu_index':0}
        return {'device_name':'Fixture D3D12'}
    def unload(self): pass
    def process(self, value):
        options = value['options']
        print('controls=' + json.dumps(options), flush=True)
        if options['style'] == '3': return b'invalid PNG'
        if options['style'] == '4': os._exit(7)
        if options['style'] == '5':
            print('waiting', flush=True)
            time.sleep(60)
        return base64.b64decode(value['image'])
'''


@asynccontextmanager
async def runtime(tmp_path, **values):
    async with existing_runtime(tmp_path) as (service, manager, _, caller):
        manifest = service.component_release.manifest
        target = service.component_directory(manifest.version)
        for name in manifest.entries.model_dump().values():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        shutil.copyfile(Path(__file__).resolve().parents[1] / "runtime_components/dlss5nr/server.py", target / manifest.entries.worker)
        (target / manifest.entries.engine).write_text(FAKE_ENGINE, encoding="utf-8")
        marker = target / "installation.json"
        marker.write_text(manifest.model_dump_json())
        service.store.save_component(ComponentInstallation(version=manifest.version, state="installed", manifest_sha256=sha256(marker)))
        service.component()
        resource = tmp_path / "data/models" / REF / "nvngx_dlssnr.dll"
        resource.parent.mkdir(parents=True)
        resource.write_bytes(b"user-provided test resource")
        model = manager.profiles.create(profile(**values))
        yield service, manager, model, caller


async def upload(caller, model, data=None, **options):
    return await caller.post("/v1/images/process", data={"model": model.alias, **options},
        files={"image": ("input.png", image_bytes() if data is None else data, "image/png")})


def test_public_overrides_reuse_and_internal_operation(tmp_path):
    async def scenario():
        async with runtime(tmp_path, parameters={"intensity": 1.5, "auto_mask": True, "style": "cinematic"}) as (_, manager, model, caller):
            assert (await caller.get("/v1/models?kind=processor")).json()["data"][0]["id"] == model.alias
            assert not manager._slots
            result = await upload(caller, model)
            assert result.status_code == 200, result.text
            assert result.headers["content-type"] == "image/png" and result.headers["x-request-id"]
            adapter = manager._managed_slot(model).adapter
            process = adapter.process.process
            result = await upload(caller, model, intensity="0", preset="0", auto_mask="false", skin="-1", channel_order="BGRA", style="default")
            assert result.status_code == 200
            controls = json.loads(adapter.log_path.read_text().split("controls=")[-1].splitlines()[0])
            assert controls == {key: value for key, value in {**model.parameters, "intensity": 0,
                "preset": 0, "auto_mask": False, "channel_order": "BGRA", "style": "default"}.items() if key != "task"}
            assert controls["preset"] == 0 and controls["auto_mask"] is False and "task" not in controls
            assert controls["channel_order"] == "BGRA" and controls["style"] == "default"
            await manager.process_image(model.id, image_bytes(), ImageProcessRequest())
            assert adapter.process.process is process and manager.profiles.get(model.id).parameters == model.parameters
            async with httpx.AsyncClient(trust_env=False) as private:
                assert (await private.get(str(adapter.client.base_url) + "/health")).status_code == 401
            await manager.unload(model.id)
            assert process.returncode is not None
    asyncio.run(scenario())


def test_public_validation_visibility_and_request_limit(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, caller):
            for options in ({"style": "bad"}, {"preset": "1.5"}, {"intensity": "NaN"}, {"tone": "3"},
                    {"auto_mask": "0"}, {"channel_order": "RGB"}, {"gpu_index": "1"}, {"temporal": "true"}):
                assert (await upload(caller, model, **options)).status_code == 422
            for files in ([('image', ('a.png', image_bytes())), ('image', ('b.png', image_bytes()))],
                    [('model', (None, model.alias)), ('image', ('a.png', image_bytes()))]):
                assert (await caller.post('/v1/images/process', data={'model': model.alias}, files=files)).status_code == 422
            assert (await upload(caller, model, data=b"bad")).status_code == 422
            assert not manager._slots
            assert (await caller.post('/v1/images/process', headers={'Authorization': 'Bearer wrong'})).status_code == 401
            manager.profiles.update(model.id, {"external_enabled": False})
            assert (await upload(caller, model)).status_code == 404
            manager.profiles.update(model.id, {"external_enabled": True})
            manager.settings.patch({"max_request_mb": 1})
            assert (await upload(caller, model, data=b"x" * (1024 * 1024))).status_code == 413
    asyncio.run(scenario())


def test_serial_queue_cancellation_malformed_output_and_explicit_crash_reload(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, _):
            other = manager.profiles.create(profile(alias="other"))
            await manager.process_image(model.id, image_bytes(), ImageProcessRequest())
            await manager.process_image(other.id, image_bytes(), ImageProcessRequest())
            adapter = manager._managed_slot(model).adapter
            witness = manager._managed_slot(other).adapter.process.process
            process = adapter.process.process
            active = asyncio.create_task(manager.process_image(model.id, image_bytes(), ImageProcessRequest(style="5")))
            await wait_for(lambda: "waiting" in adapter.log_path.read_text())
            queued = asyncio.create_task(manager.process_image(model.id, image_bytes(), ImageProcessRequest()))
            await wait_for(lambda: manager.status(model.id).queued == 1)
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)
            assert process.returncode is None
            stop = adapter._stop
            async def observed_stop():
                assert manager.status(model.id).active == 1
                await stop()
                assert process.returncode is not None
            adapter._stop = observed_stop
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
            adapter._stop = stop
            assert witness.returncode is None and manager.status(model.id).active == 0
            for style in ("3", "4"):
                with pytest.raises(ModelError):
                    await manager.process_image(model.id, image_bytes(), ImageProcessRequest(style=style))
                assert manager.status(model.id).state == "failed"
                with pytest.raises(ModelError):
                    await manager.process_image(model.id, image_bytes(), ImageProcessRequest())
                await manager.load(model.id)
                await manager.process_image(model.id, image_bytes(), ImageProcessRequest())
            assert witness.returncode is None
    asyncio.run(scenario())


def test_public_disconnect_releases_the_worker_before_occupancy(tmp_path):
    async def scenario():
        async with runtime(tmp_path) as (_, manager, model, caller):
            await manager.load(model.id)
            adapter = manager._managed_slot(model).adapter
            process = adapter.process.process
            request = caller.build_request('POST', '/v1/images/process', data={'model': model.alias, 'style': '5'},
                files={'image': ('input.png', image_bytes(), 'image/png')})
            body = request.read()
            disconnected, delivered, responses = asyncio.Event(), False, []
            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': body, 'more_body': False}
                await disconnected.wait()
                return {'type': 'http.disconnect'}
            async def send(message):
                responses.append(message)
            scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST',
                'scheme': 'http', 'path': '/v1/images/process', 'raw_path': b'/v1/images/process',
                'query_string': b'', 'headers': [(k.lower(), v) for k, v in request.headers.raw],
                'client': ('127.0.0.1', 40001), 'server': ('cogita.test', 80), 'root_path': ''}
            task = asyncio.create_task(caller._transport.app(scope, receive, send))
            try:
                await wait_for(lambda: 'waiting' in adapter.log_path.read_text())
                disconnected.set()
                await asyncio.wait_for(task, 5)
                assert process.returncode is not None and manager.status(model.id).active == 0
                assert next(item['status'] for item in responses if item['type'] == 'http.response.start') == 499
            finally:
                disconnected.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
