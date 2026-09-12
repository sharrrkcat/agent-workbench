import asyncio
import builtins
from contextlib import nullcontext
from datetime import datetime
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.cuda import LlamaCudaLog
from ai_workbench.core.models.runtimes.process import RuntimeLog
from ai_workbench.workers import timing, transformers_engine, tts_engine


def metadata(**patch):
    return {"load_id": str(uuid4()), "model_profile_id": str(uuid4()), "runtime_id": "python-worker",
            "variant": "onnx-cpu", "version": "1.0.2", "device": "cpu", "trigger": "explicit",
            "operation": "load", **patch}


def events(text):
    return [json.loads(line.split(timing.TIMING_PREFIX, 1)[1]) for line in text.splitlines() if timing.TIMING_PREFIX in line]


class Clock:
    now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_nested_stage_durations_total_and_early_completion_exclude_inference():
    clock, lines = Clock(), []
    cpu_clock = Clock()
    clock.now, cpu_clock.now = 100, 500
    trace = timing.LoadTrace(metadata(), lines.append, clock=clock, cpu_clock=cpu_clock)
    with timing.tracing(trace):
        with timing.stage("queue_wait"):
            clock.advance(2)
            cpu_clock.advance(0.1)
        with timing.stage("engine_init"):
            with timing.stage("onnx_session"):
                clock.advance(3)
                cpu_clock.advance(4.5)  # CPU time includes work on multiple threads.
            clock.advance(1)
            cpu_clock.advance(0.5)
        trace.finish()
        clock.advance(100)  # A later inference is outside the load attempt.
        cpu_clock.advance(200)
        with timing.stage("unrecorded_inference"):
            pass
    records = events("\n".join(lines))
    completed = {item["stage"]: item for item in records if item["result"] == "completed"}
    assert {name: item["duration_ms"] for name, item in completed.items()} == {
        "queue_wait": 2000, "onnx_session": 3000, "engine_init": 4000, "load_total": 6000}
    assert {name: item["cpu_duration_ms"] for name, item in completed.items()} == {
        "queue_wait": 100, "onnx_session": 4500, "engine_init": 5000, "load_total": 5100}
    assert completed["onnx_session"]["cpu_elapsed_ms"] == 4600
    assert completed["load_total"]["cpu_elapsed_ms"] == 5100
    assert len([item for item in records if item["stage"] == "load_total"]) == 2
    assert records[0]["result"] == "started" and records[-1]["stage"] == "load_total"
    assert all(item["timestamp"].endswith("Z") and datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")) for item in records)


@pytest.mark.parametrize("error,result,code", [
    (ModelError("MODEL_NOT_FOUND", "private model path"), "failed", "MODEL_NOT_FOUND"),
    (ModelError("MODEL_TIMEOUT", "private timeout"), "timeout", "MODEL_TIMEOUT"),
    (TimeoutError("private timeout"), "timeout", "MODEL_TIMEOUT"),
    (asyncio.CancelledError(), "cancelled", "REQUEST_CANCELLED"),
    (ModelError("not-a-safe-error-secret", "private data"), "failed", "MODEL_UNAVAILABLE"),
])
def test_failure_has_one_terminal_and_only_controlled_errors(error, result, code):
    lines = []
    trace = timing.LoadTrace(metadata(), lines.append)
    with pytest.raises(type(error)):
        with timing.tracing(trace):
            with timing.stage("weights"):
                raise error
    trace.finish(error)
    records = events("\n".join(lines))
    assert [item["result"] for item in records] == ["started", "started", result, result]
    assert all(0 <= item["cpu_duration_ms"] <= item["cpu_elapsed_ms"] for item in records)
    assert records[-1]["error_code"] == code
    assert "private" not in "\n".join(lines) and "not-a-safe-error-secret" not in "\n".join(lines)


def test_task_contexts_and_disabled_tracing_do_not_mix():
    async def scenario():
        outputs = []
        async def run():
            lines = []
            trace = timing.LoadTrace(metadata(), lines.append)
            with timing.tracing(trace):
                await asyncio.sleep(0)
                with timing.stage("worker_ready"):
                    assert timing.current_trace() is trace
                with timing.tracing(None):
                    assert timing.current_trace() is None
                outputs.append((trace.metadata["load_id"], lines))
        await asyncio.gather(run(), run())
        assert timing.current_trace() is None
        assert len({identifier for identifier, _ in outputs}) == 2
        for identifier, lines in outputs:
            assert {item["load_id"] for item in events("\n".join(lines))} == {identifier}
    asyncio.run(scenario())


def test_logging_failure_does_not_replace_success_or_original_error(tmp_path):
    def unavailable(_line=None):
        raise PermissionError("Log storage unavailable")
    with timing.tracing(timing.LoadTrace(metadata(), unavailable, on_finish=unavailable)):
        with timing.stage("weights"):
            pass
    with pytest.raises(ModelError, match="original"):
        with timing.tracing(timing.LoadTrace(metadata(), unavailable)):
            raise ModelError("MODEL_UNAVAILABLE", "original")
    parent = tmp_path / "not-a-directory"
    parent.write_text("fixture")
    RuntimeLog(parent / "process.log", tmp_path).write("does not raise")


def test_private_trace_metadata_is_bounded_and_never_echoes_invalid_values(capsys):
    value = metadata()
    trace = timing.worker_trace(json.dumps(value), "worker_load")
    with timing.tracing(trace):
        with timing.stage("worker_ready"):
            pass
    records = events(capsys.readouterr().out)
    assert records and all(item["scope"] == "worker" and item["load_id"] == value["load_id"] for item in records)
    for invalid in (None, "not json", "x" * 2049, [], {**value, "extra": "secret"},
                    {**value, "load_id": "not-a-uuid"}, {**value, "model_profile_id": "C:/private/model"},
                    {**value, "device": "secret device"}, {**value, "operation": "secret operation"}):
        assert timing.worker_trace(invalid if isinstance(invalid, str) or invalid is None else json.dumps(invalid), "worker_load") is None
    assert not capsys.readouterr().out


def test_raw_logs_have_utc_receipt_times_and_cuda_parses_original_records(tmp_path):
    log = LlamaCudaLog(tmp_path / "process.log", tmp_path, ("private-key",))
    log.write("Available devices:\n  CUDA0: First GPU (4096 MiB, 3000 MiB free)")
    log.write("load_tensors: offloaded 3/8 layers to GPU")
    log.write(f"{tmp_path} Authorization: private-key port=12345 http://localhost:12345/v1 127.0.0.1:12345")
    assert log.devices == [("CUDA0", "First GPU")] and log.offload == (3, 8)
    assert log.offload_observed.is_set()
    text = log.path.read_text()
    assert all(line.startswith("[") and "Z] " in line for line in text.splitlines())
    assert all(value not in text for value in (str(tmp_path), "private-key", "12345"))


@pytest.mark.parametrize("resources_valid", [True, False])
def test_kokoro_times_imports_and_checks_resources_before_building_languages(monkeypatch, resources_valid):
    import importlib.metadata
    import sys
    builds, warmups, lines = [], [], []

    def build(language):
        builds.append(language)
        def process(text):
            warmups.append(language)
            return "phonemes", None
        return process

    monkeypatch.setattr(importlib.metadata, "version", lambda _: "3.7.1")
    monkeypatch.setitem(sys.modules, "spacy", SimpleNamespace(util=SimpleNamespace(is_package=lambda _: resources_valid)))
    en = SimpleNamespace(G2P=lambda **kw: build("en-GB" if kw["british"] else "en-US"))
    espeak = SimpleNamespace(EspeakFallback=lambda **_: object(), EspeakG2P=lambda language: build(language))
    zh = SimpleNamespace(ZHG2P=lambda **_: build("zh-CN"))
    monkeypatch.setitem(sys.modules, "misaki", SimpleNamespace(en=en, espeak=espeak, zh=zh))
    monkeypatch.setitem(sys.modules, "misaki.cutlet", SimpleNamespace(Cutlet=lambda: build("ja-JP")))
    monkeypatch.setitem(sys.modules, "jieba", SimpleNamespace(setLogLevel=lambda _: None))
    with nullcontext() if resources_valid else pytest.raises(tts_engine.WorkerError):
        with timing.tracing(timing.LoadTrace(metadata(), lines.append, scope="worker", total_stage="worker_load")):
            processors = tts_engine.language_processors()
    records = events("\n".join(lines))
    imports = [f"language_imports.{name}" for name in
               ("importlib_metadata", "spacy", "misaki.en", "misaki.espeak", "misaki.zh", "misaki.cutlet", "jieba")]
    assert [item["stage"] for item in records if item["stage"] in imports and item["result"] == "completed"] == imports
    assert all(0 <= item["cpu_duration_ms"] <= item["cpu_elapsed_ms"] for item in records)
    if not resources_valid:
        assert not builds and not warmups
        assert [(item["stage"], item["error_code"]) for item in records if item["result"] == "failed"] == [
            ("language_resources", "RUNTIME_BROKEN"), ("worker_load", "RUNTIME_BROKEN")]
        return
    assert list(processors) == ["a", "b", "j", "z", "e", "f", "h", "i", "p"]
    assert builds == warmups == ["en-US", "en-GB", "ja-JP", "zh-CN", "es", "fr-fr", "hi", "it", "pt-br"]
    completed = [item["stage"] for item in records if item["result"] == "completed"]
    assert completed == [*imports, "language_imports", "language_resources",
                         *[f"language.{language}.build" for language in tts_engine.LANGUAGES.values()],
                         *[f"language.{language}.warmup" for language in tts_engine.LANGUAGES.values()], "worker_load"]


@pytest.mark.parametrize("failed_import", [None, "torch", "transformers.AutoProcessor", "transformers.serving.chat_completion"])
def test_transformers_import_timings_attribute_failures_before_model_loading(monkeypatch, failed_import):
    wall, cpu, lines, imported = Clock(), Clock(), [], []
    names = ["torch", "transformers.AutoConfig", "transformers.AutoModelForCausalLM",
             "transformers.AutoModelForMultimodalLM", "transformers.AutoProcessor",
             "transformers.serving.chat_completion", "transformers.serving.model_manager",
             "transformers.serving.utils", "transformers.modeling_auto", "transformers.logging"]
    original_import = builtins.__import__

    class DeviceReached(Exception):
        pass

    def device(_threads):
        raise DeviceReached()

    def traced_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch":
            label = "torch"
            value = SimpleNamespace(set_num_threads=device)
        elif name == "transformers" or name.startswith("transformers."):
            label = "transformers." + fromlist[0] if name == "transformers" else name.replace(".cli.", ".")
            label = {"transformers.models.auto.modeling_auto": "transformers.modeling_auto",
                     "transformers.utils": "transformers.logging"}.get(label, label)
            value = SimpleNamespace(**{symbol: object() for symbol in fromlist})
            if label == "transformers.logging":
                value.logging = SimpleNamespace(disable_progress_bar=lambda: None)
        else:
            return original_import(name, globals, locals, fromlist, level)
        record = events("\n".join(lines))[-1]
        assert (record["stage"], record["result"]) == ("engine_imports." + label, "started")
        imported.append(label)
        wall.advance(2)
        cpu.advance(0.25)
        if label == failed_import:
            raise ImportError("private dependency details")
        return value

    monkeypatch.setattr(transformers_engine, "require_offline", lambda: None)
    monkeypatch.setattr(builtins, "__import__", traced_import)
    with pytest.raises(ImportError if failed_import else DeviceReached):
        with timing.tracing(timing.LoadTrace(metadata(variant="transformers-cuda"), lines.append,
                                            scope="worker", total_stage="worker_startup", clock=wall, cpu_clock=cpu)):
            transformers_engine.TransformersEngine("unused", {"device": "cpu", "intraop_threads": 4})
    count = names.index(failed_import) + 1 if failed_import else len(names)
    assert imported == names[:count]
    records = events("\n".join(lines))
    imports = [item for item in records if item["stage"].startswith("engine_imports.") and item["result"] != "started"]
    assert len(imports) == count
    assert all(item["duration_ms"] == 2000 and item["cpu_duration_ms"] == 250 for item in imports)
    assert records[-1]["duration_ms"] == count * 2000 and records[-1]["cpu_duration_ms"] == count * 250
    failed = [item["stage"] for item in records if item["result"] == "failed"]
    assert failed == (["engine_imports." + failed_import, "engine_imports", "worker_startup"] if failed_import
                      else ["device_init", "worker_startup"])
    assert "private dependency details" not in "\n".join(lines)
    assert not any(item["stage"] in {"processor", "weights"} for item in records)
