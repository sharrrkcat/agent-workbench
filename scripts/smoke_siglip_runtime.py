"""CUDA-only SigLIP API, lifecycle and independent native-output acceptance."""
from __future__ import annotations

import argparse
import asyncio
import base64
from io import BytesIO
import json
import math
import os
from pathlib import Path
import platform
import time


def reference(path, tower, inputs, output):
    """Independent full-checkpoint reference; only the requested tower moves to CUDA."""
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    import importlib.metadata
    import torch
    import transformers
    from tokenizers import normalizers
    from PIL import Image
    torch.set_num_threads(4)
    assert torch.cuda.is_available(), "CUDA is required for reference inference"
    raw_config = json.loads((path / "config.json").read_text(encoding="utf-8"))
    prefix = {"siglip": "Siglip", "siglip2": "Siglip2"}[raw_config["model_type"]]
    model = getattr(transformers, prefix + "Model").from_pretrained(str(path),
        local_files_only=True, trust_remote_code=False, use_safetensors=True, dtype=torch.float16).eval()
    target = model.vision_model if tower == "image" else model.text_model
    target.to("cuda:0")
    if tower == "image":
        processor = getattr(transformers, prefix + "ImageProcessorPil").from_pretrained(str(path), local_files_only=True)
    else:
        tokenizer = transformers.AutoTokenizer.from_pretrained(str(path), local_files_only=True,
            trust_remote_code=False, tokenizer_file=str(path / "tokenizer.json"))
        if tokenizer.init_kwargs.get("do_lower_case") is True:
            original = tokenizer.backend_tokenizer.normalizer
            tokenizer.backend_tokenizer.normalizer = normalizers.Sequence(
                [normalizers.Lowercase()] + ([original] if original is not None else []))
        plain = tokenizer("Hello", add_special_tokens=True)["input_ids"]
        assert plain == tokenizer("hello", add_special_tokens=True)["input_ids"]
        if tokenizer.init_kwargs.get("add_eos_token"):
            assert plain[-1] == tokenizer.eos_token_id
    vectors = []
    with torch.inference_mode():
        for value in inputs:
            if tower == "image":
                with Image.open(BytesIO(base64.b64decode(value.partition(",")[2]))) as image:
                    batch = processor(images=[image.convert("RGB")], return_tensors="pt")
                operation = model.get_image_features
            else:
                batch = tokenizer([value], padding="max_length", truncation=True,
                    max_length=model.config.text_config.max_position_embeddings, add_special_tokens=True,
                    return_attention_mask="attention_mask" in tokenizer.model_input_names,
                    return_token_type_ids=False, return_tensors="pt")
                assert batch["input_ids"].shape[-1] == model.config.text_config.max_position_embeddings
                operation = model.get_text_features
            batch = {key: value.to(device="cuda:0", dtype=torch.float16 if value.is_floating_point() else value.dtype)
                     for key, value in batch.items()}
            pooled = operation(**batch).pooler_output.float()
            vectors.extend(torch.nn.functional.normalize(pooled, p=2, dim=-1).cpu().tolist())
    output.write_text(json.dumps({"vectors": vectors, "device": torch.cuda.get_device_name(0),
        "packages": {name: importlib.metadata.version(name) for name in ("torch", "transformers", "tokenizers", "pillow")},
        "peak_cuda_bytes": torch.cuda.max_memory_allocated()}), encoding="utf-8")


def fixture_inputs():
    from PIL import Image, ImageDraw
    images = []
    for color, size in (("red", (192, 96)), ("blue", (96, 192)), ("green", (224, 128))):
        image = Image.new("RGB", size, "white")
        ImageDraw.Draw(image).rectangle((16, 16, size[0] - 16, size[1] - 16), fill=color)
        stream = BytesIO(); image.save(stream, format="PNG")
        images.append("data:image/png;base64," + base64.b64encode(stream.getvalue()).decode())
    return {"image": images, "text": ["A RED RECTANGLE on a white background.",
        "a red rectangle on a white background.", "a blue rectangle on a white background.",
        "a green rectangle " * 100, "<end_of_turn> a colorful picture"]}


def compare(actual, expected):
    assert len(actual) == len(expected)
    errors, cosines = [], []
    for left, right in zip(actual, expected, strict=True):
        assert len(left) == len(right)
        errors.append(max(abs(a - b) for a, b in zip(left, right, strict=True)))
        cosines.append(sum(a * b for a, b in zip(left, right, strict=True)) /
            math.sqrt(sum(v * v for v in left) * sum(v * v for v in right)))
    assert max(errors) < 0.0002 and min(cosines) > 0.99999, (max(errors), min(cosines))
    return {"max_absolute_error": max(errors), "min_cosine_similarity": min(cosines)}


async def native_smoke(root, model_ref):
    from ai_workbench.api.deps import build_runtime_state
    from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog
    from ai_workbench.core.models.runtimes.store import RuntimeStore
    from ai_workbench.core.models.siglip import SiglipModelUse, SiglipTowerClient
    from ai_workbench.core.models.images import prepare_image_embedding_inputs
    from ai_workbench.core.models.store import LocalRuntimeSettingsStore
    from ai_workbench.db.database import get_engine
    assert platform.system() == "Windows", "Acceptance currently supports the Windows installation only"
    output = root / "build/siglip-smoke"
    output.mkdir(parents=True, exist_ok=True)
    database = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    state = build_runtime_state(root=root, use_memory=True)
    supervisor = state.runtime_supervisor
    supervisor.store, supervisor.settings = RuntimeStore(database), LocalRuntimeSettingsStore(database)
    report = {"model_ref": model_ref, "platform": platform.platform(), "device": "cuda", "cases": {}}
    try:
        supervisor.assert_available()
        report["runtime_version"] = supervisor.release.version
        start = time.monotonic()
        use = await SiglipModelUse.prepare(root, model_ref)
        report["identity_seconds"] = time.monotonic() - start
        print(json.dumps({"stage": "identity", "seconds": report["identity_seconds"]}), flush=True)
        limit = state.model_settings.get().max_normalized_request_mb * 1024 * 1024
        inputs = {tower: await asyncio.to_thread(prepare_image_embedding_inputs, tower, values, limit)
                  for tower, values in fixture_inputs().items()}
        input_file = output / "inputs.json"
        input_file.write_text(json.dumps(inputs), encoding="utf-8")
        results = {}
        for tower in ("image", "text"):
            client = SiglipTowerClient(supervisor, use, tower)
            try:
                start = time.monotonic()
                first = await client.embed(inputs[tower])
                cold = time.monotonic() - start
                process = client.process.process
                start = time.monotonic()
                repeated = await client.embed(inputs[tower])
                repeat = time.monotonic() - start
                assert client.process.process is process
                assert first.usage is first.timing is None
                assert all(len(row) == first.dimensions and all(math.isfinite(v) for v in row)
                    and abs(sum(v*v for v in row) - 1) < 0.00001 for row in first.vectors)
                repeated_comparison = compare(first.vectors, repeated.vectors)
                if tower == "text":
                    compare(first.vectors[:1], first.vectors[1:2])
                (output / f"{tower}-result.json").write_text(first.model_dump_json(), encoding="utf-8")
                results[tower] = first
                report["cases"][tower] = {"cold_seconds": cold, "repeat_seconds": repeat,
                    "metadata": client.info.model_dump(), "repeat_comparison": repeated_comparison}
                print(json.dumps({"stage": tower, "cold_seconds": cold, "repeat_seconds": repeat}), flush=True)
            finally:
                await client.close()
            assert process.returncode is not None
            reference_file = output / f"{tower}-reference.json"
            executable = supervisor.executable("siglip2", "cuda")
            env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "VIRTUAL_ENV"))}
            env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                       TOKENIZERS_PARALLELISM="false")
            reference_process = await ManagedProcess.start([executable, "-I", "-B", "-X", "utf8", Path(__file__).resolve(),
                "--reference", tower, "--root", root, "--model-ref", model_ref], env=env, cwd=output,
                log=RuntimeLog(output / f"{tower}-reference.log", root))
            try:
                assert await asyncio.wait_for(reference_process.wait(), 300) == 0, f"See {tower}-reference.log"
            finally:
                await reference_process.stop()
            expected = json.loads(reference_file.read_text(encoding="utf-8"))
            report["cases"][tower]["reference_comparison"] = compare(first.vectors, expected["vectors"])
            report["cases"][tower]["reference_peak_cuda_bytes"] = expected["peak_cuda_bytes"]
            report["packages"], report["device_name"] = expected["packages"], expected["device"]
            print(json.dumps({"stage": tower + "_reference", **report["cases"][tower]["reference_comparison"]}), flush=True)
        assert results["image"].model_revision == results["text"].model_revision == use.model_revision
        assert results["image"].vector_space_id == results["text"].vector_space_id
        report["status"] = "passed"
        report["limitations"] = ["No real CPU inference acceptance", "FixRes has automated tests only",
            "Native comparison does not cover full service lifecycle acceptance"]
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"siglip": "passed", "report": str(output / "report.json")}), flush=True)
    finally:
        await state.model_manager.close()
        await supervisor.close()
        database.dispose()


async def smoke(root, model_ref, *, full_lifecycle=False, cases=None):
    import secrets
    import socket
    import struct
    import httpx
    import uvicorn
    from ai_workbench.api.deps import build_runtime_state
    from ai_workbench.api.main import create_app
    from ai_workbench.api.schemas.inference import ImageEmbeddingResponse
    from ai_workbench.core.models.runtimes.store import RuntimeStore
    from ai_workbench.core.models.schema import ImageEmbeddingRequest
    from ai_workbench.core.models.store import LocalRuntimeSettingsStore
    from ai_workbench.db.database import get_engine, init_db

    assert platform.system() == "Windows", "Acceptance currently supports the Windows installation only"
    output = root / "build/siglip-smoke"
    output.mkdir(parents=True, exist_ok=True)
    database = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    init_db(database)
    state = build_runtime_state(root=root, use_memory=True)
    manager, supervisor = state.model_manager, state.runtime_supervisor
    supervisor.store, supervisor.settings = RuntimeStore(database), LocalRuntimeSettingsStore(database)
    listener, server, server_task = None, None, None
    report = {"model_ref": model_ref, "platform": platform.platform(), "device": "cuda", "cases": []}
    try:
        supervisor.assert_available()
        report["runtime_version"] = supervisor.release.version
        token = secrets.token_urlsafe(32)
        state.model_settings.patch({"external_enabled": True, "external_api_key": token})
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(create_app(runtime_state=state), log_level="error", ws="none"))
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started:
            if server_task.done():
                await server_task
                raise RuntimeError("The smoke API server did not start")
            await asyncio.sleep(0.02)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", timeout=310,
                headers={"Authorization": f"Bearer {token}"}, trust_env=False) as client:
            async def call(method, path, **kwargs):
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
            saved = await call("POST", "/api/models/profiles", json={"name": "SigLIP CUDA smoke", "alias": "siglip-smoke",
                "kind": "image_embedding", "model_ref": model_ref, "source": {"type": "local"}, "external_enabled": True})
            profile = manager.profiles.get(saved["id"])
            path = f"/api/models/profiles/{profile.id}"
            assert profile.source.execution_options["device"] == "cuda"
            assert profile.parameters == {"unload_other_tower_on_call": True}
            assert [item["id"] for item in (await call("GET", "/v1/models?kind=image_embedding"))["data"]] == [profile.alias]
            if full_lifecycle:
                from scripts.siglip_lifecycle import acceptance
                async def shutdown():
                    server.should_exit = True
                    await server_task
                await acceptance(root, state, client, profile, shutdown, cases)
                return
            assert not manager._slots
            assert (await call("POST", path + "/health"))["towers"]["model_revision"] is None
            inputs = fixture_inputs()
            results = []

            async def infer(case, tower, values, encoding="float"):
                start = time.monotonic()
                payload = await call("POST", "/v1/images/embeddings", json={"model": profile.alias,
                    "input_type": tower, "input": values, "encoding_format": encoding})
                result = ImageEmbeddingResponse.model_validate(payload)
                assert "usage" not in payload and "timing" not in payload
                assert result.model == profile.alias and result.input_type == tower
                assert [item.index for item in result.data] == list(range(len(values)))
                vectors = [list(struct.unpack("<" + "f" * result.dimensions, base64.b64decode(item.embedding)))
                           if isinstance(item.embedding, str) else item.embedding for item in result.data]
                assert all(len(row) == result.dimensions and all(math.isfinite(value) for value in row)
                           and abs(sum(value * value for value in row) - 1) < 0.00001 for row in vectors)
                if results:
                    assert (result.model_revision, result.vector_space_id, result.dimensions) == results[0]
                results.append((result.model_revision, result.vector_space_id, result.dimensions))
                measurement = {"case": case, "tower": tower, "seconds": round(time.monotonic() - start, 3)}
                report["cases"].append(measurement)
                print(json.dumps(measurement), flush=True)
                return vectors

            first = await infer("image_autoload", "image", inputs["image"][:1])
            adapter = manager._managed_slot(profile).adapter
            image = adapter.clients["image"].process.process
            compare(first, await infer("image_reuse", "image", inputs["image"][:1]))
            assert image is adapter.clients["image"].process.process
            text_vectors = await infer("switch_to_text", "text", inputs["text"][:3])
            text = adapter.clients["text"].process.process
            assert image.returncode is not None and adapter.towers.image.process_state == "stopped"
            compare(text_vectors, await infer("text_base64_reuse", "text", inputs["text"][:3], "base64"))
            assert text is adapter.clients["text"].process.process
            invalid = await client.post("/v1/images/embeddings", json={"model": profile.alias, "input_type": "image", "input": "bad"})
            assert invalid.status_code == 422 and text.returncode is None
            compare(first, await infer("switch_back_to_image", "image", inputs["image"][:1]))
            assert text.returncode is not None
            image = adapter.clients["image"].process.process
            loaded = await call("POST", path + "/load", json={"tower": "image"})
            assert loaded["towers"]["active_tower"] is None and image is adapter.clients["image"].process.process
            internal = await manager.image_embed(profile.id, ImageEmbeddingRequest(model=profile.alias,
                input_type="image", input=inputs["image"][:1]))
            assert internal.usage is internal.timing is None
            compare(first, internal.vectors)
            report["metadata"] = adapter.clients["image"].info.model_dump()
            assert "SigLIP image" in (await call("GET", path + "/log?tower=image"))["text"]
            unloaded = await call("POST", path + "/unload")
            assert image.returncode is not None and adapter.model_use is None
            assert unloaded["towers"]["model_revision"] is None
            assert all(unloaded["towers"][tower]["process_state"] == "stopped" for tower in ("image", "text"))
            assert not state.runs.list_all_runs() and not state.sessions.list_sessions()
            report.update(status="passed", process_reuse="passed", switch_cleanup="passed", unload="passed",
                usage_timing="unset", limitations=["No real CPU or FixRes acceptance",
                    "Full CUDA repeated switching, dual residency, cancellation and failure acceptance is deferred"])
        (output / "service-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"siglip_api": "passed", "report": str(output / "service-report.json")}), flush=True)
    finally:
        if server:
            server.should_exit = True
        if server_task:
            await server_task
        if listener:
            listener.close()
        await manager.close()
        await supervisor.close()
        database.dispose()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-ref", required=True, help="Existing SigLIP-family directory relative to data/models")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--native-reference", action="store_true", help="Compare independent single towers with native CUDA FP16 outputs instead of the API smoke")
    modes.add_argument("--full-lifecycle", action="store_true", help="Opt in to the extended CUDA matrix only when explicitly requested by the user; not routine acceptance")
    parser.add_argument("--case", action="append", choices=("switching", "residency", "cancellation", "faults", "identity", "release"),
                        help="Narrow an explicitly requested extended matrix to selected groups")
    parser.add_argument("--reference", choices=("image", "text"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.case and not args.full_lifecycle:
        parser.error("--case requires --full-lifecycle")
    if args.reference and (args.full_lifecycle or args.native_reference):
        parser.error("--reference is an internal native-reference subprocess mode")
    return args


if __name__ == "__main__":
    args = parse_args()
    root = args.root.resolve()
    if args.reference:
        output = root / "build/siglip-smoke"
        inputs = json.loads((output / "inputs.json").read_text(encoding="utf-8"))[args.reference]
        reference(root / "data/models" / args.model_ref, args.reference, inputs, output / f"{args.reference}-reference.json")
    else:
        asyncio.run(native_smoke(root, args.model_ref) if args.native_reference else
                    smoke(root, args.model_ref, full_lifecycle=args.full_lifecycle, cases=args.case))
