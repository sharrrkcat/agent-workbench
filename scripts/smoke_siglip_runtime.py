"""CUDA-only SigLIP single-tower acceptance with a supplied model and verified installation."""
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


async def smoke(root, model_ref):
    from ai_workbench.api.deps import build_runtime_state
    from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog
    from ai_workbench.core.models.runtimes.store import RuntimeStore
    from ai_workbench.core.models.siglip import SiglipModelUse, SiglipTowerClient
    from ai_workbench.core.models.store import LocalRuntimeSettingsStore
    from ai_workbench.db.database import get_engine
    assert platform.system() == "Windows", "Acceptance currently supports the Windows installation only"
    output = root / "build/siglip-smoke"
    output.mkdir(parents=True, exist_ok=True)
    database = get_engine(f"sqlite:///{root / 'data/agent_workbench.db'}")
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
        inputs = fixture_inputs()
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
            "No ModelManager binding, tower scheduling, configuration UI or public embedding endpoint"]
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"siglip": "passed", "report": str(output / "report.json")}), flush=True)
    finally:
        await state.model_manager.close()
        await supervisor.close()
        database.dispose()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-ref", required=True, help="Existing SigLIP-family directory relative to data/models")
    parser.add_argument("--reference", choices=("image", "text"), help=argparse.SUPPRESS)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    root = args.root.resolve()
    if args.reference:
        output = root / "build/siglip-smoke"
        inputs = json.loads((output / "inputs.json").read_text(encoding="utf-8"))[args.reference]
        reference(root / "data/models" / args.model_ref, args.reference, inputs, output / f"{args.reference}-reference.json")
    else:
        asyncio.run(smoke(root, args.model_ref))
