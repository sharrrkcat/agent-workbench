from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


PORTABLE_NAME = "agent-workbench-portable"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a minimal portable Agent Workbench folder.")
    parser.add_argument("--zip", action="store_true", help="Also create dist/agent-workbench-portable.zip")
    return parser.parse_args()


def run_frontend_build(root: Path) -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm was not found. Install Node.js, then run this script again.")
    subprocess.run([npm, "run", "build"], cwd=root / "frontend", check=True)


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "node_modules",
            ".env",
            "*.sqlite",
            "*.db",
            "attachments",
            "logs",
        ),
    )


def copy_required_files(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for filename in ["pyproject.toml", "uv.lock", "README.md"]:
        source = root / filename
        if source.is_file():
            shutil.copy2(source, output / filename)

    for dirname in ["ai_workbench", "agents", "capabilities"]:
        copy_tree(root / dirname, output / dirname)

    scripts_dir = output / "scripts"
    scripts_dir.mkdir()
    for filename in ["run_app.py", "check_agents.py"]:
        shutil.copy2(root / "scripts" / filename, scripts_dir / filename)

    frontend_dist = root / "frontend" / "dist"
    copy_tree(frontend_dist, output / "frontend" / "dist")

    data_dir = output / "data"
    data_dir.mkdir()
    (data_dir / ".gitkeep").write_text("", encoding="utf-8")


def write_start_scripts(output: Path) -> None:
    (output / "start.bat").write_text(
        """@echo off
setlocal
cd /d "%~dp0"
uv run python scripts\\run_app.py --open
if errorlevel 1 pause
""",
        encoding="utf-8",
        newline="\r\n",
    )
    (output / "start.sh").write_text(
        """#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
uv run python scripts/run_app.py --open
""",
        encoding="utf-8",
        newline="\n",
    )


def write_readme(output: Path) -> None:
    (output / "README_RUN.md").write_text(
        """# Agent Workbench Portable Run Guide

## Windows

Double-click `start.bat`, or run:

```bat
start.bat
```

## Linux/macOS

```bash
chmod +x start.sh
./start.sh
```

## Requirements

- Python and uv are required.
- Node.js is only required when building `frontend/dist` yourself.
- If this portable folder already contains `frontend/dist`, normal startup does not need `npm run dev`.
- LM Studio, Ollama, or llama.cpp are not bundled. Start your chosen local LLM service separately.

Default address:

```text
http://127.0.0.1:8765
```

If the port is in use:

```bash
uv run python scripts/run_app.py --port 8766 --open
```

This portable package does not include `.env`, databases, attachments, API keys, `node_modules`, or cache folders.
Current data is still stored in the project `data` directory. A future release may move data to an OS user data directory.
""",
        encoding="utf-8",
    )


def create_zip(output: Path) -> Path:
    zip_base = output.parent / PORTABLE_NAME
    zip_path = Path(shutil.make_archive(str(zip_base), "zip", root_dir=output.parent, base_dir=output.name))
    return zip_path


def main() -> None:
    args = parse_args()
    root = project_root()
    dist_dir = root / "dist"
    output = dist_dir / PORTABLE_NAME

    run_frontend_build(root)

    if output.exists():
        shutil.rmtree(output)
    copy_required_files(root, output)
    write_start_scripts(output)
    write_readme(output)

    print(f"Portable package created: {output}")
    if args.zip:
        print(f"Portable zip created: {create_zip(output)}")


if __name__ == "__main__":
    main()
