from __future__ import annotations

import fnmatch
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session as DbSession
from sqlmodel import select

from ai_workbench.core.knowledge_settings import KnowledgeSettings
from ai_workbench.core.time import utc_now
from ai_workbench.db.models import KnowledgeOriginRecord, KnowledgeSourceRecord


SUPPORTED_ORIGIN_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".html",
    ".css",
    ".env",
    ".log",
    ".csv",
    ".sql",
    ".sh",
    ".ps1",
    ".bat",
    ".ini",
    ".cfg",
}
SKIPPED_DIRS = {".git", "node_modules", "__pycache__"}


@dataclass(frozen=True)
class OriginFileSnapshot:
    path: Path
    relative_path: str
    folder_path: str
    file_name: str
    extension: str
    path_depth: int
    mtime: datetime
    size_bytes: int
    content_hash: str
    uri: str
    mime_type: str


def safe_origin_slug(value: str) -> str:
    slug = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
        raise ValueError("Origin slug must be a safe lowercase ASCII folder name.")
    if "/" in slug or "\\" in slug or ".." in slug or not all(part for part in slug.split("/")):
        raise ValueError("Origin slug must not contain path separators or traversal.")
    return slug


def origin_root_for_slug(repo_root: Path, slug: str) -> Path:
    safe = safe_origin_slug(slug)
    base = (repo_root / "data" / "knowledge" / "origins").resolve()
    root = (base / safe).resolve()
    try:
        root.relative_to(base)
    except ValueError as exc:
        raise ValueError("Origin root must stay inside data/knowledge/origins/<origin_slug>.") from exc
    return root


def validate_origin_root(repo_root: Path, slug: str, root_path: str) -> Path:
    expected = origin_root_for_slug(repo_root, slug)
    candidate = (repo_root / root_path).resolve() if not Path(root_path).is_absolute() else Path(root_path).resolve()
    if candidate != expected:
        raise ValueError("Origin root must be data/knowledge/origins/<origin_slug>.")
    return expected


def scan_origin_files(
    *,
    engine: Any,
    origin_id: str,
    repo_root: Path,
    settings: KnowledgeSettings,
) -> dict[str, Any]:
    with DbSession(engine) as session:
        origin = session.get(KnowledgeOriginRecord, origin_id)
        if origin is None:
            raise KeyError(f"unknown knowledge origin: {origin_id}")
        root = validate_origin_root(repo_root, origin.slug, origin.root_path)
        root.mkdir(parents=True, exist_ok=True)
        existing = {
            record.relative_path: record
            for record in session.exec(
                select(KnowledgeSourceRecord)
                .where(KnowledgeSourceRecord.origin_id == origin.id)
                .where(KnowledgeSourceRecord.status != "deleted")
            ).all()
            if record.relative_path
        }
        warnings: list[str] = []
        snapshots = _iter_origin_snapshots(root=root, origin=origin, settings=settings, warnings=warnings)
        seen: set[str] = set()
        counts = {"new_count": 0, "changed_count": 0, "missing_count": 0, "unchanged_count": 0, "failed_count": 0}
        now = utc_now()
        for snapshot in snapshots:
            seen.add(snapshot.relative_path)
            record = existing.get(snapshot.relative_path)
            if record is None:
                record = KnowledgeSourceRecord(
                    id=_source_id_for_origin_file(origin.id, snapshot.relative_path),
                    knowledge_base_id=origin.knowledge_base_id,
                    origin_id=origin.id,
                    source_type="origin_file",
                    status="new",
                    file_status="new",
                    content_hash=snapshot.content_hash,
                )
                counts["new_count"] += 1
            elif record.content_hash != snapshot.content_hash or record.source_size_bytes != snapshot.size_bytes:
                if record.indexed_at is None:
                    record.status = "new"
                record.file_status = "changed"
                record.error = None
                counts["changed_count"] += 1
            else:
                if record.status in {"new", "changed", "missing", "failed"}:
                    record.status = "new" if record.indexed_at is None else "indexed"
                    record.file_status = "new" if record.indexed_at is None else "ready"
                counts["unchanged_count"] += 1
            _apply_snapshot(record, snapshot)
            record.updated_at = now
            session.add(record)

        for relative_path, record in existing.items():
            if relative_path in seen:
                continue
            if record.indexed_at is None:
                record.status = "missing"
            record.file_status = "missing"
            record.updated_at = now
            session.add(record)
            counts["missing_count"] += 1

        origin.last_scan_at = now
        origin.status = "ready"
        origin.error = None
        origin.metadata_json = _summary_metadata(counts, warnings)
        origin.updated_at = now
        session.add(origin)
        session.commit()
        return {"origin_id": origin.id, **counts, "warnings": warnings}


def mark_origin_imported(*, engine: Any, origin_id: str, summary: dict[str, Any]) -> None:
    with DbSession(engine) as session:
        origin = session.get(KnowledgeOriginRecord, origin_id)
        if origin is None:
            return
        origin.last_import_at = utc_now()
        origin.status = "ready"
        origin.error = None
        origin.metadata_json = _summary_metadata(summary, list(summary.get("warnings") or []))
        origin.updated_at = utc_now()
        session.add(origin)
        session.commit()


def _iter_origin_snapshots(
    *,
    root: Path,
    origin: KnowledgeOriginRecord,
    settings: KnowledgeSettings,
    warnings: list[str],
) -> list[OriginFileSnapshot]:
    include_globs = _glob_list(origin.include_globs) or ["**/*"]
    exclude_globs = _glob_list(origin.exclude_globs)
    snapshots: list[OriginFileSnapshot] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        try:
            resolved = path.resolve()
            relative = resolved.relative_to(root)
        except ValueError:
            warnings.append(f"Skipped path outside origin root: {path}")
            continue
        parts = relative.parts
        if any(part.startswith(".") or part in SKIPPED_DIRS for part in parts[:-1]):
            continue
        if path.is_symlink():
            warnings.append(f"Skipped symlink: {relative.as_posix()}")
            continue
        relative_path = relative.as_posix()
        if not any(_glob_matches(relative_path, pattern) for pattern in include_globs):
            continue
        if any(_glob_matches(relative_path, pattern) for pattern in exclude_globs):
            continue
        extension = resolved.suffix.lower()
        if extension not in SUPPORTED_ORIGIN_EXTENSIONS:
            warnings.append(f"Skipped unsupported file type: {relative_path}")
            continue
        stat = resolved.stat()
        if stat.st_size > settings.max_source_size_bytes:
            warnings.append(f"Skipped oversized file: {relative_path}")
            continue
        try:
            raw = resolved.read_bytes()
            raw.decode("utf-8")
        except UnicodeDecodeError:
            warnings.append(f"Skipped non-UTF-8 or binary file: {relative_path}")
            continue
        snapshots.append(
            OriginFileSnapshot(
                path=resolved,
                relative_path=relative_path,
                folder_path=relative.parent.as_posix() if str(relative.parent) != "." else "",
                file_name=relative.name,
                extension=extension,
                path_depth=len(relative.parts),
                mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                size_bytes=stat.st_size,
                content_hash=hashlib.sha256(raw).hexdigest(),
                uri=f"data/knowledge/origins/{origin.slug}/{relative_path}",
                mime_type=mimetypes.guess_type(resolved.name)[0] or "text/plain",
            )
        )
    return sorted(snapshots, key=lambda item: item.relative_path)


def _apply_snapshot(record: KnowledgeSourceRecord, snapshot: OriginFileSnapshot) -> None:
    record.uri = snapshot.uri
    record.title = snapshot.relative_path
    record.relative_path = snapshot.relative_path
    record.virtual_path = snapshot.relative_path
    record.folder_path = snapshot.folder_path
    record.file_name = snapshot.file_name
    record.extension = snapshot.extension
    record.path_depth = snapshot.path_depth
    record.mime_type = snapshot.mime_type
    record.size_bytes = snapshot.size_bytes
    record.source_size_bytes = snapshot.size_bytes
    record.source_mtime = snapshot.mtime
    record.content_hash = snapshot.content_hash
    record.metadata_json = _source_metadata(snapshot)


def _source_metadata(snapshot: OriginFileSnapshot) -> str:
    import json

    return json.dumps(
        {
            "relative_path": snapshot.relative_path,
            "virtual_path": snapshot.relative_path,
            "folder_path": snapshot.folder_path,
            "file_name": snapshot.file_name,
            "extension": snapshot.extension,
            "path_depth": snapshot.path_depth,
        },
        ensure_ascii=False,
    )


def _summary_metadata(counts: dict[str, Any], warnings: list[str]) -> str:
    import json

    return json.dumps({"last_scan_summary": counts, "warnings": warnings[:50]}, ensure_ascii=False, default=str)


def _glob_list(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").replace("\n", ",").split(",") if part.strip()]


def _glob_matches(relative_path: str, pattern: str) -> bool:
    if pattern == "**/*":
        return True
    if fnmatch.fnmatch(relative_path, pattern):
        return True
    if pattern.startswith("**/") and fnmatch.fnmatch(relative_path, pattern[3:]):
        return True
    return False


def _source_id_for_origin_file(origin_id: str, relative_path: str) -> str:
    digest = hashlib.sha256(f"{origin_id}:{relative_path}".encode("utf-8")).hexdigest()[:32]
    return f"origin_{digest}"
