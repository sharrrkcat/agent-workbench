"""Measure the real filter compiler and 40-result batches in isolated processes."""
import argparse
import gc
import json
import platform
from pathlib import Path
import statistics
import subprocess
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_workbench.core.web_filter_rules import FilterSnapshot


CASES = ("domains", "exceptions", "paths", "unprefixed_globs")


def inputs(case, count):
    if case == "paths":
        return "", "\n".join(f"*://same.example/article/{i:06d}/entry/*" for i in range(count))
    if case == "unprefixed_globs":
        return "", "\n".join(f"*://*/*needle{i:06d}*end*" for i in range(count))
    if case == "exceptions":
        blocked = count * 4 // 5
        return ("\n".join(f"@*://*.d{i:06d}.example/*" for i in range(count - blocked)),
                "\n".join(f"*://*.d{i:06d}.example/*" for i in range(blocked)))
    return "", "\n".join(f"*://*.d{i:06d}.example/*" for i in range(count))


def urls(case, count, mode, batch):
    output = []
    for i in range(40):
        hit = mode == "hits" or mode == "mixed" and i % 2 == 0
        index = (batch * 40 + i) % count
        if case == "paths":
            path = f"article/{index:06d}/entry/item" if hit else f"missing/{index:06d}/item"
            output.append(f"https://same.example/{path}?batch={batch}")
        elif case == "unprefixed_globs":
            output.append(f"https://clear{i}.example/absent-{batch}-{i}")
        elif case == "exceptions":
            index = count // 5 + index % (count * 3 // 5) if hit else index % (count // 5)
            output.append(f"https://sub.d{index:06d}.example/item?batch={batch}")
        else:
            host = f"sub.d{index:06d}.example" if hit else f"clear-{batch}-{i}.example"
            output.append(f"https://{host}/item?batch={batch}")
    return output


def measure(case, count, batches):
    custom, subscribed = inputs(case, count)
    started = time.perf_counter()
    snapshot = FilterSnapshot(custom, [subscribed])
    compile_seconds = time.perf_counter() - started
    workloads = {}
    for mode in ("misses",) if case == "unprefixed_globs" else ("hits", "misses", "mixed"):
        samples = []
        iterations = min(batches, 5) if case == "unprefixed_globs" else batches
        for batch in range(iterations):
            values = urls(case, count, mode, batch)
            start = time.perf_counter_ns()
            matched = sum(snapshot.blocked(url) for url in values)
            samples.append((time.perf_counter_ns() - start) / 1e6)
            assert matched == {"hits": 40, "misses": 0, "mixed": 20}[mode]
        samples.sort()
        workloads[mode] = {"batches": iterations, "p50_ms": statistics.median(samples),
                           "p95_ms": samples[max(0, int(len(samples) * .95) - 1)], "max_ms": samples[-1]}
    del snapshot
    gc.collect()
    tracemalloc.start()
    before = FilterSnapshot(custom, [subscribed])
    index_bytes = tracemalloc.get_traced_memory()[0]
    # A live old snapshot can coexist with its fully built replacement.
    after = FilterSnapshot(custom, [subscribed])
    update_peak_bytes = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert before.subscriptions.rule_count == after.subscriptions.rule_count
    return {"case": case, "rules": count, "urls_per_batch": 40, "compile_seconds": compile_seconds,
            "index_mib": index_bytes / 2**20, "update_peak_mib": update_peak_bytes / 2**20,
            "workloads": workloads, "passed": None if case == "unprefixed_globs" else
            compile_seconds <= 5 and index_bytes <= 128 * 2**20 and all(row["p95_ms"] <= 10 for row in workloads.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=int, default=100000)
    parser.add_argument("--batches", type=int, default=1000)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--output", type=Path, default=ROOT / "build/web-filter-implementation/benchmark.json")
    args = parser.parse_args()
    if args.rules < 40 or args.batches < 1:
        parser.error("At least 40 rules and one batch are required")
    if args.case:
        print(json.dumps(measure(args.case, args.rules, args.batches)), flush=True)
        return
    rows = []
    for case in CASES:
        data = subprocess.check_output([sys.executable, str(Path(__file__).resolve()), "--case", case,
            "--rules", str(args.rules), "--batches", str(args.batches)], text=True)
        row = json.loads(data)
        rows.append(row)
        print(json.dumps(row), flush=True)
    report = {"python": platform.python_version(), "platform": platform.platform(), "processes_per_case": 1,
              "limits": {"batch_p95_ms": 10, "compile_seconds": 5, "index_mib": 128}, "cases": rows,
              "limitation": "Globs without discriminating literal prefixes can require scanning every glob in a matching host bucket.",
              "passed": all(row["passed"] is not False for row in rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

