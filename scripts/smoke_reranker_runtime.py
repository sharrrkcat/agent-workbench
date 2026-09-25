"""Accept a supplied CrossEncoder using the installed runtime, without model hashes or downloads."""
import argparse
import asyncio
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import secrets
import socket
import sys
import time

CASES = [
    {"name": "english", "query": "Who wrote To Kill a Mockingbird?", "documents": [
        "A soccer match lasts ninety minutes.",
        "Harper Lee wrote To Kill a Mockingbird, published in 1960.",
        "The weather forecast predicts rain and cool temperatures. " * 30,
        "Harper Lee wrote To Kill a Mockingbird, published in 1960.",
        "Jane Austen wrote Pride and Prejudice.",
    ]},
    {"name": "chinese", "query": "哪颗行星被称为红色星球？", "documents": [
        "木星是太阳系中体积最大的行星。",
        "火星因为表面富含氧化铁而呈现红色，因此被称为红色星球。",
        "海洋覆盖了地球表面的大部分区域。" * 15,
    ]},
]


def compare(actual, expected):
    assert len(actual) == len(expected) and actual
    assert all(math.isfinite(value) for value in actual)
    error = max(abs(left - right) for left, right in zip(actual, expected))
    assert error <= 0.005, {"max_absolute_error": error}
    for left in range(len(expected)):
        for right in range(len(expected)):
            if expected[left] - expected[right] > 0.01:
                assert actual[left] > actual[right], "Clearly separated native scores changed order"
    return {"max_absolute_error": error, "separated_pair_order": "passed"}


def native_reference(root, model_ref, output):
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false", HF_HUB_DISABLE_PROGRESS_BARS="1")
    sys.path.insert(0, str(root / "ai_workbench/workers"))
    from common import require_offline, safe_reference
    require_offline()
    directory = (root / "data/models" / safe_reference(model_ref)).resolve()
    assert directory.is_relative_to((root / "data/models").resolve())
    import torch
    from sentence_transformers import CrossEncoder
    torch.set_num_threads(4)
    model = CrossEncoder(str(directory), device="cuda", backend="torch", local_files_only=True,
        trust_remote_code=False, model_kwargs={"dtype": "auto", "local_files_only": True, "trust_remote_code": False},
        processor_kwargs={"local_files_only": True, "trust_remote_code": False},
        config_kwargs={"local_files_only": True, "trust_remote_code": False})
    result = {"dtype": str(model.dtype), "activation": type(model.activation_fn).__name__,
        "max_seq_length": model.max_seq_length, "device_name": torch.cuda.get_device_name(0), "cases": {},
        "packages": {name: importlib.metadata.version(name) for name in ("torch", "transformers", "sentence-transformers")}}
    with torch.inference_mode():
        for case in CASES:
            pairs = [(case["query"], document) for document in case["documents"]]
            result["cases"][case["name"]] = {str(batch): model.predict(pairs, batch_size=batch,
                show_progress_bar=False, convert_to_tensor=True).float().cpu().tolist() for batch in (1, 3)}
    result["peak_cuda_bytes"] = torch.cuda.max_memory_allocated()
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


async def smoke(args):
    import httpx
    import uvicorn
    from ai_workbench.api.deps import build_runtime_state
    from ai_workbench.api.main import create_app
    from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog
    from ai_workbench.core.models.runtimes.store import RuntimeStore
    from ai_workbench.core.models.store import LocalRuntimeSettingsStore
    from ai_workbench.db.database import get_engine, init_db
    from ai_workbench.workers.reranker_catalog import load_configuration

    root = args.root.resolve()
    assert platform.system() == "Windows", "Acceptance currently supports Windows only"
    load_configuration(root / "data/models", args.model_ref)
    output = root / "build/reranker-smoke"
    output.mkdir(parents=True, exist_ok=True)
    database = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    init_db(database)
    state = build_runtime_state(root=root, use_memory=True)
    manager, supervisor = state.model_manager, state.runtime_supervisor
    supervisor.store, supervisor.settings = RuntimeStore(database), LocalRuntimeSettingsStore(database)
    listener, server, task = None, None, None
    report = {"model_ref": args.model_ref, "device": args.device, "platform": platform.platform(), "cases": []}
    try:
        supervisor.assert_available()
        report["runtime_version"] = supervisor.release.version
        expected = None
        if args.device == "cuda":
            print(json.dumps({"stage": "native_reference"}), flush=True)
            executable = supervisor.executable("cross-encoder", "cuda")
            env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "VIRTUAL_ENV"))}
            process = await ManagedProcess.start([executable, "-I", "-B", "-X", "utf8", Path(__file__).resolve(),
                "--reference", "--root", root, "--model-ref", args.model_ref], env=env, cwd=output,
                log=RuntimeLog(output / "native-reference.log", root))
            try:
                assert await asyncio.wait_for(process.wait(), 300) == 0, "See native-reference.log"
            finally:
                await process.stop()
            expected = json.loads((output / "native-reference.json").read_text(encoding="utf-8"))
            report["reference"] = {key: value for key, value in expected.items() if key != "cases"}

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

            information = await call("GET", "/api/models/inspect", params={"kind": "reranker", "model_ref": args.model_ref})
            assert not information["diagnostics"] and information["architecture"] == "cross-encoder"
            report["information"] = information
            saved = await call("POST", "/api/models/profiles", json={"name": "Reranker acceptance", "alias": "reranker-smoke",
                "kind": "reranker", "model_ref": args.model_ref, "source": {"type": "local", "execution_options": {"device": args.device}},
                "external_enabled": True})
            profile = manager.profiles.get(saved["id"])
            route = f"/api/models/profiles/{profile.id}"
            assert profile.parameters == {} and profile.source.lifecycle.unload == "manual"
            assert profile.source.execution_options == {"device": args.device, "intraop_threads": 4, "max_batch_size": 1}
            assert (await call("GET", "/v1/models", params={"kind": "reranker"}))["data"][0]["id"] == profile.alias

            async def infer(case, batch):
                started = time.monotonic()
                value = await call("POST", "/v1/rerank", json={"model": profile.alias, "query": case["query"],
                    "documents": case["documents"], "return_documents": True})
                rows = value["results"]
                assert value["model"] == profile.alias and "usage" not in value
                assert sorted(row["index"] for row in rows) == list(range(len(case["documents"])))
                assert [row["relevance_score"] for row in rows] == sorted((row["relevance_score"] for row in rows), reverse=True)
                scores = [0.0] * len(rows)
                for row in rows:
                    scores[row["index"]] = row["relevance_score"]
                    assert row["document"]["text"] == case["documents"][row["index"]]
                assert all(math.isfinite(score) for score in scores) and scores[1] > scores[0]
                measurement = {"case": case["name"], "batch_size": batch, "seconds": round(time.monotonic() - started, 3),
                    "order": [row["index"] for row in rows], "scores": scores}
                if expected:
                    measurement.update(compare(scores, expected["cases"][case["name"]][str(batch)]))
                report["cases"].append(measurement)
                print(json.dumps(measurement), flush=True)
                return rows

            cases = CASES if args.device == "cuda" else [{**CASES[0], "documents": CASES[0]["documents"][:2]}]
            print(json.dumps({"stage": "service_inference", "device": args.device}), flush=True)
            for case in cases:
                rows = await infer(case, 1)
            adapter = manager._managed_slot(profile).adapter
            first_process = adapter.process.process
            health = await adapter._rpc("GET", "/health")
            assert health["device"] == args.device
            assert health["dtype"] == (expected["dtype"] if expected else "torch.float32")
            report["worker"] = {key: health[key] for key in ("device", "device_name", "dtype")}
            limited = await call("POST", "/v1/rerank", json={"model": profile.alias, "query": cases[-1]["query"],
                "documents": cases[-1]["documents"], "top_n": 1})
            assert len(limited["results"]) == 1 and limited["results"][0]["index"] == rows[0]["index"]
            assert "document" not in limited["results"][0] and adapter.process.process is first_process
            await call("POST", route + "/unload")
            assert first_process.returncode is not None and manager.status(profile.id).residency == "unloaded"

            if args.device == "cuda":
                await call("PATCH", route, json={"source": {"type": "local", "execution_options": {"max_batch_size": 3}}})
                profile = manager.profiles.get(profile.id)
                for case in CASES:
                    await infer(case, 3)
                reloaded = manager._managed_slot(profile).adapter.process.process
                assert reloaded is not first_process
                await call("POST", route + "/unload")
                assert reloaded.returncode is not None
                print(json.dumps({"stage": "knowledge", "embedding_model_ref": args.embedding_model_ref}), flush=True)
                embedding = await call("POST", "/api/models/profiles", json={"name": "RAG acceptance embedding", "alias": "rag-embedding",
                    "kind": "embedding", "model_ref": args.embedding_model_ref, "source": {"type": "local"}})
                base = await call("POST", "/api/knowledge/bases", json={"name": "Reranker facts", "embedding_model_profile_id": embedding["id"]})
                for index in (0, 1, 4):
                    indexed = await call("POST", f"/api/knowledge/bases/{base['id']}/sources", json={"title": str(index), "text": CASES[0]["documents"][index]})
                    assert indexed["status"] == "indexed"
                # Release the query embedder before scoring, fitting acceptance on a 4 GiB GPU.
                await call("PATCH", f"/api/models/profiles/{embedding['id']}", json={"source": {
                    "type": "local", "lifecycle": {"unload": "after_request"}}})
                assert (await call("GET", f"/api/knowledge/bases/{base['id']}"))["index_status"] != "needs_reindex"
                await call("PATCH", "/api/knowledge/settings", json={"reranker_enabled": True,
                    "reranker_model_profile_id": profile.id})
                found = await call("POST", "/api/knowledge/search", json={"query": CASES[0]["query"],
                    "knowledge_base_ids": [base["id"]], "debug": True, "top_k": 3})
                assert found["metadata"]["reranker_used"] and not found["metadata"]["rerank_fallback"]
                assert found["results"][0]["content"] == CASES[0]["documents"][1], found
                assert all(row["rerank_score"] is not None for row in found["results"])
                report["knowledge"] = {"embedding_model_ref": args.embedding_model_ref, "metadata": found["metadata"],
                    "order": [row["content"] for row in found["results"]]}
                await call("POST", route + "/unload")
            report.update(status="passed", release="passed")
            report_file = output / (args.device + "-report.json")
            report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"reranker": "passed", "report": str(report_file)}), flush=True)
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
    parser.add_argument("--model-ref", required=True, help="Existing CrossEncoder directory relative to data/models")
    parser.add_argument("--embedding-model-ref", help="Existing local text embedding directory for CUDA Knowledge acceptance")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--reference", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.device == "cuda" and not args.reference and not args.embedding_model_ref:
        parser.error("CUDA acceptance requires --embedding-model-ref for the Knowledge search")
    return args


if __name__ == "__main__":
    args = parse_args()
    if args.reference:
        native_reference(args.root.resolve(), args.model_ref, args.root / "build/reranker-smoke/native-reference.json")
    else:
        asyncio.run(smoke(args))
