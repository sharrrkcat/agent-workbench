"""Request-scoped ASR files, independent of temporary TTS voice references."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import re
import shutil
from uuid import uuid4

from ai_workbench.core.models.errors import ModelError


class ASRInputs:
    def __init__(self, root: Path):
        parent = root / "data/tmp/asr-inputs"
        if parent.resolve() != parent.absolute():
            raise ModelError("MODEL_UNAVAILABLE", "Temporary ASR storage must not be redirected.", 503)
        parent.mkdir(parents=True, exist_ok=True)
        for old in parent.iterdir():
            if re.fullmatch(r"session-[0-9a-f]{32}", old.name) and old.is_dir():
                if old.resolve() != old.absolute():
                    raise ModelError("MODEL_UNAVAILABLE", "Temporary ASR storage contains a redirected session.", 503)
                shutil.rmtree(old)
        self.base = parent / ("session-" + uuid4().hex)
        self.base.mkdir()

    def _write(self, data, audio_format):
        path = self.base / (uuid4().hex + "." + audio_format)
        try:
            with path.open("xb") as output:
                output.write(data)
        except OSError as exc:
            path.unlink(missing_ok=True)
            raise ModelError("MODEL_UNAVAILABLE", "Temporary ASR input could not be stored.", 503) from exc
        return path

    @asynccontextmanager
    async def stage(self, data, audio_format):
        pending = asyncio.create_task(asyncio.to_thread(self._write, data, audio_format))
        try:
            path = await asyncio.shield(pending)
        except asyncio.CancelledError:
            try:
                path = await pending
            except ModelError:
                pass
            else:
                await asyncio.to_thread(path.unlink, missing_ok=True)
            raise
        try:
            yield path.name
        finally:
            await asyncio.to_thread(path.unlink, missing_ok=True)

    def close(self):
        if self.base.exists():
            self.base.rmdir()
