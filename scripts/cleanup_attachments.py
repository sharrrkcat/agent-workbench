import argparse
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_workbench.core.attachments import attachments_root
from ai_workbench.db.database import get_database_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove unreferenced local attachment files.")
    parser.add_argument("--apply", action="store_true", help="delete orphan files; default is dry-run")
    parser.add_argument("--database-url", default=None, help="override the SQLite database URL")
    args = parser.parse_args(argv)

    referenced = _referenced_attachment_filenames(args.database_url)
    files = _attachment_files()
    orphan_files = [path for path in files if path.name not in referenced]
    deleted = 0
    errors: list[str] = []

    if args.apply:
        for path in orphan_files:
            try:
                path.unlink()
                deleted += 1
            except OSError as exc:
                errors.append(f"{path}: {exc}")

    print(f"referenced count: {len(referenced)}")
    print(f"orphan count: {len(orphan_files)}")
    print(f"deleted count: {deleted}")
    print(f"errors: {len(errors)}")
    for error in errors:
        print(error)
    if not args.apply:
        print("dry-run: pass --apply to delete orphan files")
    return 1 if errors else 0


def _attachment_files() -> list[Path]:
    files: list[Path] = []
    for child in ("images", "files"):
        root = attachments_root() / child
        if root.exists():
            files.extend(path for path in root.iterdir() if path.is_file())
    return sorted(files)


def _referenced_attachment_filenames(database_url: str | None) -> set[str]:
    db_path = _sqlite_path(database_url)
    if db_path is None or not db_path.exists():
        return set()
    referenced: set[str] = set()
    with sqlite3.connect(db_path) as connection:
        try:
            rows = connection.execute("SELECT metadata_json FROM messagerecord").fetchall()
        except sqlite3.Error:
            return referenced
    for (metadata_json,) in rows:
        try:
            metadata = json.loads(metadata_json or "{}")
        except json.JSONDecodeError:
            continue
        attachments = metadata.get("attachments")
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            uri = attachment.get("uri")
            if isinstance(uri, str) and uri.startswith("local://attachments/"):
                referenced.add(uri.removeprefix("local://attachments/"))
    return referenced


def _sqlite_path(database_url: str | None) -> Path | None:
    resolved = get_database_url(database_url)
    if not resolved.startswith("sqlite:///"):
        return None
    value = resolved.replace("sqlite:///", "", 1)
    if value == ":memory:":
        return None
    return Path(value).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
