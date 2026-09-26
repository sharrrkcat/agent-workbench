from __future__ import annotations

import asyncio
import hashlib
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
from ai_workbench.core.models.runtimes.catalog import CATALOG_ROOT, WORKER_ROOT, catalog, requirements_digest, worker_entrypoint
from ai_workbench.core.models.runtimes.process import ManagedProcess, RuntimeLog
from ai_workbench.core.models.runtimes.schema import (
    CacheCleanupResult, ComponentInstallation, ComponentManifest, Installation, InstallationManifest, RuntimeArtifact, RuntimeJob, StorageUsage, TERMINAL,
)
from ai_workbench.core.models.runtimes.components import BUNDLED_ROOT, bootstrap_processor, bundled_release, require_component
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


def installed_file(target: Path, name: str) -> Path:
    from ai_workbench.core.models.runtimes.schema import relative_ref
    relative_ref(name)
    path = target / name
    resolved = path.resolve()
    if resolved.is_relative_to(target.resolve()):
        return path
    raise ModelError("RUNTIME_BROKEN", "Installed file escapes its runtime directory.", 503)


async def file_work(work):
    cancelled = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(work, cancelled))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        await asyncio.gather(task, return_exceptions=True)
        raise


def extract_archive(archive: Path, target: Path, archive_format: str, *, strip_prefix: str | None = None):
    target.mkdir(parents=True, exist_ok=True)

    def destination(name):
        if "\\" in name or ":" in name or ".." in Path(name).parts or Path(name).is_absolute():
            raise ModelError("RUNTIME_BROKEN", "Unsafe archive member.", 503)
        if strip_prefix is not None:
            parts = Path(name).parts
            if not parts or parts[0] != strip_prefix:
                raise ModelError("RUNTIME_BROKEN", "Unexpected archive root.", 503)
            name = Path(*parts[1:])
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
    def __init__(self, root, store, settings, events=None, release=None, transport=None):
        self.root = Path(root).resolve()
        self.base = self.root / "data" / "runtimes"
        self.logs = self.root / "data" / "logs" / "runtimes"
        self.store = store
        self.events = events
        self.settings = settings
        self.release = release if release is not None else catalog()
        self.worker_root = WORKER_ROOT
        self._installation_snapshot: Installation | None = None
        self.component_release = bundled_release()
        self._component_snapshot = None
        self.transport = transport
        self.task: asyncio.Task | None = None
        self.active_job: str | None = None
        self.blocked = False
        self.closed = False
        self.manager = None
        self.store.interrupt_unfinished()
        for job in self.store.jobs():
            if job.state == "interrupted":
                staging = self.base / ".staging" / job.id
                if staging.exists():
                    remove_owned(self.base, staging)
        self.installation()
        self.component()

    def component_directory(self, version=None):
        version = version or self.component().version
        root = contained(self.base, self.base / "local" / "components" / "dlss5nr")
        return contained(root, root / version)

    def component(self, *, check=True):
        if not check:
            return self._component_snapshot.model_copy(deep=True)
        release = self.component_release.manifest
        records = self.store.components()
        value = records[0] if records else ComponentInstallation(version=release.version)
        if not self.release.supported:
            value.state, value.error_code = "unsupported", "RUNTIME_COMPONENT_INCOMPATIBLE"
        elif value.state == "installed":
            try:
                target = self.component_directory(value.version)
                contents = installed_file(target, "installation.json").read_bytes()
                manifest = ComponentManifest.model_validate_json(contents, strict=True)
                if hashlib.sha256(contents).hexdigest() != value.manifest_sha256:
                    raise ValueError("Component metadata changed")
                if manifest.version != value.version or manifest.python_version != self.release.python_version:
                    value.state, value.error_code = "unsupported", "RUNTIME_COMPONENT_INCOMPATIBLE"
                elif not all(installed_file(target, entry).is_file() for entry in manifest.entries.model_dump().values()):
                    raise ValueError("Component entry point missing")
            except (OSError, ValueError, ModelError):
                value.state, value.error_code = "broken", "RUNTIME_COMPONENT_BROKEN"
        self._component_snapshot = value.model_copy(deep=True)
        return value

    def component_entries(self):
        value = self.component()
        require_component(value)
        target = self.component_directory(value.version)
        manifest = ComponentManifest.model_validate_json((target / "installation.json").read_bytes())
        return {key: installed_file(target, name) for key, name in manifest.entries.model_dump().items()}

    def directory(self, version=None):
        if version is None:
            value = self._installation_snapshot
            version = value.version if value and value.state != "not_installed" else self.release.version
        local = contained(self.base, self.base / "local")
        return contained(local, local / version)

    def worker_entrypoint(self, engine):
        if engine == "dlss5nr":
            return self.component_entries()["worker"]
        path = self.worker_root / worker_entrypoint(engine)
        if not path.is_file():
            raise ModelError("MODEL_UNAVAILABLE", "The application worker entry point is missing.", 503)
        return path

    def _entry_paths(self, target, manifest):
        if manifest.dependencies != self.release.dependency_identity():
            raise ValueError("Runtime dependencies changed")
        paths = {key: installed_file(target, name) for key, name in manifest.executables.model_dump().items()}
        if not all(path.is_file() for path in paths.values()):
            raise ValueError("An installed entry point is missing")
        return paths

    def _inspect_installation(self, check=True):
        if not check:
            return self._installation_snapshot.model_copy(deep=True), None
        entry = self.release
        records = self.store.installations()
        value = records[0] if records else Installation(version=entry.version)
        paths = None
        if not entry.supported:
            value.state, value.error_code = "unsupported", "RUNTIME_UNSUPPORTED"
        elif value.state == "installed":
            try:
                target = self.directory(value.version)
                contents = installed_file(target, "installation.json").read_bytes()
                if hashlib.sha256(contents).hexdigest() != value.manifest_sha256:
                    raise ValueError("Installation metadata digest changed")
                paths = self._entry_paths(target, InstallationManifest.model_validate_json(contents, strict=True))
            except (OSError, ValueError, ModelError):
                value.state, value.error_code = "broken", "RUNTIME_BROKEN"
        previous = self._installation_snapshot
        self._installation_snapshot = value.model_copy(deep=True)
        if previous and previous.model_dump(exclude={"updated_at"}) != value.model_dump(exclude={"updated_at"}):
            self._emit_installation(value)
        return value, paths

    def installation(self, *, check=True):
        return self._inspect_installation(check)[0]

    @staticmethod
    def _require_available(value):
        codes = {"not_installed": "RUNTIME_NOT_INSTALLED", "installing": "RUNTIME_INSTALLING",
                 "broken": "RUNTIME_BROKEN", "unsupported": "RUNTIME_UNSUPPORTED", "interrupted": "RUNTIME_BROKEN"}
        if value.state != "installed":
            raise ModelError(codes[value.state], "Install or repair the local runtime in Models settings.", 503,
                {"source_type": "local", "action": "repair" if value.state in {"broken", "interrupted"}
                 else "install" if value.state == "not_installed" else "view_runtime"})

    def assert_available(self, *, check=True):
        self._require_available(self.installation(check=check))
        return self.release

    def executable(self, engine, device="cpu"):
        """Check fixed installation metadata and entry points before starting a process."""
        value, paths = self._inspect_installation()
        self._require_available(value)
        if engine == "dlss5nr":
            require_component(self.component())
        return paths[device if engine == "llama-server" else "python"]

    def _emit_installation(self, value):
        component = isinstance(value, ComponentInstallation)
        if component:
            self._component_snapshot = value.model_copy(deep=True)
        else:
            self._installation_snapshot = value.model_copy(deep=True)
        if self.events:
            payload = value.model_dump(mode="json", exclude={"manifest_sha256"})
            if component:
                payload["bundled_version"] = self.component_release.manifest.version
            self.events.emit("runtime_status", session_id="", payload={"component" if component else "installation": payload})
        if self.manager:
            self.manager.runtime_changed()

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
            self._prune_logs(cache=True)

    async def submit(self, operation, component_id=None):
        if self.closed:
            raise ModelError("MODEL_UNAVAILABLE", "Runtime supervisor is shutting down.", 503)
        if self.active_job is not None:
            raise ModelError("RUNTIME_INSTALLING", "Another runtime task is in progress.", 409)
        entry = self.release
        if not entry.supported:
            raise ModelError("RUNTIME_UNSUPPORTED", "The local runtime is not supported on this platform.", 422)
        if self.manager:
            self.manager.require_local_idle()
        if component_id:
            if operation != "uninstall":
                self.assert_available()
            value = self.component()
            entry = self.component_release.manifest
        else:
            value = self.installation()
        if operation == "install" and value.state != "not_installed":
            (require_component if component_id else self._require_available)(value)
        already_installed = operation == "install" and value.state == "installed" and (not component_id or value.version == entry.version)
        version = value.version if operation == "uninstall" or already_installed else entry.version
        job = RuntimeJob(version=version, operation=operation, component_id=component_id)
        job.log_path = f"{job.id}.log"
        self.active_job = job.id
        self.blocked = True
        try:
            if already_installed:
                if component_id:
                    bootstrap_processor(self.root, self.manager.profiles, value)
                    self.store.save_component(value)
                    self._emit_installation(value)
                job.state, job.stage, job.finished_at = "completed", "already_installed", utc_now()
                self._save_job(job)
                self.active_job = None
                self.blocked = False
                return job
            if self.manager:
                await self.manager.invalidate_local()
            value.state, value.job_id, value.error_code = "installing", job.id, None
            (self.store.save_component if component_id else self.store.save_installation)(value)
            self._save_job(job)
            self._emit_installation(value)
            self.task = asyncio.create_task(self._execute(job, entry))
            return job
        except BaseException:
            self.active_job = None
            self.blocked = False
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
        log = None
        value = self.component() if job.component_id else self.installation()
        try:
            log = RuntimeLog(self.logs / job.log_path, self.root)
            job.state = "running"
            self._save_job(job)
            target = self.component_directory(job.version) if job.component_id else self.directory(job.version)
            if job.operation == "uninstall":
                if target.exists():
                    await file_work(lambda _: remove_owned(self.base, target))
                value.state, value.manifest_sha256 = "not_installed", None
                if not job.component_id:
                    for component in self.store.components():
                        directory = self.component_directory(component.version)
                        if directory.exists():
                            await file_work(lambda _: remove_owned(self.base, directory))
                        component.state, component.manifest_sha256 = "not_installed", None
                        self.store.save_component(component)
                        self._emit_installation(component)
            else:
                staging.mkdir(parents=True)
                payload = staging / "payload"
                if job.component_id:
                    manifest = await self._install_component(payload, job, log)
                else:
                    await self._install_python(entry, payload, job, log)
                    executables = {"python": entry.python_executable}
                    for device, native in (("cpu", entry.native_cpu), ("cuda", entry.native_cuda)):
                        executables[device] = await self._install_native(native, payload, staging, device, job, log)
                    manifest = InstallationManifest(dependencies=entry.dependency_identity(), executables=executables)
                    self._entry_paths(payload, manifest)
                self._stage(job, "finalizing", log)
                marker = payload / "installation.json"
                marker.write_text(manifest.model_dump_json(), encoding="utf-8")
                value.manifest_sha256 = sha256(marker)
                target.parent.mkdir(parents=True, exist_ok=True)
                previous = self.component_directory(value.version) if job.component_id else self.directory(value.version)
                if previous != target and previous.exists():
                    await file_work(lambda _: remove_owned(self.base, previous))
                if target.exists():
                    await file_work(lambda _: remove_owned(self.base, target))
                payload.replace(target)
                value.version, value.state = entry.version, "installed"
                if job.component_id:
                    bootstrap_processor(self.root, self.manager.profiles, value)
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
                    await file_work(lambda _: remove_owned(self.base, staging))
            except OSError:
                job.state, job.error_code = "failed", "RUNTIME_CLEANUP_FAILED"
                value.state, value.error_code = "broken", job.error_code
                if log:
                    log.write("Staging cleanup failed. Retry after closing file handles.")
            job.finished_at = utc_now()
            value.updated_at = utc_now()
            try:
                (self.store.save_component if job.component_id else self.store.save_installation)(value)
                self._save_job(job)
                self._emit_installation(value)
            finally:
                self.active_job = None
                self.blocked = False
            self._prune_logs(cache=job.version is None)

    async def _install_component(self, payload, job, log):
        release = self.component_release
        if release.manifest.python_version != self.release.python_version:
            raise ModelError("RUNTIME_COMPONENT_INCOMPATIBLE", "The bundled component requires a different base Python version.", 503)
        self._stage(job, "checking_component_archive", log)
        archive = installed_file(BUNDLED_ROOT, release.archive)
        if await file_digest(archive) != release.archive_sha256:
            raise ModelError("RUNTIME_CHECKSUM_MISMATCH", "Bundled component checksum mismatch.", 503)
        self._stage(job, "extracting_component", log)
        await file_work(lambda _: extract_archive(archive, payload, "zip"))
        manifest = ComponentManifest.model_validate_json((payload / "installation.json").read_bytes())
        if manifest != release.manifest:
            raise ModelError("RUNTIME_COMPONENT_INCOMPATIBLE", "Bundled component metadata mismatch.", 503)
        entries = {key: installed_file(payload, name) for key, name in manifest.entries.model_dump().items()}
        if not all(path.is_file() for path in entries.values()):
            raise ModelError("RUNTIME_COMPONENT_BROKEN", "Component entry point missing.", 503)
        self._stage(job, "checking_component", log)
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith(("PYTHON", "VIRTUAL_ENV"))}
        await self._command([self.executable("component-check"), "-I", "-B", entries["worker"], "--self-check", entries["bridge"], entries["caller"]], env, payload, log)
        return manifest

    async def _install_native(self, native, payload, staging, device, job, log):
        artifacts = [native.artifact, *native.dependencies]
        target_root = payload / "native" / device
        total = sum(artifact.size_bytes for artifact in artifacts) if all(artifact.size_bytes is not None for artifact in artifacts) else None
        offset = 0
        archives = []
        self._stage(job, "native_" + device, log)
        for index, artifact in enumerate(artifacts):
            archive = contained(self.base, self.base / ".cache" / "cogita-artifacts" / artifact.sha256)
            if not archive.is_file() or await file_digest(archive) != artifact.sha256:
                staged_archive = staging / f"{device}-{index}"
                await self._download(artifact, staged_archive, job, offset=offset,
                                     total_bytes=total, final=index == len(artifacts) - 1)
                archive.parent.mkdir(parents=True, exist_ok=True)
                staged_archive.replace(archive)
            else:
                log.write("Using a checksum-verified native archive from cache.")
                job.progress_current, job.progress_total = offset + archive.stat().st_size, total
                self._save_job(job)
            archives.append(archive)
            offset = job.progress_current
        await file_work(lambda _: extract_archive(archives[0], target_root, native.artifact.archive_format))
        candidates = list(target_root.rglob(native.executable))
        if len(candidates) != 1 or not candidates[0].is_file():
            raise ModelError("RUNTIME_BROKEN", "Native runtime entry program was not found.", 503)
        for index, artifact in enumerate(native.dependencies, 1):
            extra = staging / f"{device}-dependency-{index}"
            await file_work(lambda _: extract_archive(archives[index], extra, artifact.archive_format))
            dll_count = 0
            for source in sorted(extra.rglob("*")):
                if is_link(source.lstat()):
                    raise ModelError("RUNTIME_BROKEN", "Additional runtime files must not be links.", 503)
                if not source.is_file():
                    continue
                if source.suffix.lower() == ".dll":
                    destination = candidates[0].parent / source.name
                    dll_count += 1
                else:
                    destination = target_root / "dependencies" / str(index) / source.relative_to(extra)
                contained(target_root, destination)
                if destination.exists():
                    if not destination.is_file() or destination.is_symlink() or await file_digest(destination) != await file_digest(source):
                        raise ModelError("RUNTIME_BROKEN", "Runtime artifacts contain conflicting files.", 503)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source.replace(destination)
            if not dll_count:
                raise ModelError("RUNTIME_BROKEN", "Additional CUDA runtime DLLs are missing.", 503)
        from ai_workbench.core.models.runtimes.cuda import llama_environment
        self._stage(job, "checking_program", log)
        await self._command([candidates[0], "--version"], llama_environment(candidates[0].parent), candidates[0].parent, log)
        return candidates[0].relative_to(payload).as_posix()

    def _stage(self, job, stage, log):
        job.stage, job.progress_current, job.progress_total = stage, 0, None
        log.write(stage)
        self._save_job(job)

    async def _download(self, entry, target, job, *, offset=0, total_bytes=None, final=True):
        settings = self.settings.get().download
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
        if requirements_digest(lock) != entry.requirements_sha256:
            raise ModelError("RUNTIME_BROKEN", "Runtime requirements changed during installation.", 503)
        env = {key: value for key, value in os.environ.items() if not key.startswith(("UV_", "PIP_", "PYTHON", "VIRTUAL_ENV")) and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}}
        env.update(UV_CACHE_DIR=str(self.base / ".cache"), UV_NO_PROGRESS="1", UV_NATIVE_TLS="true", UV_PYTHON_DOWNLOADS="never")
        settings = self.settings.get().download
        if settings.http_proxy:
            env.update(HTTP_PROXY=settings.http_proxy, HTTPS_PROXY=settings.http_proxy)
        self._stage(job, "creating_environment", log)
        artifact = entry.python_artifact
        archive = contained(self.base, self.base / "python" / "archives" / (artifact.sha256 + ".tar.gz"))
        if not archive.is_file() or await file_digest(archive) != artifact.sha256:
            staged_archive = target.parent / "python.tar.gz"
            await self._download(artifact, staged_archive, job)
            archive.parent.mkdir(parents=True, exist_ok=True)
            staged_archive.replace(archive)
        target.mkdir(parents=True)
        await file_work(lambda _: extract_archive(archive, target / "env", artifact.archive_format, strip_prefix="python"))
        await self._command([target / entry.python_executable, "-I", "-B", "-c",
            f"import platform; assert platform.python_version() == {entry.python_version!r}"], env, self.root, log)
        self._stage(job, "installing_packages", log)
        await self._command([uv, "pip", "sync", "--no-config", "--python", target / entry.python_executable,
            "--require-hashes", "--only-binary", ":all:", "--no-binary", "docopt,jieba,unidic-lite,antlr4-python3-runtime,sox",
            "--build-constraints", lock, "--find-links", CATALOG_ROOT / "wheels",
            "--index-url", settings.pypi_index_url or "https://pypi.org/simple",
            "--extra-index-url", settings.pytorch_index_url or entry.pytorch_index_url,
            "--index-strategy", "unsafe-best-match", lock], env, self.root, log)
        self._stage(job, "checking_packages", log)
        await self._command([uv, "pip", "check", "--no-config", "--python", target / entry.python_executable], env, self.root, log)
        python = target / entry.python_executable
        await self._command([python, "-I", "-B", "-X", "utf8", self.worker_root / "patch_transformers.py"],
            env, self.root, log)
        site_packages = python.parent / "Lib" / "site-packages"
        await self._command([python, "-I", "-B", "-X", "utf8", "-m", "compileall", "-q", "-j", "4", "-o", "0",
            "--invalidation-mode", "timestamp", "-e", site_packages, site_packages], env, self.root, log)
        checks = [
            "from embedding_engine import require_offline; require_offline(); import sentence_transformers; from sentence_transformers import SentenceTransformer, CrossEncoder; assert sentence_transformers.__version__ == '6.1.0'",
            "from tts_engine import require_offline; require_offline(); import onnxruntime, spacy, thinc, lameenc, tokenizers; from misaki import en, espeak, zh; from misaki.cutlet import Cutlet",
            "from transformers_engine import require_offline; require_offline(); import torch, torchvision, transformers; from transformers.cli.serving.chat_completion import ChatCompletionHandler; from transformers.cli.serving.model_manager import ModelManager; from transformers.cli.serving.utils import GenerationState; assert torch.__version__ == '2.11.0+cu128' and torch.version.cuda == '12.8'; assert torchvision.__version__ == '0.26.0+cu128' and transformers.__version__ == '5.16.1'",
            "from audio_engine import require_offline; require_offline(); import torch, torchaudio, numpy; from chatterbox.tts import ChatterboxTTS; assert torch.__version__ == torchaudio.__version__ == '2.11.0+cu128' and numpy.__version__ == '1.26.4'",
            "from audio_engine import require_offline; require_offline(); from qwen_tts import Qwen3TTSModel",
            "from asr_engine import require_offline; require_offline(); from transformers import WhisperForConditionalGeneration, WhisperProcessor",
        ]
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
        for check in checks:
            script = "import sys; sys.path.insert(0, sys.argv[1]); " + check
            await self._command([target / entry.python_executable, "-I", "-B", "-c", script, self.worker_root], env, self.root, log)

    def log_text(self, job_id):
        job = self.store.job(job_id)
        path = contained(self.logs, self.logs / job.log_path)
        return RuntimeLog(path, self.root).sanitize(path.read_text(encoding="utf-8", errors="replace")) if path.is_file() else ""

    def _prune_logs(self, *, cache):
        jobs = [job for job in self.store.jobs() if (job.version is None) == cache and job.state in TERMINAL]
        for job in jobs[20:]:
            path = contained(self.logs, self.logs / job.log_path)
            if path.is_file():
                path.unlink()

    async def close(self):
        self.closed = True
        if self.active_job:
            await self.cancel(self.active_job)
