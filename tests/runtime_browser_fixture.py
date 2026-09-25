"""Temporary-root runtime fixtures for the settings browser tests."""
import asyncio
import json
import os

from fastapi import Body

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.catalog import catalog
from tests.model_fixtures import write_local_model
from tests.test_tts import model_tree


def install_runtime_fixture(app, root):
    model_tree(root)
    for reference, engine in [('llms/fixture', 'llama-server'), ('llms/other', 'llama-server'),
            ('llms/text-only', 'llama-server'), ('llms/manual-model', 'llama-server'), ('llms/transformers', 'transformers'),
            ('tts/fixture-chatterbox', 'chatterbox'), ('tts/fixture-qwen', 'qwen3tts'), ('tts/fixture-qwen3tts', 'qwen3tts')]:
        path = write_local_model(root, reference, engine)
        if reference in {'llms/fixture', 'llms/other'}:
            (path / 'mmproj-fixture.gguf').write_bytes(b'projector fixture')
    ambiguous = write_local_model(root, 'llms/ambiguous', 'llama-server')
    (ambiguous / 'second.gguf').write_bytes(b'second quantization')
    state = app.state.runtime_state
    supervisor = state.runtime_supervisor
    cache = supervisor.base / ".cache"
    shared = cache / "shared.bin"
    exclusive = cache / "exclusive.bin"
    installed = supervisor.base / "local/1.0.0/env/Lib/shared.bin"
    behavior = {"slow": False, "fail": False}

    @app.post("/__test__/runtimes")
    async def configure(values: dict = Body(default={})):
        if supervisor.active_job:
            await supervisor.cancel(supervisor.active_job)
        supervisor.store._jobs.clear()
        supervisor.release = catalog("windows", "x86_64")
        behavior.update(slow=bool(values.get("slow")), fail=bool(values.get("fail")))
        cache.mkdir(parents=True, exist_ok=True)
        installed.parent.mkdir(parents=True, exist_ok=True)
        shared.unlink(missing_ok=True)
        installed.unlink(missing_ok=True)
        shared.write_bytes(b"shared fixture" * 256)
        os.link(shared, installed)
        exclusive.write_bytes(b"exclusive fixture" * 512)
        for profile in state.model_manager.profiles.list():
            if profile.alias.startswith("runtime-fixture-"):
                state.model_manager.profiles.delete(profile.id)
        if values.get("wd14"):
            model = root / "data/models/vision/browser-wd14"
            model.mkdir(parents=True, exist_ok=True)
            (model / "model.onnx").write_bytes(b"Browser inventory fixture")
            (model / "selected_tags.csv").write_text("name,category\nfixture_tag,0\n", encoding="utf-8")
        if values.get("siglip2"):
            for name, model_type in (("browser-naflex", "siglip2"), ("browser-fixres", "siglip"), ("incomplete", "unknown")):
                model = root / "data/models/image_embeddings" / name
                model.mkdir(parents=True, exist_ok=True)
                (model / "config.json").write_text(json.dumps({"model_type": model_type,
                    "vision_config": {"hidden_size": 768, "image_size": 256, "patch_size": 16},
                    "text_config": {"projection_size": 768, "max_position_embeddings": 64}}), encoding="utf-8")
                (model / "model.safetensors").write_bytes(b"Browser inventory fixture")
                if name != "incomplete":
                    (model / "preprocessor_config.json").write_text(json.dumps({"patch_size": 16, "max_num_patches": 256,
                        "do_resize": True, "resample": 2, "do_rescale": True, "rescale_factor": 1 / 255,
                        "do_normalize": True, "image_mean": [0.5] * 3, "image_std": [0.5] * 3}), encoding="utf-8")
                    (model / "tokenizer_config.json").write_text(json.dumps({"model_max_length": 10**30,
                        "do_lower_case": True, "add_bos_token": False, "add_eos_token": True}), encoding="utf-8")

        async def command(args, env, cwd, log):
            assert list(map(str, args))[1:3] in (["cache", "prune"], ["cache", "clean"])
            assert str(cache) == str(args[args.index("--cache-dir") + 1])
            await asyncio.sleep(3 if behavior["slow"] else 0.25)
            exclusive.unlink(missing_ok=True)
            if behavior["fail"]:
                behavior["fail"] = False
                raise ModelError("RUNTIME_INSTALL_FAILED", "Fixture file is in use", 503)
            if args[2] == "clean":
                shared.unlink(missing_ok=True)
            log.write("Fixture cache operation completed.")

        supervisor._command = command
        return (await supervisor.storage()).model_dump(mode="json")

    @app.post("/__test__/runtimes/files")
    async def files():
        return {"installed_preserved": installed.is_file() and installed.read_bytes() == b"shared fixture" * 256}
