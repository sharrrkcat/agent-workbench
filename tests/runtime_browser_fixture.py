"""Temporary-root runtime fixtures for the settings browser tests."""
import asyncio
import os

from fastapi import Body

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.catalog import catalog


def install_runtime_fixture(app, root):
    state = app.state.runtime_state
    supervisor = state.runtime_supervisor
    cache = supervisor.base / ".cache"
    shared = cache / "shared.bin"
    exclusive = cache / "exclusive.bin"
    installed = supervisor.base / "py/torch-cpu/1.0.0/Lib/shared.bin"
    behavior = {"slow": False, "fail": False}

    @app.post("/__test__/runtimes")
    async def configure(values: dict = Body(default={})):
        if supervisor.active_job:
            await supervisor.cancel(supervisor.active_job)
        supervisor.store._jobs.clear()
        supervisor.entries = catalog("windows", "x86_64")
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
