"""Explicit attachment cleanup with the same reference owners as the API."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_workbench.core.personas import PersonaStore
from ai_workbench.core.qq_store import QQStore
from ai_workbench.core.storage_maintenance import cleanup_orphan_attachments, scan_orphan_attachments, sqlite_database_path
from ai_workbench.db.database import get_database_url, get_engine
from ai_workbench.db.stores import SqlMessageStore, SqlKnowledgeStore, SqlRunStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove unreferenced local attachment files.")
    parser.add_argument("--apply", action="store_true", help="delete orphan files; default is dry-run")
    parser.add_argument("--database-url", default=None, help="override the SQLite database URL")
    args = parser.parse_args(argv)
    url = get_database_url(args.database_url)
    path = sqlite_database_path(url)
    if path is None or not path.is_file():
        parser.error("Choose an existing Cogita SQLite database.")
    engine = get_engine(url)
    try:
        messages = SqlMessageStore(engine)
        owners = dict(persona_store=PersonaStore(engine), knowledge_store=SqlKnowledgeStore(engine),
                      run_store=SqlRunStore(engine), qq_store=QQStore(engine))
        scan = scan_orphan_attachments(messages, **owners)
        result = cleanup_orphan_attachments(messages, **owners) if args.apply else {"deleted_count": 0, "errors": []}
        print(f"referenced count: {scan['attachment_count'] - scan['orphan_count']}")
        print(f"orphan count: {scan['orphan_count']}")
        print(f"deleted count: {result['deleted_count']}")
        print(f"errors: {len(result['errors'])}")
        for error in result["errors"]:
            print(f"{error.get('path')}: {error.get('error')}")
        if not args.apply:
            print("dry-run: pass --apply to delete orphan files")
        return 1 if result["errors"] else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
