from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ai_workbench.core.attachments import attachments_root
from ai_workbench.core.time import isoformat_utc, utc_now
from ai_workbench.db.database import SCHEMA_VERSION, get_database_url


def sqlite_database_path(database_url: str | None = None) -> Path | None:
    resolved = get_database_url(database_url)
    if not resolved.startswith("sqlite:///"):
        return None
    value = resolved.replace("sqlite:///", "", 1)
    if value == ":memory:":
        return None
    return Path(value).resolve()


def storage_stats(message_store: Any, database_url: str | None = None) -> dict[str, Any]:
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
        scan = scan_orphan_attachments(message_store)
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
            "schema_version": SCHEMA_VERSION,
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


def scan_orphan_attachments(message_store: Any) -> dict[str, Any]:
    root = attachments_root()
    files = _attachment_files(root)
    referenced = referenced_attachment_filenames(message_store)
    orphans = []
    total_size = 0
    for path in files:
        size = _safe_size(path)
        total_size += size
        if path.name in referenced:
            continue
        orphans.append({"id": path.name, "path": str(path), "size_bytes": size})
    return {
        "attachment_count": len(files),
        "attachment_total_size_bytes": total_size,
        "orphan_count": len(orphans),
        "orphan_size_bytes": sum(item["size_bytes"] for item in orphans),
        "orphans": orphans,
    }


def cleanup_orphan_attachments(message_store: Any) -> dict[str, Any]:
    root = attachments_root().resolve()
    scan = scan_orphan_attachments(message_store)
    deleted_count = 0
    deleted_size = 0
    errors: list[dict[str, str]] = []
    for orphan in scan["orphans"]:
        path = Path(orphan["path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append({"path": str(path), "error": "path is outside attachment directory"})
            continue
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
            path.unlink()
            deleted_count += 1
            deleted_size += size
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {"deleted_count": deleted_count, "deleted_size_bytes": deleted_size, "errors": errors}


def referenced_attachment_filenames(message_store: Any) -> set[str]:
    try:
        messages = message_store.list_all_messages()
    except Exception:
        return set()
    referenced: set[str] = set()
    for message in messages:
        attachments = (getattr(message, "metadata", {}) or {}).get("attachments")
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            uri = attachment.get("uri")
            if isinstance(uri, str) and uri.startswith("local://attachments/"):
                referenced.add(uri.removeprefix("local://attachments/"))
    return referenced


def _attachment_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for child in ("images", "files"):
        directory = (root / child).resolve()
        try:
            directory.relative_to(root.resolve())
        except ValueError:
            continue
        if directory.exists():
            files.extend(path.resolve() for path in directory.iterdir() if path.is_file())
    return sorted(files)


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
