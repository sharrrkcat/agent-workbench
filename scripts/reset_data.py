import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "sqlite:///./data/agent_workbench.db"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset the local Agent Workbench SQLite database.")
    parser.add_argument("--yes", action="store_true", help="Actually delete the database file.")
    parser.add_argument("--database-url", default=os.getenv("AGENT_WORKBENCH_DATABASE_URL") or DEFAULT_URL)
    args = parser.parse_args()

    database_url = args.database_url
    print(f"Database URL: {database_url}")
    path = sqlite_file_path(database_url)
    if path is None:
        print("Refusing to reset a non-file SQLite database URL.")
        return 1

    print(f"Database file: {path}")
    if not is_safe_path(path):
        print("Refusing to delete a path outside the project data directory or current working tree.")
        return 1

    if not args.yes:
        print("Dry run only. Re-run with --yes to delete this database file.")
        return 0

    if path.exists():
        path.unlink()
        print("Deleted database file.")
    else:
        print("Database file did not exist.")
    return 0


def sqlite_file_path(database_url: str):
    if database_url == "sqlite:///:memory:":
        return None
    if not database_url.startswith("sqlite:///"):
        return None
    raw_path = database_url.replace("sqlite:///", "", 1)
    path = Path(raw_path)
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def is_safe_path(path: Path) -> bool:
    resolved = path.resolve()
    allowed_roots = [(ROOT / "data").resolve(), ROOT.resolve(), Path(tempfile.gettempdir()).resolve()]
    if resolved.suffix not in {".db", ".sqlite", ".sqlite3"}:
        return False
    return any(resolved == root or root in resolved.parents for root in allowed_roots)


if __name__ == "__main__":
    raise SystemExit(main())
