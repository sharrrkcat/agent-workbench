"""Read-only Phase 0 hygiene and database audit.

The cleanup itself is intentionally not implemented here.  This command only
reports the state of the checkout and, with ``--check``, returns a non-zero
status when a known Phase 0 invariant is violated.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEST_STUB_NAME = re.compile(r"^a2-embed-[0-9a-f]{8}$", re.IGNORECASE)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class AuditReport:
    root: str
    dist_present: bool
    dist_file_count: int
    model_file_count: int
    model_directory_count: int
    exact_test_stubs: tuple[str, ...]
    database_path: str
    database_exists: bool
    database_integrity: str | None
    alembic_revision: str | None
    business_table_count: int | None
    explicit_index_count: int | None
    backup_file_count: int
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_exact_test_stub(path: Path) -> bool:
    if not path.is_dir() or not TEST_STUB_NAME.fullmatch(path.name):
        return False
    files = [item for item in path.rglob("*") if item.is_file() and not item.is_symlink()]
    if len(files) != 1 or files[0].name != "config.json":
        return False
    try:
        return files[0].read_text(encoding="utf-8").strip() == "{}"
    except (OSError, UnicodeError):
        return False


def _count_files(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file() and not path.is_symlink())


def _read_database(path: Path) -> tuple[str | None, str | None, int | None, int | None, list[str]]:
    if not path.is_file():
        return None, None, None, None, []
    errors: list[str] = []
    integrity: str | None = None
    revision: str | None = None
    business_count: int | None = None
    index_count: int | None = None
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        return None, None, None, None, [f"database_open_failed:{exc}"]
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            errors.append(f"database_integrity:{integrity}")
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "alembic_version" in names:
            rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
            if len(rows) == 1:
                revision = str(rows[0][0])
            elif rows:
                errors.append("alembic_version_multiple_rows")
        from ai_workbench.db.migrations import (
            BASELINE_REVISION,
            CRITICAL_TABLES,
            validate_baseline_compatibility,
        )

        business_count = len(names & set(CRITICAL_TABLES))
        index_count = sum(
            1
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            if not str(row[0]).startswith("sqlite_")
        )
        if revision is not None and revision != BASELINE_REVISION:
            errors.append(f"unexpected_alembic_revision:{revision}")
        if revision == BASELINE_REVISION:
            from sqlalchemy import create_engine

            engine = create_engine(f"sqlite:///{path}")
            try:
                validate_baseline_compatibility(engine)
            except Exception as exc:
                errors.append(f"database_schema_invalid:{exc}")
            finally:
                engine.dispose()
        elif business_count:
            errors.append("database_unversioned")
    except sqlite3.Error as exc:
        errors.append(f"database_read_failed:{exc}")
    finally:
        connection.close()
    return revision, integrity, business_count, index_count, errors


def audit(root: Path, *, database_path: Path | None = None) -> AuditReport:
    root = root.expanduser().resolve()
    models_root = root / "data" / "models"
    embedding_root = models_root / "embeddings"
    stubs = tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in embedding_root.iterdir()
            if _is_exact_test_stub(path)
        )
        if embedding_root.is_dir()
        else ()
    )
    selected_database = database_path or (root / "data" / "agent_workbench.db")
    if not selected_database.is_absolute():
        selected_database = root / selected_database
    db_path = selected_database.expanduser().resolve()
    revision, integrity, business_count, index_count, errors = _read_database(db_path)
    dist = root / "dist"
    backup_root = db_path.parent / "backups" / "database"
    backup_count = (
        sum(1 for path in backup_root.glob("*.db") if path.is_file())
        if backup_root.is_dir()
        else 0
    )
    if dist.is_dir():
        errors.append("legacy_dist_present")
    if stubs:
        errors.append("exact_test_stubs_present")
    return AuditReport(
        root=str(root),
        dist_present=dist.is_dir(),
        dist_file_count=_count_files(dist),
        model_file_count=_count_files(models_root),
        model_directory_count=sum(1 for path in models_root.rglob("*") if path.is_dir()) if models_root.is_dir() else 0,
        exact_test_stubs=stubs,
        database_path=str(db_path),
        database_exists=db_path.is_file(),
        database_integrity=integrity,
        alembic_revision=revision,
        business_table_count=business_count,
        explicit_index_count=index_count,
        backup_file_count=backup_count,
        errors=tuple(errors),
    )


def _print_report(report: AuditReport, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return
    print(f"root: {report.root}")
    print(f"dist: {'present' if report.dist_present else 'absent'} ({report.dist_file_count} files)")
    print(f"models: {report.model_file_count} files, {report.model_directory_count} directories")
    print(f"exact test stubs: {len(report.exact_test_stubs)}")
    print(f"database: {'present' if report.database_exists else 'absent'} {report.database_path}")
    if report.database_exists:
        print(f"database integrity: {report.database_integrity}")
        print(f"alembic revision: {report.alembic_revision or '<none>'}")
        print(f"business tables: {report.business_table_count}; explicit indexes: {report.explicit_index_count}")
    print(f"database backups: {report.backup_file_count}")
    if report.errors:
        print("errors:")
        for error in report.errors:
            print(f"- {error}")
    else:
        print("errors: none")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="workbench root to inspect")
    parser.add_argument("--database", type=Path, help="database path (defaults to <root>/data/agent_workbench.db)")
    parser.add_argument("--check", action="store_true", help="return 1 when an invariant fails")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit JSON instead of text")
    args = parser.parse_args(argv)
    report = audit(args.root, database_path=args.database)
    _print_report(report, as_json=args.as_json)
    return 1 if args.check and report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
