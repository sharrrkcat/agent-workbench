"""Accept bundled DLSS NR installation and still-image inference on Windows D3D12."""
import argparse
import asyncio
from io import BytesIO
import json
from pathlib import Path
import platform
import time
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageChops

from ai_workbench.api.main import create_app
from ai_workbench.core.models.processing import prepare_process_image, validate_process_output
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import ModelSettingsStore


def fixture(size=(640, 360)):
    gradient = Image.linear_gradient('L').resize(size)
    image = Image.merge('RGB', (gradient, gradient.transpose(Image.Transpose.FLIP_TOP_BOTTOM), gradient.transpose(Image.Transpose.FLIP_LEFT_RIGHT)))
    draw = ImageDraw.Draw(image)
    width, height = size
    draw.rectangle((width // 12, height // 6, width // 3, height * 5 // 6), fill=(210, 30, 20))
    draw.ellipse((width // 2, height // 6, width * 5 // 6, height * 5 // 6), fill=(20, 30, 210))
    for x in range(0, width, max(2, width // 64)):
        draw.line((x, 0, width - x, height), fill=(120, 80, 40))
    image.putalpha(gradient)
    output = BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


def color_fixture(color):
    image = Image.new('RGBA', (256, 192), color)
    image.putalpha(Image.linear_gradient('L').resize(image.size))
    output = BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


async def check_image_independence(infer, reload):
    """Compare a fresh process with reuse after an unrelated input, at each strength."""
    red, green = color_fixture('red'), color_fixture('lime')
    expected = Image.open(BytesIO(green)).convert('RGBA').tobytes()
    cases = []
    for style in ('natural', 'cinematic'):
        for intensity in (0, 0.01, 0.5, 1):
            name = f'{style}-{intensity}'
            options = {'style': style, 'intensity': str(intensity), 'channel_order': 'RGBA'}
            await reload()
            isolated = await infer('isolated-green-' + name, green, **options)
            await infer('red-before-' + name, red, style=style, intensity='1', channel_order='RGBA')
            reused = await infer('reused-green-' + name, green, **options)
            assert reused.tobytes() == isolated.tobytes(), f'{name}: output depends on the previous image'
            if intensity == 0:
                assert reused.tobytes() == expected, f'{name}: zero intensity did not retain the current RGBA input'
            cases.append({'style': style, 'intensity': intensity, 'independent': True})
    await infer('red-before-style-switch', red, style='natural', intensity='1', channel_order='RGBA')
    switched = await infer('green-zero-after-style-switch', green, style='cinematic', intensity='0', channel_order='RGBA')
    assert switched.tobytes() == expected, 'Zero intensity after changing style returned stale or black pixels'
    return cases


async def smoke(root, model_ref, lifecycle, sample):
    output = root / 'build/dlss-smoke'
    output.mkdir(parents=True, exist_ok=True)
    report = {'platform': platform.platform(), 'cases': [], 'status': 'running'}
    app = create_app(root=root, use_memory=False)
    state = app.state.runtime_state
    supervisor, manager = state.runtime_supervisor, state.model_manager
    # Acceptance credentials and settings are request-local; profile/bootstrap ownership stays durable.
    state.model_settings = manager.settings = ModelSettingsStore()
    manager.settings.patch({'external_enabled': True, 'external_api_key': uuid4().hex, 'max_request_mb': 100})
    model = None
    resource = root / 'data/models' / model_ref / 'nvngx_dlssnr.dll'
    original_names = set(resource.parent.iterdir())
    base = supervisor.installation().model_dump()
    try:
        supervisor.assert_available()
        if not resource.is_file():
            raise RuntimeError('Supply nvngx_dlssnr.dll in the selected model directory before acceptance.')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 40001)),
                base_url='http://cogita.test', timeout=310, headers={'Authorization': 'Bearer ' + manager.settings.get().external_api_key}) as client:
            async def component_action(action):
                response = await client.post('/api/models/local-runtime/components/dlss5nr/' + action)
                response.raise_for_status()
                job = response.json()
                if job['state'] not in {'completed', 'failed'}:
                    await supervisor.task
                result = supervisor.store.job(job['id'])
                report['cases'].append({'operation': action, 'state': result.state, 'error_code': result.error_code})
                if result.state != 'completed':
                    raise RuntimeError(supervisor.log_text(result.id))
                assert supervisor.installation().model_dump() == base
                assert set(resource.parent.iterdir()) == original_names
                print(json.dumps(report['cases'][-1]), flush=True)
            if lifecycle:
                await component_action('install')
                await component_action('repair')
                await component_action('uninstall')
                await component_action('install')
            else:
                supervisor.component_entries()
            report['runtime_version'] = supervisor.installation().version
            report['component_version'] = supervisor.component().version
            model = manager.profiles.create(ModelProfile(name='DLSS acceptance', alias='dlss-smoke-' + uuid4().hex[:8],
                kind='processor', model_ref=model_ref, external_enabled=True))
            await manager.load(model.id)
            report['device'] = manager.status(model.id).runtime.device_name
            adapter = manager._managed_slot(model).adapter
            process = adapter.process.process
            async def infer(name, data, **options):
                started = time.monotonic()
                response = await client.post('/v1/images/process', data={'model': model.alias, **options},
                    files={'image': ('input.png', data, 'image/png')})
                elapsed = round(time.monotonic() - started, 3)
                case = {'case': name, 'seconds': elapsed, 'http_status': response.status_code}
                report['cases'].append(case)
                if response.is_error:
                    case['error'] = response.json()
                    raise RuntimeError(response.text)
                original = prepare_process_image(data)
                result = validate_process_output(response.content, original)
                case.update(width=result.width, height=result.height, bytes=len(result.data))
                (output / (name + '.png')).write_bytes(result.data)
                assert adapter.process.process is process
                print(json.dumps(case), flush=True)
                return Image.open(BytesIO(result.data)).copy()
            data = sample.read_bytes() if sample else fixture()
            (output / 'input.png').write_bytes(prepare_process_image(data).data)
            first = await infer('default', data)
            repeated = await infer('repeat', data)
            report['repeat_identical'] = first.tobytes() == repeated.tobytes()
            changed = await infer('cinematic', data, style='cinematic', preset='2', intensity='0.5', tone='0.7',
                structure='0.8', skin='0', auto_mask='true', channel_order='auto')
            report['parameters_change_rgb'] = ImageChops.difference(first.convert('RGB'), changed.convert('RGB')).getbbox() is not None
            async def reload():
                nonlocal process
                await manager.unload(model.id)
                await manager.load(model.id)
                process = adapter.process.process
            report['image_independence'] = await check_image_independence(infer, reload)
            await infer('uhd_4k', fixture((3840, 2160)))
            started = time.monotonic()
            await manager.unload(model.id)
            assert process.returncode is not None and manager.status(model.id).residency == 'unloaded'
            report['unload_seconds'] = round(time.monotonic() - started, 3)
            await manager.load(model.id)
            process = adapter.process.process
            await infer('after_reload', data)
            assert manager.profiles.get(model.id).parameters['intensity'] == 1
            assert set(resource.parent.iterdir()) == original_names
            report['model_resources_unchanged'] = True
            report['status'] = 'passed'
    except Exception as exc:
        report.update(status='failed', error=str(exc))
        if model:
            (output / 'worker.log').write_text(manager.process_log(model), encoding='utf-8')
        raise
    finally:
        try:
            await manager.close()
            if model:
                manager.profiles.delete(model.id)
            await supervisor.close()
        finally:
            (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps({'status': report['status'], 'report': str(output / 'report.json')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--model-ref', default='processors/dlss5-nr')
    parser.add_argument('--component-lifecycle', action='store_true', help='Install/repair/uninstall/reinstall only the DLSS component; preserve the base runtime and model resources.')
    parser.add_argument('--image', type=Path, help='Optional representative PNG/JPEG/WebP in addition to the UHD fixture.')
    args = parser.parse_args()
    asyncio.run(smoke(args.root.resolve(), args.model_ref, args.component_lifecycle, args.image))
