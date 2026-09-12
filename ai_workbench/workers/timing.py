"""Standard-library load timing shared by the host and isolated workers."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import re
import time
from uuid import UUID

TRACE_ENV = "WORKBENCH_LOAD_TRACE"
TRACE_HEADER = "X-Workbench-Load-Trace"
TIMING_PREFIX = "model_timing "
_current: ContextVar[LoadTrace | None] = ContextVar("model_load_trace", default=None)
_FIELDS = {"load_id", "model_profile_id", "runtime_id", "variant", "version", "device", "trigger", "operation"}
_IDENTIFIER = re.compile(r"^[a-zA-Z0-9_.+-]{1,128}$")
_ERROR_CODES = frozenset({
    "INVALID_REQUEST", "MODEL_BUSY", "MODEL_NOT_FOUND", "MODEL_UNAVAILABLE", "MODEL_TIMEOUT",
    "MODEL_KIND_MISMATCH", "UNSUPPORTED_CAPABILITY", "RUNTIME_NOT_INSTALLED", "RUNTIME_INSTALLING",
    "RUNTIME_BROKEN", "RUNTIME_UNSUPPORTED", "RUNTIME_DEVICE_UNAVAILABLE", "REQUEST_CANCELLED",
    "PROVIDER_ERROR", "PROVIDER_PROTOCOL_ERROR", "VOICE_UNAVAILABLE", "INVALID_AUDIO",
    "AUDIO_TOO_LONG", "AUDIO_TOO_LARGE", "REQUEST_TOO_LARGE",
})


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def error_result(error):
    if isinstance(error, asyncio.CancelledError):
        return "cancelled", "REQUEST_CANCELLED"
    code = getattr(error, "code", None)
    if isinstance(error, TimeoutError) or code == "MODEL_TIMEOUT":
        return "timeout", "MODEL_TIMEOUT"
    return "failed", code if isinstance(code, str) and code in _ERROR_CODES else "MODEL_UNAVAILABLE"


class LoadTrace:
    def __init__(self, metadata, write, *, scope="host", total_stage="load_total", clock=None, cpu_clock=None, on_finish=None):
        self.metadata = dict(metadata)
        self.write = write
        self.scope, self.total_stage = scope, total_stage
        self.clock = clock or time.perf_counter
        self.cpu_clock = cpu_clock or time.process_time
        self.started = self.clock()
        self.cpu_started = self.cpu_clock()
        self.finished = False
        self.reused = {}
        self.on_finish = on_finish
        self._emit(total_stage, "started", self.started, self.cpu_started)

    def _emit(self, name, result, started, cpu_started, error_code=None):
        now = self.clock()
        cpu_now = self.cpu_clock()
        event = {"event": "model_load_timing", "timestamp": utc_timestamp(), **self.metadata,
                 "scope": self.scope, "stage": name, "result": result,
                 "duration_ms": round(max(0, now - started) * 1000, 3),
                 "elapsed_ms": round(max(0, now - self.started) * 1000, 3),
                 "cpu_duration_ms": round(max(0, cpu_now - cpu_started) * 1000, 3),
                 "cpu_elapsed_ms": round(max(0, cpu_now - self.cpu_started) * 1000, 3), **self.reused}
        if error_code:
            event["error_code"] = error_code
        try:
            self.write(TIMING_PREFIX + json.dumps(event, ensure_ascii=True, separators=(",", ":")))
        except Exception:
            # Diagnostics must not change inference or cancellation outcomes.
            pass

    def start_stage(self, name):
        return TimedStage(self, name)

    def finish(self, error=None):
        if self.finished:
            return
        self.finished = True
        result, code = error_result(error) if error is not None else ("completed", None)
        self._emit(self.total_stage, result, self.started, self.cpu_started, code)
        if self.on_finish:
            try:
                self.on_finish()
            except Exception:
                pass

    def transport_value(self):
        return json.dumps(self.metadata, ensure_ascii=True, separators=(",", ":"))


class TimedStage:
    def __init__(self, trace, name):
        self.trace, self.name = trace, name
        self.started = trace.clock()
        self.cpu_started = trace.cpu_clock()
        self.finished = False
        trace._emit(name, "started", self.started, self.cpu_started)

    def finish(self, error=None):
        if self.finished:
            return
        self.finished = True
        result, code = error_result(error) if error is not None else ("completed", None)
        self.trace._emit(self.name, result, self.started, self.cpu_started, code)


def current_trace():
    trace = _current.get()
    return trace if trace is not None and not trace.finished else None


@contextmanager
def tracing(trace):
    token = _current.set(trace)
    try:
        yield trace
    except BaseException as error:
        if trace:
            trace.finish(error)
        raise
    else:
        if trace:
            trace.finish()
    finally:
        _current.reset(token)


@contextmanager
def stage(name):
    trace = current_trace()
    span = trace.start_stage(name) if trace else None
    try:
        yield
    except BaseException as error:
        if span:
            span.finish(error)
        raise
    else:
        if span:
            span.finish()


def worker_trace(encoded, total_stage):
    """Ignore invalid diagnostic metadata without changing the private RPC body."""
    if not isinstance(encoded, str) or len(encoded) > 2048:
        return None
    try:
        metadata = json.loads(encoded)
        if not isinstance(metadata, dict) or set(metadata) != _FIELDS:
            return None
        if any(not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) for value in metadata.values()):
            return None
        if str(UUID(metadata["load_id"])) != metadata["load_id"]:
            return None
        if metadata["runtime_id"] != "python-worker" or metadata["trigger"] not in {"explicit", "autoload", "health", "reference"}:
            return None
        if metadata["device"] not in {"cpu", "cuda"}:
            return None
        if metadata["operation"] not in {"load", "health", "reference_prepare"}:
            return None
    except (ValueError, TypeError, AttributeError):
        return None
    return LoadTrace(metadata, lambda line: print(line, flush=True), scope="worker", total_stage=total_stage)
