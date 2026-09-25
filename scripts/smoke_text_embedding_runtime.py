"""Accept an explicitly supplied text embedding directory using the installed runtime."""
import argparse
import asyncio
import base64
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import secrets
import socket
import struct
import time


QUERIES = ["how much protein should a female eat", "summit define"]
DOCUMENTS = [
    "As a general guideline, the CDC's average requirement of protein for women ages 19 to 70 is 46 grams per day.",
    "Definition of summit: the highest point of a mountain, or a meeting between leaders of governments.",
    "Citrus fruits include oranges and lemons. " * 30,
]


def compare(actual, expected):
    assert len(actual) == len(expected)
    errors, cosines = [], []
    for left, right in zip(actual, expected):
        assert len(left) == len(right)
        errors.append(max(abs(a - b) for a, b in zip(left, right)))
        cosines.append(sum(a * b for a, b in zip(left, right)) /
            math.sqrt(sum(v * v for v in left) * sum(v * v for v in right)))
    result = {"max_absolute_error": max(errors), "min_cosine_similarity": min(cosines)}
    assert result["max_absolute_error"] <= 0.005 and result["min_cosine_similarity"] >= 0.9998, result
    return result


def native_reference(directory, output):
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(4)
    model = SentenceTransformer(str(directory), device="cuda", local_files_only=True,
        trust_remote_code=False, model_kwargs={"dtype": "auto"})
    # Native max_seq_length may prefer the tokenizer over the backbone's smaller limit.
    model.max_seq_length = min(value for value in (model.max_seq_length,
        model.tokenizer.model_max_length, getattr(model[0].auto_model.config, "max_position_embeddings", None))
        if isinstance(value, int) and value > 0)
    config_file = directory / "config_sentence_transformers.json"
    metadata = json.loads(config_file.read_text(encoding="utf-8")) if config_file.is_file() else {}
    declared = metadata.get("prompts", {})
    # ST 6.1 adds empty query/document entries; resolution uses only declared templates.
    query_name = next((key for key in ("query", "web_search_query") if key in declared), metadata.get("default_prompt_name"))
    document_name = next((key for key in ("document", "passage", "corpus") if key in declared), metadata.get("default_prompt_name"))
    with torch.inference_mode():
        queries = model.encode_query(QUERIES, prompt_name=query_name, prompt=None if query_name else "",
            batch_size=len(QUERIES), convert_to_tensor=True, show_progress_bar=False).float().cpu().tolist()
        documents = model.encode_document(DOCUMENTS, prompt_name=document_name, prompt=None if document_name else "",
            batch_size=len(DOCUMENTS), convert_to_tensor=True, show_progress_bar=False).float().cpu().tolist()
    output.write_text(json.dumps({"queries": queries, "documents": documents,
        "dimensions": model.get_embedding_dimension(), "max_seq_length": model.max_seq_length,
        "dtype": str(model.dtype), "device_name": torch.cuda.get_device_name(0),
        "peak_cuda_bytes": torch.cuda.max_memory_allocated(),
        "packages": {name: importlib.metadata.version(name) for name in ("torch", "transformers", "sentence-transformers")}}), encoding="utf-8")


async def smoke(args):
    import httpx
    import uvicorn
    from ai_workbench.api.deps import build_runtime_state
    from ai_workbench.api.main import create_app
    from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog
    from ai_workbench.core.models.runtimes.store import RuntimeStore
    from ai_workbench.core.models.store import LocalRuntimeSettingsStore
    from ai_workbench.db.database import get_engine, init_db

    root = args.root.resolve()
    assert platform.system() == "Windows", "Acceptance currently supports Windows only"
    output = root / "build/text-embedding-smoke"
    output.mkdir(parents=True, exist_ok=True)
    database = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    init_db(database)
    state = build_runtime_state(root=root, use_memory=True)
    manager, supervisor = state.model_manager, state.runtime_supervisor
    supervisor.store, supervisor.settings = RuntimeStore(database), LocalRuntimeSettingsStore(database)
    listener, server, task = None, None, None
    report = {"model_ref": args.model_ref, "platform": platform.platform(), "device": args.device, "cases": []}
    try:
        supervisor.assert_available()
        report["runtime_version"] = supervisor.release.version
        expected = None
        if args.native_reference:
            executable = supervisor.executable("sentence-transformers", "cuda")
            env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "VIRTUAL_ENV"))}
            process = await ManagedProcess.start([executable, "-I", "-B", "-X", "utf8", Path(__file__).resolve(),
                "--reference", "--root", root, "--model-ref", args.model_ref],
                env=env, cwd=output, log=RuntimeLog(output / "native-reference.log", root))
            try:
                assert await asyncio.wait_for(process.wait(), 300) == 0, "See native-reference.log"
            finally:
                await process.stop()
            expected = json.loads((output / "native-reference.json").read_text(encoding="utf-8"))
            report["reference"] = {key: value for key, value in expected.items() if key not in ("queries", "documents")}
            print(json.dumps({"stage": "native_reference", **report["reference"]}), flush=True)

        token = secrets.token_urlsafe(32)
        state.model_settings.patch({"external_enabled": True, "external_api_key": token})
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(create_app(runtime_state=state), log_level="error", ws="none"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("The smoke API server did not start")
            await asyncio.sleep(0.02)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", timeout=310,
                headers={"Authorization": f"Bearer {token}"}, trust_env=False) as client:
            async def call(method, path, **kwargs):
                response = await client.request(method, path, **kwargs)
                assert response.is_success, (response.status_code, response.text)
                return response.json()

            information = await call("GET", "/api/models/inspect", params={"kind": "embedding", "model_ref": args.model_ref})
            assert not information["diagnostics"], information
            report["information"] = information
            saved = await call("POST", "/api/models/profiles", json={"name": "Text embedding acceptance", "alias": "embedding-smoke",
                "kind": "embedding", "model_ref": args.model_ref, "source": {"type": "local", "execution_options": {"device": args.device}},
                "external_enabled": True})
            profile = manager.profiles.get(saved["id"])
            path = f"/api/models/profiles/{profile.id}"
            assert profile.source.lifecycle.unload == "manual"
            assert profile.source.execution_options == {"device": args.device, "intraop_threads": 4, "max_batch_size": 1}
            assert profile.parameters == {"query_prompt_name": None, "document_prompt_name": None}
            dimensions = args.expected_dimensions or information["dimensions"]
            assert dimensions is not None

            async def infer(case, texts, **options):
                started = time.monotonic()
                value = await call("POST", "/v1/embeddings", json={"model": profile.alias, "input": texts, **options})
                assert value["model"] == profile.alias and [item["index"] for item in value["data"]] == list(range(len(texts)))
                vectors = [list(struct.unpack("<" + "f" * dimensions, base64.b64decode(item["embedding"])))
                    if isinstance(item["embedding"], str) else item["embedding"] for item in value["data"]]
                assert all(len(row) == dimensions and all(math.isfinite(v) for v in row) and any(row) for row in vectors)
                measurement = {"case": case, "seconds": round(time.monotonic() - started, 3)}
                report["cases"].append(measurement)
                print(json.dumps(measurement), flush=True)
                return vectors

            documents = DOCUMENTS if args.device == "cuda" else DOCUMENTS[:1]
            encoded = await infer("document_autoload", documents)
            adapter = manager._managed_slot(profile).adapter
            first_process = adapter.process.process
            report["worker"] = await adapter._rpc("GET", "/health")
            assert report["worker"]["device"] == args.device
            if args.device == "cpu":
                assert report["worker"]["dtype"] == "torch.float32"
            else:
                compare(encoded, await infer("document_base64", documents, purpose="document", dimensions=dimensions, encoding_format="base64"))
                queries = await infer("query_float", QUERIES, purpose="query")
                compare(queries, await infer("query_base64", QUERIES, purpose="query", encoding_format="base64"))
                if expected:
                    report["document_comparison"] = compare(encoded, expected["documents"])
                    report["query_comparison"] = compare(queries, expected["queries"])
                    assert information["max_seq_length"] == expected["max_seq_length"]
                wrong = await client.post("/v1/embeddings", json={"model": profile.alias, "input": "text", "dimensions": dimensions + 1})
                assert wrong.status_code == 422
                await call("PATCH", "/api/knowledge/settings", json={"hybrid_search_enabled": False})
                base = await call("POST", "/api/knowledge/bases", json={"name": "Acceptance facts", "embedding_model_profile_id": profile.id})
                for index, document in enumerate(DOCUMENTS):
                    result = await call("POST", f"/api/knowledge/bases/{base['id']}/sources", json={"title": str(index), "text": document})
                    assert result["status"] == "indexed"
                report["retrieval"] = []
                for index, query in enumerate(QUERIES):
                    found = await call("POST", "/api/knowledge/search", json={"query": query, "knowledge_base_ids": [base["id"]], "debug": True})
                    assert found["results"][0]["content"] == DOCUMENTS[index], found
                    report["retrieval"].append({"query": query, "first": found["results"][0]})
                assert adapter.process.process is first_process
            await call("POST", path + "/unload")
            assert first_process.returncode is not None and manager.status(profile.id).residency == "unloaded"
            if args.device == "cuda":
                await call("PATCH", path, json={"source": {"type": "local",
                    "execution_options": {"device": "cuda", "intraop_threads": 4, "max_batch_size": 3}}})
                profile = manager.profiles.get(profile.id)
                compare(encoded, await infer("reload_batched_documents", documents))
                adapter = manager._managed_slot(profile).adapter
                reloaded = adapter.process.process
                assert reloaded is not first_process
                compare(queries, await infer("batched_queries", QUERIES, purpose="query"))
                assert adapter.process.process is reloaded
                report["worker_batch_sizes"] = [1, 3]
                await call("POST", path + "/unload")
                assert reloaded.returncode is not None
            report.update(status="passed", release="passed", dimensions=dimensions)
        report_file = output / (args.device + "-report.json")
        report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"text_embedding": "passed", "report": str(report_file)}), flush=True)
    finally:
        if server:
            server.should_exit = True
        if task:
            await task
        if listener:
            listener.close()
        await manager.close()
        await supervisor.close()
        database.dispose()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-ref", required=True, help="Existing directory relative to data/models")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--native-reference", action="store_true", help="Compare with a separate native CUDA process before service inference")
    parser.add_argument("--expected-dimensions", type=int)
    parser.add_argument("--reference", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.native_reference and args.device != "cuda":
        parser.error("--native-reference requires CUDA; CPU acceptance covers short-text service inference and release")
    return args


if __name__ == "__main__":
    args = parse_args()
    if args.reference:
        native_reference(args.root / "data/models" / args.model_ref, args.root / "build/text-embedding-smoke/native-reference.json")
    else:
        asyncio.run(smoke(args))
