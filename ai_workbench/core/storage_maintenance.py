from __future__ import annotations

from pathlib import Path
from itertools import islice
from typing import Any

from ai_workbench.core.attachments import attachments_root, referenced_attachment_filenames, delete_attachment_if_unreferenced
from ai_workbench.core.time import isoformat_utc, utc_now
from ai_workbench.db.database import get_database_url
from ai_workbench.db.migrations import HEAD_REVISION


def sqlite_database_path(database_url: str | None = None) -> Path | None:
    resolved = get_database_url(database_url)
    if not resolved.startswith("sqlite:///"):
        return None
    value = resolved.replace("sqlite:///", "", 1)
    if value == ":memory:":
        return None
    return Path(value).resolve()


def storage_stats(message_store: Any, database_url: str | None = None, *, persona_store=None, knowledge_store=None, run_store=None, qq_store=None) -> dict[str, Any]:
    warnings: list[str] = []
    db_path = sqlite_database_path(database_url)
    db_size = 0
    db_status = "ok"
    if db_path is not None:
        try:
            db_size = db_path.stat().st_size if db_path.exists() else 0
        except OSError as exc:
            db_status = "warning"
            warnings.append(f"database size unavailable: {exc}")

    try:
        scan = scan_orphan_attachments(message_store, persona_store=persona_store, knowledge_store=knowledge_store, run_store=run_store, qq_store=qq_store, include_details=False)
        attachment_count = scan["attachment_count"]
        attachment_size = scan["attachment_total_size_bytes"]
        orphan_count = scan["orphan_count"]
        orphan_size = scan["orphan_size_bytes"]
    except Exception as exc:
        warnings.append(f"attachment scan failed: {exc}")
        attachment_count = 0
        attachment_size = 0
        orphan_count = 0
        orphan_size = 0

    payload = {
        "database": {
            "status": db_status,
            "path": str(db_path) if db_path is not None else ":memory:",
            "size_bytes": db_size,
            "schema_revision": HEAD_REVISION,
        },
        "attachments": {
            "directory": str(attachments_root()),
            "count": attachment_count,
            "total_size_bytes": attachment_size,
            "orphan_count": orphan_count,
            "orphan_size_bytes": orphan_size,
            "last_scan_time": isoformat_utc(utc_now()),
        },
    }
    if warnings:
        payload["warnings"] = warnings
    return payload


def _scanned_files(message_store, *, persona_store, knowledge_store, run_store, qq_store):
    files = iter(_attachment_files(attachments_root()))
    while batch := list(islice(files, 128)):
        referenced = referenced_attachment_filenames(message_store, {path.name for path in batch},
            persona_store=persona_store, knowledge_store=knowledge_store, run_store=run_store, qq_store=qq_store)
        for path in batch:
            yield path, path.name not in referenced


def scan_orphan_attachments(message_store: Any, *, persona_store=None, knowledge_store=None, run_store=None, qq_store=None,
                           include_details: bool = True) -> dict[str, Any]:
    result = {"attachment_count": 0, "attachment_total_size_bytes": 0, "orphan_count": 0, "orphan_size_bytes": 0, "orphans": []}
    for path, orphan in _scanned_files(message_store, persona_store=persona_store, knowledge_store=knowledge_store, run_store=run_store, qq_store=qq_store):
        size = _safe_size(path)
        result["attachment_count"] += 1
        result["attachment_total_size_bytes"] += size
        if orphan:
            result["orphan_count"] += 1
            result["orphan_size_bytes"] += size
            if include_details:
                result["orphans"].append({"id": path.name, "path": str(path), "size_bytes": size})
    return result


def cleanup_orphan_attachments(message_store: Any, *, persona_store=None, knowledge_store=None, run_store=None, qq_store=None) -> dict[str, Any]:
    root = attachments_root().resolve()
    deleted_count = 0
    deleted_size = 0
    errors: list[dict[str, str]] = []
    for path, orphan in _scanned_files(message_store, persona_store=persona_store, knowledge_store=knowledge_store, run_store=run_store, qq_store=qq_store):
        if not orphan:
            continue
        try:
            path.relative_to(root)
        except ValueError:
            errors.append({"path": str(path), "error": "path is outside attachment directory"})
            continue
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
            removed = delete_attachment_if_unreferenced({"uri": "local://attachments/" + path.name}, message_store,
                persona_store=persona_store, knowledge_store=knowledge_store, run_store=run_store, qq_store=qq_store)
            if removed:
                deleted_count += 1
                deleted_size += size
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {"deleted_count": deleted_count, "deleted_size_bytes": deleted_size, "errors": errors}


def _attachment_files(root: Path):
    for child in ("images", "files"):
        directory = (root / child).resolve()
        try:
            directory.relative_to(root.resolve())
        except ValueError:
            continue
        if directory.exists():
            for path in directory.iterdir():
                if path.is_file() and not path.is_symlink():
                    yield path.resolve()


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
