import argparse
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_workbench.db.database import get_database_url
from ai_workbench.core.storage_maintenance import cleanup_orphan_attachments, scan_orphan_attachments, sqlite_database_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove unreferenced local attachment files.")
    parser.add_argument("--apply", action="store_true", help="delete orphan files; default is dry-run")
    parser.add_argument("--database-url", default=None, help="override the SQLite database URL")
    args = parser.parse_args(argv)

    store = _SqliteMessageMetadataStore(args.database_url)
    scan = scan_orphan_attachments(store)
    result = {"deleted_count": 0, "errors": []}
    if args.apply:
        result = cleanup_orphan_attachments(store)

    print(f"referenced count: {len(_referenced_attachment_filenames(args.database_url))}")
    print(f"orphan count: {scan['orphan_count']}")
    print(f"deleted count: {result['deleted_count']}")
    print(f"errors: {len(result['errors'])}")
    for error in result["errors"]:
        print(f"{error.get('path')}: {error.get('error')}")
    if not args.apply:
        print("dry-run: pass --apply to delete orphan files")
    return 1 if result["errors"] else 0


class _SqliteMessageMetadataStore:
    def __init__(self, database_url: str | None) -> None:
        self.database_url = database_url

    def list_all_messages(self) -> list:
        db_path = _sqlite_path(self.database_url)
        if db_path is None or not db_path.exists():
            return []
        messages = []
        with sqlite3.connect(db_path) as connection:
            try:
                rows = connection.execute("SELECT metadata_json FROM messagerecord").fetchall()
            except sqlite3.Error:
                return messages
        for (metadata_json,) in rows:
            try:
                metadata = json.loads(metadata_json or "{}")
            except json.JSONDecodeError:
                metadata = {}
            messages.append(SimpleNamespace(metadata=metadata))
        return messages


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
    return sqlite_database_path(get_database_url(database_url))


if __name__ == "__main__":
    raise SystemExit(main())
