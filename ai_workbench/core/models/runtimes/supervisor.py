from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import ssl
import sysconfig
import tarfile
import threading
import time
import zipfile

import httpx

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.catalog import CATALOG_ROOT, catalog, find_entry, text_digest, worker_digest
from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog
from ai_workbench.core.models.runtimes.schema import (
    CacheCleanupResult, Installation, RuntimeArtifact, RuntimeJob, StorageUsage, TERMINAL,
)
from ai_workbench.core.models.runtimes.storage import is_link, scan_storage
from ai_workbench.core.time import utc_now


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


async def file_digest(path: Path) -> str:
    task = asyncio.create_task(asyncio.to_thread(sha256, path))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def contained(root: Path, path: Path) -> Path:
    if not path.resolve().is_relative_to(root.resolve()) or path.resolve() == root.resolve():
        raise ModelError("RUNTIME_BROKEN", "Runtime path escapes its installation directory.", 503)
    return path


def remove_owned(root: Path, path: Path):
    contained(root, path)
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def installed_file(base: Path, target: Path, name: str, allow_interpreter=False) -> Path:
    # Linux venv entry points link to the shared, runtime-owned Python install.
    from ai_workbench.core.models.runtimes.schema import relative_ref
    relative_ref(name)
    path = target / name
    resolved = path.resolve()
    if resolved.is_relative_to(target.resolve()):
        return path
    if allow_interpreter and name in {"bin/python", "bin/python3", "bin/python3.12"} and resolved.is_relative_to((base / "python").resolve()):
        return path
    raise ModelError("RUNTIME_BROKEN", "Installed file escapes its runtime directory.", 503)


def runtime_inventory(base: Path, target: Path, allow_interpreter, cancelled):
    from ai_workbench.core.models.runtimes.schema import relative_ref
    resolved_target = target.resolve()
    shared_python = (base / "python").resolve()
    parents = {target: resolved_target}
    files = {}
    for path in target.rglob("*"):
        if cancelled.is_set():
            raise InterruptedError()
        name = path.relative_to(target).as_posix()
        if "__pycache__" in path.relative_to(target).parts:
            continue
        relative_ref(name)
        parent = parents.get(path.parent)
        if parent is None:
            parent = parents[path.parent] = path.parent.resolve()
        info = path.lstat()
        resolved = path.resolve() if is_link(info) else parent / path.name
        if not resolved.is_relative_to(resolved_target) and not (
            allow_interpreter and name in {"bin/python", "bin/python3", "bin/python3.12"}
            and resolved.is_relative_to(shared_python)
        ):
            raise ModelError("RUNTIME_BROKEN", "Installed file escapes its runtime directory.", 503)
        if path.is_dir():
            parents[path] = resolved
        elif path.is_file():
            files[name] = (path, path.stat())
    return files


async def file_work(work):
    cancelled = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(work, cancelled))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        await asyncio.gather(task, return_exceptions=True)
        raise


def inventory_hashes(base, target, allow_interpreter, cancelled):
    result = {}
    for name, (path, _info) in sorted(runtime_inventory(base, target, allow_interpreter, cancelled).items()):
        if cancelled.is_set():
            raise InterruptedError()
        result[name] = sha256(path)
    return result


def extract_archive(archive: Path, target: Path, archive_format: str):
    target.mkdir(parents=True, exist_ok=True)

    def destination(name):
        if "\\" in name or ":" in name or ".." in Path(name).parts or Path(name).is_absolute():
            raise ModelError("RUNTIME_BROKEN", "Unsafe archive member.", 503)
        return contained(target, target / name)

    if archive_format == "zip":
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                path = destination(member.orig_filename)
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ModelError("RUNTIME_BROKEN", "Archive links are not supported in ZIP files.", 503)
                if member.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(member) as reader, path.open("wb") as writer:
                        shutil.copyfileobj(reader, writer)
    else:
        with tarfile.open(archive, "r:gz") as source:
            links = []
            for member in source:
                if member.name in {".", "./"}:
                    continue
                path = destination(member.name)
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(member) as reader, path.open("wb") as writer:
                        shutil.copyfileobj(reader, writer)
                    path.chmod(member.mode & 0o755)
                elif member.issym():
                    if Path(member.linkname).is_absolute():
                        raise ModelError("RUNTIME_BROKEN", "Unsafe archive link.", 503)
                    contained(target, path.parent / member.linkname)
                    links.append((path, member.linkname))
                else:
                    raise ModelError("RUNTIME_BROKEN", "Unsupported archive member.", 503)
            for path, link in links:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(link)
            for path, _ in links:
                contained(target, path)


class RuntimeSupervisor:
    def __init__(self, root, store, events=None, entries=None, transport=None):
        self.root = Path(root).resolve()
        self.base = self.root / "data" / "runtimes"
        self.logs = self.root / "data" / "logs" / "runtimes"
        self.store = store
        self.events = events
        self.entries = entries if entries is not None else catalog()
        self.transport = transport
        self.task: asyncio.Task | None = None
        self.active_job: str | None = None
        self.blocked: tuple | None = None
        self.closed = False
        self.manager = None
        self._verified: dict[str, tuple] = {}
        self.store.interrupt_unfinished()
        for job in self.store.jobs():
            if job.state == "interrupted":
                staging = self.base / ".staging" / job.id
                if staging.exists():
                    remove_owned(self.base, staging)

    def entry(self, runtime_id, variant):
        return find_entry(self.entries, runtime_id, variant)

    def directory(self, entry):
        path = self.base / (f"llama-server/{entry.version}/{entry.variant}" if entry.runtime_id == "llama-server" else f"py/{entry.variant}/{entry.version}")
        return contained(self.base, path)

    def installation(self, runtime_id, variant):
        entry = self.entry(runtime_id, variant)
        key = f"{runtime_id}/{variant}"
        value = next((item for item in self.store.installations() if item.id == key), None)
        value = value or Installation(id=key, runtime_id=runtime_id, variant=variant, version=entry.version)
        if not entry.supported:
            value.state, value.error_code = "unsupported", "RUNTIME_UNSUPPORTED"
        elif value.version != entry.version or value.state == "installed" and not (self.directory(entry) / "installation.json").is_file():
            value.state, value.error_code = "broken", "RUNTIME_BROKEN"
        return value

    def installations(self):
        return [self.installation(entry.runtime_id, entry.variant) for entry in self.entries]

    def assert_available(self, runtime_id, variant):
        value = self.installation(runtime_id, variant)
        codes = {"not_installed": "RUNTIME_NOT_INSTALLED", "installing": "RUNTIME_INSTALLING",
                 "broken": "RUNTIME_BROKEN", "unsupported": "RUNTIME_UNSUPPORTED", "interrupted": "RUNTIME_BROKEN"}
        if value.state != "installed":
            raise ModelError(codes[value.state], "Install or repair the selected runtime in Models settings.", 503,
                {"runtime_id": runtime_id, "variant": variant, "action": "install" if value.state in {"not_installed", "broken", "interrupted"} else "view_runtime"})
        return self.entry(runtime_id, variant)

    async def verify(self, entry):
        value = self.installation(entry.runtime_id, entry.variant)
        target = self.directory(entry)

        def check(cancelled):
            manifest = target / "installation.json"
            if sha256(manifest) != value.manifest_sha256:
                raise ValueError("manifest mismatch")
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data["artifact_sha256"] != entry.sha256 or data["version"] != entry.version:
                raise ValueError("artifact mismatch")
            if entry.additional_artifacts and data["additional_artifact_sha256"] != [artifact.sha256 for artifact in entry.additional_artifacts]:
                raise ValueError("additional artifacts mismatch")
            if entry.runtime_id == "python-worker" and data.get("worker_sha256") != entry.worker_sha256:
                raise ValueError("worker code mismatch")
            if entry.python_artifact and data.get("python_artifact") != entry.python_artifact.model_dump():
                raise ValueError("interpreter artifact mismatch")
            files = data["files"]
            if not isinstance(files, dict) or not files:
                raise ValueError("empty installation")
            inventory = runtime_inventory(self.base, target, entry.archive_format == "venv", cancelled)
            inventory.pop("installation.json", None)
            if set(files) != set(inventory):
                raise ValueError("installation file inventory changed")
            snapshot = [(name, info.st_size, info.st_mtime_ns) for name, (_path, info) in sorted(inventory.items())]
            signature = (value.manifest_sha256, tuple(snapshot))
            if self._verified.get(value.id) != signature:
                for name, digest in files.items():
                    if cancelled.is_set():
                        raise InterruptedError()
                    if sha256(inventory[name][0]) != digest:
                        raise ValueError("installed file mismatch")
            executable = inventory[data["executable"]][0]
            return executable, signature

        try:
            executable, signature = await file_work(check)
            self._verified[value.id] = signature
            return executable
        except (OSError, ValueError, KeyError, TypeError, ModelError) as exc:
            value.state, value.error_code = "broken", "RUNTIME_BROKEN"
            self.store.save_installation(value)
            self._emit_installation(value)
            raise ModelError("RUNTIME_BROKEN", "Runtime integrity check failed. Reinstall it from Models settings.", 503) from exc

    def _emit_installation(self, value):
        if self.events:
            self.events.emit("runtime_status", session_id="", payload={"installation": value.model_dump(mode="json")})
        if self.manager:
            self.manager.runtime_changed(value.runtime_id, value.variant)

    def _save_job(self, job):
        self.store.save_job(job)
        if self.events:
            self.events.emit("runtime_job_updated", session_id="", payload={"job": self.public_job(job)})

    @staticmethod
    def public_job(job):
        return job.model_dump(mode="json", exclude={"log_path"})

    async def storage(self):
        task = asyncio.create_task(asyncio.to_thread(scan_storage, self.base))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def _cache_usage(self):
        snapshot = await self.storage()
        group = next(group for group in snapshot.groups if group.id == ".cache")
        return StorageUsage.model_validate(group.model_dump(include=set(StorageUsage.model_fields)))

    def _cache_directory(self):
        cache = self.base / ".cache"
        for path in (self.base.parent, self.base, cache):
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if is_link(info) or not stat.S_ISDIR(info.st_mode):
                raise ModelError("RUNTIME_BROKEN", "The managed cache directory is redirected or invalid.", 503)
        pending = [cache] if cache.exists() else []
        while pending:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    info = path.lstat()
                    if is_link(info):
                        if not path.resolve().is_relative_to(cache):
                            raise ModelError("RUNTIME_BROKEN", "A cache link escapes the managed cache directory.", 503)
                    elif stat.S_ISDIR(info.st_mode):
                        pending.append(path)
        return cache

    @staticmethod
    def _uv():
        uv = Path(sysconfig.get_path("scripts")) / ("uv.exe" if os.name == "nt" else "uv")
        if not uv.is_file():
            raise ModelError("RUNTIME_BROKEN", "The application uv dependency is missing.", 503)
        return uv

    async def submit_cache(self, mode):
        if self.closed:
            raise ModelError("MODEL_UNAVAILABLE", "Runtime supervisor is shutting down.", 503)
        if self.active_job is not None:
            raise ModelError("RUNTIME_INSTALLING", "Another runtime maintenance task is in progress.", 409)
        job = RuntimeJob(operation=f"cache_{mode}", result=CacheCleanupResult())
        job.log_path = f"{job.id}.log"
        self.active_job = job.id
        try:
            self._save_job(job)
            self.task = asyncio.create_task(self._execute_cache(job, mode))
            return job
        except BaseException:
            self.active_job = None
            raise

    async def _execute_cache(self, job, mode):
        log = None
        try:
            log = RuntimeLog(self.logs / job.log_path, self.root)
            job.state = "running"
            self._stage(job, "scanning_cache", log)
            job.result.before = await self._cache_usage()
            self._save_job(job)
            validation = asyncio.create_task(asyncio.to_thread(self._cache_directory))
            try:
                cache = await asyncio.shield(validation)
            except asyncio.CancelledError:
                await asyncio.gather(validation, return_exceptions=True)
                raise
            env = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(("UV_", "PIP_", "PYTHON", "VIRTUAL_ENV"))}
            self._stage(job, "pruning_cache" if mode == "prune" else "cleaning_cache", log)
            await self._command([self._uv(), "cache", mode, "--cache-dir", cache, "--no-config", "--offline"],
                                env, self.root, log)
            job.state, job.stage = "completed", "completed"
            log.write("Cache maintenance completed.")
        except asyncio.CancelledError:
            job.state, job.error_code, job.cancel_requested = "cancelled", "RUNTIME_CANCELLED", True
            if log:
                log.write("Cache maintenance cancelled; already removed entries stay removed.")
        except Exception as exc:
            job.state = "failed"
            job.error_code = exc.code if isinstance(exc, ModelError) and exc.code != "RUNTIME_INSTALL_FAILED" else "RUNTIME_CLEANUP_FAILED"
            if log:
                log.write(f"Cache maintenance failed: {job.error_code} ({type(exc).__name__}).")
        finally:
            try:
                job.result.after = await self._cache_usage()
                if log:
                    log.write("Cache accounting: " + job.result.model_dump_json())
            except Exception as exc:
                if log:
                    log.write(f"Cache accounting unavailable: {type(exc).__name__}.")
            job.finished_at = utc_now()
            try:
                self._save_job(job)
            finally:
                self.active_job = None
            self._prune_logs(None)

    async def submit(self, runtime_id, variant, operation):
        if self.closed:
            raise ModelError("MODEL_UNAVAILABLE", "Runtime supervisor is shutting down.", 503)
        if self.active_job is not None:
            raise ModelError("RUNTIME_INSTALLING", "Another runtime task is in progress.", 409)
        entry = self.entry(runtime_id, variant)
        if not entry.supported:
            raise ModelError("RUNTIME_UNSUPPORTED", "This runtime variant is not enabled on this platform.", 422)
        if self.manager:
            self.manager.require_runtime_idle(runtime_id, variant)
        value = self.installation(runtime_id, variant)
        job = RuntimeJob(runtime_id=runtime_id, variant=variant, version=entry.version, operation=operation)
        job.log_path = f"{job.id}.log"
        # Reserve the global slot before any await, including integrity checks.
        self.active_job = job.id
        self.blocked = (runtime_id, variant)
        try:
            if operation == "install" and value.state == "installed":
                try:
                    await self.verify(entry)
                except ModelError:
                    value = self.installation(runtime_id, variant)
                else:
                    job.state, job.stage, job.finished_at = "completed", "already_installed", utc_now()
                    self._save_job(job)
                    self.active_job = None
                    self.blocked = None
                    return job
            if self.manager:
                await self.manager.invalidate_runtime(runtime_id, variant)
            value.state, value.job_id, value.error_code = "installing", job.id, None
            self.store.save_installation(value)
            self._save_job(job)
            self._emit_installation(value)
            self.task = asyncio.create_task(self._execute(job, entry))
            return job
        except BaseException:
            self.active_job = None
            self.blocked = None
            raise

    async def cancel(self, job_id):
        job = self.store.job(job_id)
        if job.state not in TERMINAL and job.id == self.active_job:
            if not job.cancel_requested:
                job.cancel_requested = True
                self._save_job(job)
                # Let the task enter its cleanup block before delivering cancellation.
                await asyncio.sleep(0)
                if self.task:
                    self.task.cancel()
            if self.task:
                await asyncio.gather(self.task, return_exceptions=True)
        return self.store.job(job_id)

    async def _execute(self, job, entry):
        staging = self.base / ".staging" / job.id
        target = self.directory(entry)
        log = None
        value = self.installation(entry.runtime_id, entry.variant)
        try:
            log = RuntimeLog(self.logs / job.log_path, self.root)
            job.state = "running"
            self._save_job(job)
            self._verified.pop(value.id, None)
            if job.operation == "uninstall":
                if target.exists():
                    remove_owned(self.base, target)
                value.state, value.manifest_sha256 = "not_installed", None
            else:
                staging.mkdir(parents=True)
                payload = staging / "payload"
                if entry.archive_format == "venv":
                    await self._install_python(entry, payload, job, log)
                else:
                    await self._install_archives(entry, payload, staging, job, log)
                candidates = list(payload.rglob(entry.executable)) if entry.runtime_id == "llama-server" else [payload / entry.executable]
                if len(candidates) != 1 or not candidates[0].is_file():
                    raise ModelError("RUNTIME_BROKEN", "Runtime entry program was not found.", 503)
                self._stage(job, "verifying", log)
                executable = candidates[0].relative_to(payload).as_posix()
                manifest = {"version": entry.version, "artifact_sha256": entry.sha256, "worker_sha256": entry.worker_sha256, "executable": executable, "files": {}}
                if entry.python_artifact:
                    manifest["python_artifact"] = entry.python_artifact.model_dump()
                if entry.additional_artifacts:
                    manifest["additional_artifact_sha256"] = [artifact.sha256 for artifact in entry.additional_artifacts]
                manifest["files"] = await file_work(lambda cancelled: inventory_hashes(
                    self.base, payload, entry.archive_format == "venv", cancelled))
                marker = payload / "installation.json"
                marker.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
                value.manifest_sha256 = sha256(marker)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    remove_owned(self.base, target)
                payload.replace(target)
                value.version, value.state = entry.version, "installed"
            job.state, job.stage = "completed", "completed"
            value.error_code = None
            log.write("Runtime task completed.")
        except asyncio.CancelledError:
            job.state, job.error_code = "cancelled", "RUNTIME_CANCELLED"
            job.cancel_requested = True
            value.state, value.error_code = "interrupted", job.error_code
            if log:
                log.write("Runtime task cancelled.")
        except Exception as exc:
            job.state = "failed"
            job.error_code = exc.code if isinstance(exc, ModelError) else "RUNTIME_INSTALL_FAILED"
            value.state, value.error_code = "broken", job.error_code
            if log:
                log.write(f"Runtime task failed: {job.error_code} ({type(exc).__name__}).")
        finally:
            try:
                if staging.exists():
                    remove_owned(self.base, staging)
            except OSError:
                job.state, job.error_code = "failed", "RUNTIME_CLEANUP_FAILED"
                value.state, value.error_code = "broken", job.error_code
                if log:
                    log.write("Staging cleanup failed. Retry after closing file handles.")
            job.finished_at = utc_now()
            value.updated_at = utc_now()
            try:
                self.store.save_installation(value)
                self._save_job(job)
                self._emit_installation(value)
            finally:
                self.active_job = None
                self.blocked = None
            self._prune_logs(job.runtime_id)

    async def _install_archives(self, entry, payload, staging, job, log):
        artifacts = [RuntimeArtifact(url=entry.url, sha256=entry.sha256,
                                     archive_format=entry.archive_format, size_bytes=entry.size_bytes), *entry.additional_artifacts]
        total = sum(artifact.size_bytes for artifact in artifacts) if all(artifact.size_bytes is not None for artifact in artifacts) else None
        offset = 0
        for index, artifact in enumerate(artifacts):
            log.write(f"Downloading artifact {index + 1}/{len(artifacts)}.")
            await self._download(artifact, staging / f"download-{index}", job, offset=offset,
                                 total_bytes=total, final=index == len(artifacts) - 1)
            offset = job.progress_current
        self._stage(job, "extracting", log)
        extract_archive(staging / "download-0", payload, entry.archive_format)
        candidates = list(payload.rglob(entry.executable))
        if len(candidates) != 1 or not candidates[0].is_file():
            raise ModelError("RUNTIME_BROKEN", "Runtime entry program was not found.", 503)
        for index, artifact in enumerate(entry.additional_artifacts, 1):
            extra = staging / f"additional-{index}"
            extract_archive(staging / f"download-{index}", extra, artifact.archive_format)
            dll_count = 0
            for source in sorted(extra.rglob("*")):
                if is_link(source.lstat()):
                    raise ModelError("RUNTIME_BROKEN", "Additional runtime files must not be links.", 503)
                if not source.is_file():
                    continue
                if source.suffix.lower() == ".dll":
                    target = candidates[0].parent / source.name
                    dll_count += 1
                else:
                    target = payload / "dependencies" / str(index) / source.relative_to(extra)
                contained(payload, target)
                if target.exists():
                    if not target.is_file() or target.is_symlink() or await file_digest(target) != await file_digest(source):
                        raise ModelError("RUNTIME_BROKEN", "Runtime artifacts contain conflicting files.", 503)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source.replace(target)
            if not dll_count:
                raise ModelError("RUNTIME_BROKEN", "Additional CUDA runtime DLLs are missing.", 503)
        if entry.variant == "cuda":
            from ai_workbench.core.models.runtimes.cuda import llama_environment
            self._stage(job, "checking_program", log)
            await self._command([candidates[0], "--version"], llama_environment(candidates[0].parent), candidates[0].parent, log)

    def _stage(self, job, stage, log):
        job.stage, job.progress_current, job.progress_total = stage, 0, None
        log.write(stage)
        self._save_job(job)

    async def _download(self, entry, target, job, *, offset=0, total_bytes=None, final=True):
        settings = self.store.settings()
        url = entry.url
        if settings.github_release_proxy_url:
            url = settings.github_release_proxy_url + "/" + url
        job.stage = "downloading"
        job.progress_current, job.progress_total = offset, total_bytes
        self._save_job(job)
        digest = hashlib.sha256()
        last_event = time.monotonic()
        async with httpx.AsyncClient(proxy=settings.http_proxy, timeout=60, trust_env=False, transport=self.transport, verify=ssl.create_default_context()) as client:
            # Redirect destinations are checked before requesting them.
            for _ in range(6):
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        next_url = response.url.join(response.headers["location"])
                        if next_url.scheme != "https":
                            raise ModelError("RUNTIME_BROKEN", "Runtime downloads require HTTPS redirects.", 503)
                        url = str(next_url)
                        continue
                    response.raise_for_status()
                    length = response.headers.get("content-length")
                    if total_bytes is None and final:
                        job.progress_total = offset + int(length) if length and length.isdigit() else None
                    with target.open("wb") as output:
                        async for data in response.aiter_bytes():
                            output.write(data)
                            digest.update(data)
                            job.progress_current += len(data)
                            if time.monotonic() - last_event >= 0.25:
                                self._save_job(job)
                                last_event = time.monotonic()
                    break
            else:
                raise ModelError("RUNTIME_INSTALL_FAILED", "Too many runtime download redirects.", 503)
        self._save_job(job)
        if digest.hexdigest() != entry.sha256:
            raise ModelError("RUNTIME_CHECKSUM_MISMATCH", "Runtime download checksum did not match the catalog.", 503)

    async def _command(self, args, env, cwd, log):
        process = await ManagedProcess.start(args, env=env, cwd=cwd, log=log)
        try:
            code = await process.wait()
            if code:
                raise ModelError("RUNTIME_INSTALL_FAILED", "Runtime installation command failed. See the task log.", 503)
        finally:
            await process.stop()

    async def _install_python(self, entry, target, job, log):
        uv = self._uv()
        lock = CATALOG_ROOT / entry.requirements
        if text_digest(lock) != entry.sha256:
            raise ModelError("RUNTIME_BROKEN", "Worker requirements checksum mismatch.", 503)
        auxiliary = None
        if entry.variant == "onnx-cpu":
            auxiliary = self.root / "data/models/_auxiliary/en_core_web_sm/en_core_web_sm-any-py3-none-any.whl"
            if not auxiliary.resolve().is_relative_to((self.root / "data/models/_auxiliary").resolve()) or not auxiliary.is_file():
                raise ModelError("MODEL_NOT_FOUND", "Place en_core_web_sm 3.7.1 in data/models/_auxiliary before installing ONNX CPU.", 404)
            if await file_digest(auxiliary) != "86cc141f63942d4b2c5fcee06630fd6f904788d2f0ab005cce45aadb8fb73889":
                raise ModelError("RUNTIME_CHECKSUM_MISMATCH", "The auxiliary language model checksum does not match.", 503)
        env = {key: value for key, value in os.environ.items() if not key.startswith(("UV_", "PIP_", "PYTHON", "VIRTUAL_ENV")) and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}}
        env.update(UV_PYTHON_INSTALL_DIR=str(self.base / "python"), UV_CACHE_DIR=str(self.base / ".cache"), UV_NO_PROGRESS="1", UV_NATIVE_TLS="true")
        settings = self.store.settings()
        if settings.http_proxy:
            env.update(HTTP_PROXY=settings.http_proxy, HTTPS_PROXY=settings.http_proxy)
        self._stage(job, "creating_environment", log)
        await self._command([uv, "python", "install", entry.python_key, "--no-config", "--no-bin", "--no-registry"], env, self.root, log)
        await self._command([uv, "venv", "--no-config", "--python", entry.python_key, "--python-preference", "only-managed", "--no-python-downloads", str(target)], env, self.root, log)
        self._stage(job, "installing_packages", log)
        build_options = ["--no-binary", "docopt,jaconv,jieba,unidic-lite", "--build-constraints", lock] if auxiliary else []
        if entry.variant == "audio-cuda":
            build_options = ["--no-binary", "antlr4-python3-runtime,sox", "--build-constraints", lock,
                             "--find-links", CATALOG_ROOT / "wheels"]
        torch_index = ["--extra-index-url", settings.pytorch_index_url or entry.pytorch_index_url] if entry.pytorch_index_url else []
        await self._command([uv, "pip", "install", "--no-config", "--python", target / entry.executable, "--require-hashes", "--no-deps", "--only-binary", ":all:", *build_options,
            "--index-url", settings.pypi_index_url or "https://pypi.org/simple", *torch_index,
            "--index-strategy", "unsafe-best-match", "-r", lock], env, self.root, log)
        if auxiliary:
            staged = target / "en_core_web_sm-3.7.1-py3-none-any.whl"
            shutil.copyfile(auxiliary, staged)
            await self._command([uv, "pip", "install", "--no-config", "--python", target / entry.executable, "--no-deps", "--no-index", staged], env, self.root, log)
            staged.unlink()
        worker_source = Path(__file__).resolve().parents[3] / "workers"
        if worker_digest(entry.worker_files, worker_source) != entry.worker_sha256:
            raise ModelError("RUNTIME_BROKEN", "Worker source fingerprint changed during installation.", 503)
        (target / "worker").mkdir()
        for name in entry.worker_files:
            shutil.copyfile(worker_source / name, target / "worker" / name)
        self._stage(job, "checking_packages", log)
        await self._command([uv, "pip", "check", "--no-config", "--python", target / entry.executable], env, self.root, log)
        check = ("import sys, importlib.util; sys.path.insert(0, sys.argv[1]); "
                 "from tts_engine import language_processors, require_offline; require_offline(); language_processors(); "
                 "import onnxruntime, lameenc, tokenizers; "
                 "assert all(importlib.util.find_spec(name) is None for name in ('torch', 'transformers', 'kokoro')); "
                 "print('ONNX worker packages and language resources verified')") if auxiliary else (
                 "import sys; sys.path.insert(0, sys.argv[1]); "
                 "from transformers_engine import require_offline; require_offline(); "
                 "import torch, torchvision, transformers; "
                 "assert torch.__version__ == '2.11.0+cu128' and torch.version.cuda == '12.8'; "
                 "assert torchvision.__version__ == '0.26.0+cu128' and transformers.__version__ == '5.16.1'; "
                 "from transformers.cli.serving.chat_completion import ChatCompletionHandler; "
                 "from transformers.cli.serving.model_manager import ModelManager; "
                 "from transformers.cli.serving.utils import GenerationState; "
                 "print('Transformers serve packages verified; CUDA execution is checked at model load')")
        if entry.variant == "audio-cuda":
            check = ("import sys, importlib.metadata; sys.path.insert(0, sys.argv[1]); "
                     "from audio_engine import require_offline; require_offline(); "
                     "import torch, torchaudio, transformers, numpy, onnxruntime, soundfile, lameenc; "
                     "from chatterbox.tts import ChatterboxTTS; from qwen_tts import Qwen3TTSModel; "
                     "from transformers import WhisperForConditionalGeneration, WhisperProcessor; "
                     "assert torch.__version__ == torchaudio.__version__ == '2.6.0+cu124'; "
                     "assert torch.version.cuda == '12.4' and transformers.__version__ == '4.57.3'; "
                     "assert numpy.__version__ == '1.26.4'; "
                     "assert importlib.metadata.version('chatterbox-tts') == '0.1.7+workbench.1'; "
                     "print('Audio packages verified; CUDA execution is checked at model load')")
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
        await self._command([target / entry.executable, "-I", "-B", "-c", check, target / "worker"], env, self.root, log)

    def log_text(self, job_id):
        job = self.store.job(job_id)
        path = contained(self.logs, self.logs / job.log_path)
        return RuntimeLog(path, self.root).sanitize(path.read_text(encoding="utf-8", errors="replace")) if path.is_file() else ""

    def _prune_logs(self, runtime_id):
        jobs = [job for job in self.store.jobs() if job.runtime_id == runtime_id and job.state in TERMINAL]
        for job in jobs[20:]:
            path = contained(self.logs, self.logs / job.log_path)
            if path.is_file():
                path.unlink()

    async def close(self):
        self.closed = True
        if self.active_job:
            await self.cancel(self.active_job)
