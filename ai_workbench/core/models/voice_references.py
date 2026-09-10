"""Ephemeral, credential-scoped audio files; no persistent voice records."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import re
import secrets
import shutil
import threading

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.time import isoformat_utc, utc_now
from ai_workbench.workers.audio_catalog import MAX_REFERENCE_BYTES


def credential_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass
class VoiceReference:
    id: str
    path: Path
    size: int
    profile_id: str = ""
    binding: str = ""
    credential: str = ""
    expires_at: datetime | None = None
    active: int = 1
    valid: bool = True

    @property
    def published(self):
        return self.expires_at is not None


class VoiceReferences:
    def __init__(self, root: Path, *, clock=utc_now, max_count=64, max_bytes=128 * 1024 * 1024):
        self.clock, self.max_count, self.max_bytes = clock, max_count, max_bytes
        self._lock = threading.RLock()
        self._entries: dict[str, VoiceReference] = {}
        self._closed = False
        parent = root / "data" / "tmp" / "voice-references"
        if parent.resolve() != parent.absolute():
            raise ModelError("VOICE_STORAGE_UNAVAILABLE", "Temporary voice storage must not be redirected.", 503)
        parent.mkdir(parents=True, exist_ok=True)
        for old in parent.iterdir():
            if re.fullmatch(r"session-[0-9a-f]{32}", old.name) and old.is_dir() and not old.is_symlink():
                if old.resolve().parent != parent.resolve():
                    raise ModelError("VOICE_STORAGE_UNAVAILABLE", "Temporary voice storage is invalid.", 503)
                shutil.rmtree(old)
        self.base = parent / ("session-" + secrets.token_hex(16))
        self.base.mkdir()

    def stage(self, data: bytes, audio_format: str) -> VoiceReference:
        if audio_format not in {"wav", "mp3"} or not isinstance(data, bytes) or not data:
            raise ModelError("INVALID_AUDIO", "Provide a nonempty WAV or MP3 reference.")
        if len(data) > MAX_REFERENCE_BYTES:
            raise ModelError("REQUEST_TOO_LARGE", "Reference audio exceeds 8 MiB.", 413)
        with self._lock:
            self._cleanup()
            if self._closed:
                raise ModelError("MODEL_UNAVAILABLE", "Model services are shutting down.", 503)
            if len(self._entries) >= self.max_count or sum(item.size for item in self._entries.values()) + len(data) > self.max_bytes:
                raise ModelError("VOICE_REFERENCE_LIMIT", "Temporary voice storage is full.", 429)
            identifier = "tmpv_" + secrets.token_urlsafe(24)
            path = self.base / (identifier + "." + audio_format)
            try:
                with path.open("xb") as output:
                    output.write(data)
            except OSError as exc:
                path.unlink(missing_ok=True)
                raise ModelError("VOICE_STORAGE_UNAVAILABLE", "Reference audio could not be stored.", 503) from exc
            entry = VoiceReference(identifier, path, len(data))
            self._entries[identifier] = entry
            return entry

    def publish(self, entry, profile_id, binding, credential):
        with self._lock:
            if not entry.valid or self._closed or self._entries.get(entry.id) is not entry:
                raise ModelError("VOICE_UNAVAILABLE", "The reference is no longer available.", 404)
            entry.profile_id, entry.binding, entry.credential = profile_id, binding, credential
            entry.expires_at = self.clock() + timedelta(minutes=30)
            entry.active -= 1
            return entry

    def _get(self, identifier, profile_id, binding, credential, now):
        entry = self._entries.get(identifier)
        if entry and entry.published and entry.expires_at <= now:
            entry.valid = False
        if (not entry or not entry.valid or not entry.published or entry.profile_id != profile_id
                or entry.binding != binding or entry.credential != credential):
            self._cleanup(now)
            raise ModelError("VOICE_UNAVAILABLE", "Voice ID is unavailable for this model and credential.", 404)
        return entry

    def check(self, identifier, profile_id, binding, credential):
        with self._lock:
            return self._get(identifier, profile_id, binding, credential, self.clock())

    def admit(self, identifier, profile_id, binding, credential):
        with self._lock:
            now = self.clock()
            entry = self._get(identifier, profile_id, binding, credential, now)
            entry.expires_at = max(entry.expires_at, now + timedelta(minutes=15))
            entry.active += 1
            return entry

    def release(self, entry):
        with self._lock:
            entry.active -= 1
            if entry.active < 0:
                raise RuntimeError("Reference lease released twice")
            self._cleanup()

    def delete(self, identifier, profile_id, binding, credential):
        with self._lock:
            entry = self._get(identifier, profile_id, binding, credential, self.clock())
            if entry.active:
                raise ModelError("VOICE_REFERENCE_IN_USE", "Wait for admitted speech requests before deleting this voice.", 409)
            entry.valid = False
            self._cleanup()

    def list(self, profile_id, binding, credential):
        with self._lock:
            now = self.clock()
            self._cleanup(now)
            return [{"id": entry.id, "source": "temporary", "language": "en-US",
                     "expires_at": isoformat_utc(entry.expires_at)} for entry in self._entries.values()
                    if entry.valid and entry.published and entry.expires_at > now
                    and (entry.profile_id, entry.binding, entry.credential) == (profile_id, binding, credential)]

    def invalidate(self, profile_id=None):
        with self._lock:
            for entry in self._entries.values():
                if profile_id is None or entry.profile_id == profile_id:
                    entry.valid = False
            self._cleanup()

    def _cleanup(self, now=None):
        now = now if now is not None else self.clock()
        for identifier, entry in list(self._entries.items()):
            if entry.published and entry.expires_at <= now:
                entry.valid = False
            if not entry.active and (not entry.valid or not entry.published):
                entry.path.unlink(missing_ok=True)
                del self._entries[identifier]
        if self._closed and not self._entries and self.base.exists():
            self.base.rmdir()

    def close(self):
        with self._lock:
            self._closed = True
            for entry in self._entries.values():
                entry.valid = False
            self._cleanup()
