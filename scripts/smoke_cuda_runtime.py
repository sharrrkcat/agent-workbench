"""Verify GGUF CUDA offload using the installed local runtime; installation is explicit."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from ai_workbench.core.models.manager import ModelManager
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.runtimes.supervisor import RuntimeSupervisor
from ai_workbench.core.models.schema import ChatRequest, ModelProfile
from ai_workbench.core.models.store import LocalRuntimeSettingsStore, ModelProfileStore, ModelSettingsStore, ProviderProfileStore
from ai_workbench.db import migrations
from ai_workbench.db.database import get_engine


async def smoke(root: Path, model_ref: str | None, install_only: bool = False):
    engine = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    if migrations.current_revision(engine) != migrations.HEAD_REVISION:
        raise RuntimeError("Upgrade the database to Alembic head before running this smoke test")
    supervisor = RuntimeSupervisor(root, RuntimeStore(engine), LocalRuntimeSettingsStore(engine))
    manager = ModelManager(ModelProfileStore(), ProviderProfileStore(), ModelSettingsStore(), runtime_supervisor=supervisor)
    try:
        if install_only:
            job = await supervisor.submit('install')
            last = None
            while supervisor.task and not supervisor.task.done():
                current = supervisor.store.job(job.id)
                bucket = int(current.progress_current * 10 / current.progress_total) if current.progress_total else None
                key = current.stage, bucket
                if key != last:
                    print(json.dumps({"stage": current.stage, "bytes": current.progress_current, "total": current.progress_total}), flush=True)
                    last = key
                await asyncio.wait({supervisor.task}, timeout=1)
            result = supervisor.store.job(job.id)
            print(json.dumps({"installation_job": result.id, "state": result.state, "error_code": result.error_code}), flush=True)
            if result.state != "completed":
                print(supervisor.log_text(result.id), flush=True)
                raise RuntimeError("Local runtime installation failed")
            return
        supervisor.assert_available()
        profile = manager.profiles.create(ModelProfile(name='CUDA smoke', alias='cuda-smoke', kind='llm', model_ref=model_ref, capabilities={'streaming': True}, source={'type': 'local', 'execution_options': {'gpu_layers': 'auto', 'context_size': 4096}}))
        loaded = await manager.load(profile.id)
        assert loaded.state == "ready" and loaded.runtime.gpu_layers_loaded > 0
        print(json.dumps({"loaded": loaded.model_dump(mode="json")}), flush=True)
        request = ChatRequest(model=profile.alias, messages=[{"role": "user", "content": "Say hello in one short sentence."}],
                              temperature=0, max_tokens=32)
        reply = await manager.chat(profile.id, request)
        assert reply.message.content
        print(json.dumps({"nonstream": reply.model_dump(mode="json")}), flush=True)
        chunks = [chunk async for chunk in manager.chat_stream(profile.id, request.model_copy(update={"stream": True}))]
        assert any(chunk.delta.content for chunk in chunks) and any(chunk.finish_reason for chunk in chunks)
        print(json.dumps({"stream_chunks": len(chunks), "finish": chunks[-1].finish_reason}), flush=True)
        unloaded = await manager.unload(profile.id)
        assert unloaded.residency == "unloaded" and unloaded.runtime.device_name is None
        reloaded = await manager.load(profile.id)
        assert reloaded.state == "ready" and reloaded.runtime.gpu_layers_loaded > 0
        await manager.unload(profile.id)
        manager.profiles.update(profile.id, {"source": {"type": "local", "execution_options": {"gpu_layers": 1, "context_size": 4096}}})
        manual = await manager.load(profile.id)
        assert manual.state == "ready" and manual.runtime.gpu_layers_loaded == 1
        await manager.unload(profile.id)
        print(json.dumps({"reload": "passed", "manual_layers": manual.runtime.gpu_layers_loaded, "final_state": manager.status(profile.id).state}), flush=True)
    finally:
        await manager.close()
        await supervisor.close()
        engine.dispose()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-ref", help="An existing GGUF model directory relative to data/models")
    parser.add_argument("--install-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.install_only and not args.model_ref:
        parser.error("--model-ref is required for CUDA acceptance; use --install-only to install")
    return args


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(smoke(args.root.resolve(), args.model_ref, args.install_only))
