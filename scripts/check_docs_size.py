"""Check soft line limits for key documentation files.

Run from the repository root:

    python scripts/check_docs_size.py
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CheckResult:
    path: str
    lines: int | None
    limit: int | None
    status: str


FIXED_LIMITS = {
    "docs/AI_CONTEXT.md": 150,
    "README.md": 350,
    "docs/EXTENSION_API.md": 350,
    "docs/EXTENSION_ARCHITECTURE.md": 350,
    "docs/RUNTIME_PROTOCOLS.md": 300,
}

TASK_LIMIT = 120


def count_lines(path: Path) -> int:
    data = path.read_bytes()
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def check_limited_file(relative_path: str, limit: int) -> CheckResult:
    path = ROOT / relative_path
    if not path.exists():
        return CheckResult(relative_path, None, limit, "missing")
    lines = count_lines(path)
    return CheckResult(relative_path, lines, limit, "ok" if lines <= limit else "over")


def collect_results() -> list[CheckResult]:
    results: list[CheckResult] = [
        check_limited_file(path, limit) for path, limit in FIXED_LIMITS.items()
    ]

    task_dir = ROOT / "docs" / "ai"
    task_files = sorted(task_dir.glob("TASK_*.md")) if task_dir.exists() else []
    if not task_dir.exists():
        results.append(CheckResult("docs/ai/TASK_*.md", None, TASK_LIMIT, "missing"))
    elif not task_files:
        results.append(CheckResult("docs/ai/TASK_*.md", None, TASK_LIMIT, "missing"))
    else:
        for path in task_files:
            relative_path = path.relative_to(ROOT).as_posix()
            results.append(check_limited_file(relative_path, TASK_LIMIT))

    contracts_dir = ROOT / "docs" / "contracts"
    if contracts_dir.exists():
        for path in sorted(contracts_dir.glob("*.md")):
            relative_path = path.relative_to(ROOT).as_posix()
            results.append(CheckResult(relative_path, count_lines(path), None, "info"))

    return results


def print_text(results: list[CheckResult]) -> None:
    for result in results:
        if result.limit is None:
            print(f"{result.path}: {result.lines} lines (info)")
            continue
        if result.lines is None:
            print(f"{result.path}: missing (limit {result.limit})")
            continue
        print(
            f"{result.path}: {result.lines}/{result.limit} lines "
            f"[{result.status}]"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    args = parser.parse_args()

    results = collect_results()
    failed = any(result.status in {"missing", "over"} for result in results)

    if args.json:
        print(json.dumps([result.__dict__ for result in results], indent=2))
    else:
        print_text(results)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
