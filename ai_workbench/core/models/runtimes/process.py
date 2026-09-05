from __future__ import annotations

import asyncio
import ctypes
import os
from pathlib import Path
import re
import signal
import subprocess

from ai_workbench.core.models.errors import ModelError

LOG_LIMIT = 10 * 1024 * 1024


class RuntimeLog:
    def __init__(self, path: Path, root: Path, secrets=()):
        self.path = path
        self.root = root
        self.secrets = secrets
        path.parent.mkdir(parents=True, exist_ok=True)

    def sanitize(self, text: str):
        text = text.replace(str(self.root), "<workspace>").replace(self.root.as_posix(), "<workspace>")
        for secret in self.secrets:
            if secret:
                text = text.replace(secret, "<redacted>")
        text = re.sub(r"https?://\S+", "<url>", text)
        text = re.sub(r"(?i)(authorization|api[_-]key|token)\s*[:=]\s*\S+", r"\1=<redacted>", text)
        text = re.sub(r"[A-Za-z]:[\\/][^\s'\"`]+", "<path>", text)
        text = re.sub(r"(?<![\w<])/(?:home|Users|tmp|opt|var)/[^\s'\"`]+", "<path>", text)
        return text

    def write(self, text: str):
        text = self.sanitize(text)
        data = (text.rstrip() + "\n").encode("utf-8", errors="replace")
        size = self.path.stat().st_size if self.path.exists() else 0
        if size < LOG_LIMIT:
            with self.path.open("ab") as stream:
                stream.write(data[:LOG_LIMIT - size])


def _windows_job(pid):
    # Closing this handle kills descendants even if the API process terminates.
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_ = [("per_process", ctypes.c_int64), ("per_job", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                    ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                    ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
    try:
        if not job or not process or not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(job, process):
            if job:
                kernel.CloseHandle(job)
            raise OSError("Cannot assign managed process to a Windows job")
    finally:
        if process:
            kernel.CloseHandle(process)
    return lambda: kernel.CloseHandle(job)


class ManagedProcess:
    def __init__(self, process, log, close_job=None):
        self.process = process
        self.log = log
        self.close_job = close_job
        self.reader = asyncio.create_task(self._read())
        self.stopping = False

    @classmethod
    async def start(cls, args, *, env, cwd, log):
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        try:
            process = await asyncio.create_subprocess_exec(*map(str, args), env=env, cwd=cwd,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, **flags)
        except OSError as exc:
            raise ModelError("RUNTIME_BROKEN", "Cannot start the managed runtime executable.", 503) from exc
        try:
            close_job = _windows_job(process.pid) if os.name == "nt" else None
        except OSError:
            process.kill()
            await process.wait()
            raise ModelError("RUNTIME_BROKEN", "Cannot supervise the runtime process tree.", 503)
        return cls(process, log, close_job)

    async def _read(self):
        pending = b""
        while data := await self.process.stdout.read(4096):
            pending += data
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                self.log.write(line.decode("utf-8", errors="replace"))
            if len(pending) > 16384:
                self.log.write(pending.decode("utf-8", errors="replace"))
                pending = b""
        if pending:
            self.log.write(pending.decode("utf-8", errors="replace"))

    async def wait(self):
        code = await self.process.wait()
        await self.reader
        return code

    async def stop(self):
        self.stopping = True
        if self.close_job:
            self.close_job()
            self.close_job = None
        elif os.name != "nt":
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        elif self.process.returncode is None:
            self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), 5)
        except asyncio.TimeoutError:
            if os.name != "nt":
                os.killpg(self.process.pid, signal.SIGKILL)
            else:
                self.process.kill()
            await self.process.wait()
        await self.reader
