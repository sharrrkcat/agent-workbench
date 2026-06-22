import asyncio
import base64
from pathlib import Path

import pytest
import yaml

from ai_workbench.core.image_generation.generation import ImageGenerationError, ImageGenerationService
from ai_workbench.core.image_generation.profiles import ImageModelProfile
from ai_workbench.core.stores import ImageGenerationProfileStore
from capabilities.image_generation import CapabilityRuntime


ROOT = Path(__file__).resolve().parents[1]


def make_runtime(tmp_path: Path) -> tuple[CapabilityRuntime, ImageGenerationProfileStore]:
    store = ImageGenerationProfileStore()
    runtime = CapabilityRuntime()
    runtime.configure(service=ImageGenerationService(profile_store=store, repo_root=tmp_path))
    return runtime, store


def add_profile(store: ImageGenerationProfileStore, *, enabled: bool = True, alias: str = "image-main") -> ImageModelProfile:
    return store.create(
        ImageModelProfile(
            name="SDXL Image Model",
            alias=alias,
            enabled=enabled,
            architecture="sdxl",
            checkpoint_ref=f"image_generation/checkpoints/{alias}.safetensors",
        )
    )


def test_image_generation_manifest_has_no_commands_and_runtime_methods() -> None:
    manifest = yaml.safe_load((ROOT / "capabilities" / "image_generation" / "capability.yaml").read_text(encoding="utf-8"))
    runtime = CapabilityRuntime()

    assert manifest["commands"] == []
    assert {method["id"] for method in manifest["methods"]} == {
        "status",
        "list_model_profiles",
        "validate_txt2img",
        "txt2img",
        "queue_status",
        "cancel",
        "unload",
    }
    for method in manifest["methods"]:
        assert callable(getattr(runtime, method["id"]))


def test_image_generation_status_uses_fake_runtime(tmp_path: Path) -> None:
    runtime, store = make_runtime(tmp_path)
    add_profile(store)

    status = runtime.status()

    assert status["service"] == "internal"
    assert status["profiles_total"] == 1
    assert status["profiles_enabled"] == 1
    assert status["runtime"] == {
        "available": True,
        "status": "ready",
        "backend": "fake",
        "real_generation": False,
        "supports_queue": True,
        "supports_cancel": True,
        "supports_unload": True,
    }
    assert status["queue"] == {"max_concurrent": 1, "active_count": 0, "queued_count": 0}
    assert status["cache"]["cached_profiles"] == 0


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"profile_id_or_alias": "missing"}, "IMAGE_GENERATION_MODEL_NOT_FOUND"),
        ({"positive_prompt": ""}, "INVALID_IMAGE_GENERATION_REQUEST"),
        ({"width": 65}, "INVALID_IMAGE_GENERATION_REQUEST"),
        ({"seed": 2**32}, "INVALID_IMAGE_GENERATION_REQUEST"),
        ({"loras": [{"ref": "..\\bad.safetensors", "weight": 1.0}]}, "INVALID_IMAGE_GENERATION_REQUEST"),
    ],
)
def test_validate_txt2img_rejects_invalid_requests(tmp_path: Path, patch: dict, code: str) -> None:
    runtime, store = make_runtime(tmp_path)
    add_profile(store)
    payload = {
        "profile_id_or_alias": "image-main",
        "positive_prompt": "secret prompt",
        "width": 64,
        "height": 64,
    }
    payload.update(patch)

    with pytest.raises(ImageGenerationError) as exc:
        runtime.validate_txt2img(**payload)

    assert exc.value.code == code


def test_validate_txt2img_rejects_disabled_profile(tmp_path: Path) -> None:
    runtime, store = make_runtime(tmp_path)
    add_profile(store, enabled=False)

    with pytest.raises(ImageGenerationError) as exc:
        runtime.validate_txt2img(profile_id_or_alias="image-main", positive_prompt="secret prompt", width=64, height=64)

    assert exc.value.code == "IMAGE_GENERATION_MODEL_DISABLED"


def test_txt2img_returns_transient_png_without_paths_or_prompts(tmp_path: Path) -> None:
    runtime, store = make_runtime(tmp_path)
    add_profile(store)

    result = asyncio.run(
        runtime.txt2img(
            profile_id_or_alias="image-main",
            positive_prompt="secret prompt",
            negative_prompt="hidden negative",
            width=64,
            height=64,
            steps=12,
            cfg=5.5,
            seed=123,
            batch_size=2,
            loras=[{"ref": "image_generation/loras/style.safetensors", "weight": 0.7}],
            context={"run_id": "run-image"},
        )
    )

    assert result["backend"] == "fake"
    assert result["real_generation"] is False
    assert result["request"]["lora_count"] == 1
    assert result["request"]["positive_prompt_chars"] == len("secret prompt")
    assert result["request"]["positive_prompt_sha256"]
    assert result["queue"]["run_id"] == "run-image"
    assert result["queue"]["status"] == "completed"
    assert len(result["images"]) == 2
    png = base64.b64decode(result["images"][0]["data_base64"])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert str(tmp_path) not in str(result)
    assert "secret prompt" not in str(result)
    assert "hidden negative" not in str(result)
    assert "image_generation/loras/style.safetensors" not in str(result)


def test_queue_status_cancel_and_unload_are_compact(tmp_path: Path) -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowFakeRuntime:
            backend = "fake"
            real_generation = False

            def request_id(self, profile, request):
                return "slow_" + request.positive_prompt.replace(" ", "_")

            async def generate(self, profile, request, request_id=None):
                started.set()
                await release.wait()
                return FakeRuntimeForTest().generate(profile, request, request_id=request_id)

        class FakeRuntimeForTest:
            backend = "fake"
            real_generation = False

            def generate(self, profile, request, request_id=None):
                from ai_workbench.core.image_generation.generation import FakeTxt2ImgRuntime

                return FakeTxt2ImgRuntime().generate(profile, request, request_id=request_id)

        store = ImageGenerationProfileStore()
        service = ImageGenerationService(profile_store=store, repo_root=tmp_path, runtime=SlowFakeRuntime(), max_concurrent=1)
        runtime = CapabilityRuntime(service=service)
        add_profile(store)

        first = asyncio.create_task(
            runtime.txt2img(profile_id_or_alias="image-main", positive_prompt="secret first", width=64, height=64)
        )
        await started.wait()
        second = asyncio.create_task(
            runtime.txt2img(profile_id_or_alias="image-main", positive_prompt="secret second", width=64, height=64)
        )
        await asyncio.sleep(0)
        status = runtime.queue_status()

        assert status["active_count"] == 1
        assert status["queued_count"] == 1
        assert status["active_requests"][0]["request_id"] == "slow_secret_first"
        assert "secret first" not in str(status)
        assert "secret second" not in str(status)
        assert "data_base64" not in str(status)
        assert str(tmp_path) not in str(status)

        cancel = runtime.cancel(request_id="slow_secret_second")
        assert cancel["status"] == "cancel_requested"
        busy_unload = runtime.unload()
        assert busy_unload["status"] == "busy"

        release.set()
        result = await first
        assert result["queue"]["status"] == "completed"
        with pytest.raises(ImageGenerationError) as exc:
            await second
        assert exc.value.code == "IMAGE_GENERATION_CANCELLED"

        freed = runtime.unload()
        assert freed["status"] == "freed"
        assert freed["removed"] == 1
        skipped = runtime.unload()
        assert skipped["status"] == "skipped"
        missing = runtime.cancel(request_id="missing")
        assert missing["status"] == "not_found"

    asyncio.run(scenario())
