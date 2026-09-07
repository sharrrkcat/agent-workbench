"""Metadata-only accounting for the supervisor's runtime directory."""
from __future__ import annotations

from collections import Counter, defaultdict
import os
from pathlib import Path
import stat

from ai_workbench.core.models.runtimes.schema import (
    RuntimeStorage, StorageGroup, StorageUsage, StorageWarning,
)


def is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _signature(info: os.stat_result):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def unknown_usage() -> StorageUsage:
    return StorageUsage(complete=False, file_count=None, logical_bytes=None,
                        unique_bytes=None, shared_bytes=None, exclusive_bytes=None)


def scan_storage(base: Path) -> RuntimeStorage:
    base = Path(base)
    groups = {
        name: StorageGroup(id=name, category=category, relative_path=name)
        for name, category in ((".cache", "cache"), ("python", "python"),
                               (".staging", "staging"), (".processes", "processes"), ("other", "other"))
    }
    files: dict[Path, tuple[os.stat_result, str]] = {}
    directories: dict[Path, os.stat_result] = {}
    incomplete: set[str] = set()
    warnings: list[StorageWarning] = []
    skipped_links = 0

    def group_for(path: Path):
        parts = path.relative_to(base).parts
        if parts and parts[0] in groups:
            return parts[0]
        if len(parts) >= 3 and parts[0] in {"llama-server", "py"}:
            key = "/".join(parts[:3])
            if key not in groups:
                is_llama = parts[0] == "llama-server"
                groups[key] = StorageGroup(id=key, category="runtime", relative_path=key,
                    runtime_id="llama-server" if is_llama else "python-worker",
                    version=parts[1] if is_llama else parts[2], variant=parts[2] if is_llama else parts[1])
            return key
        return "other"

    def problem(path: Path, code: str):
        incomplete.add(group_for(path))
        if path == base:
            incomplete.update(groups)
        if len(warnings) < 100:
            warnings.append(StorageWarning(code=code, relative_path=path.relative_to(base).as_posix()))

    def walk(directory: Path):
        nonlocal skipped_links
        try:
            before = directory.lstat()
            if is_link(before):
                skipped_links += 1
                problem(directory, "STORAGE_CHANGED")
                return
            if not stat.S_ISDIR(before.st_mode):
                problem(directory, "STORAGE_CHANGED")
                return
            group_for(directory)
            directories[directory] = before
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    try:
                        info = path.lstat()
                        if is_link(info):
                            skipped_links += 1
                            key = group_for(path)
                            if groups[key].relative_path == path.relative_to(base).as_posix():
                                problem(path, "STORAGE_LINK_ROOT")
                        elif stat.S_ISDIR(info.st_mode):
                            walk(path)
                        elif stat.S_ISREG(info.st_mode):
                            key = group_for(path)
                            files[path] = (info, key)
                            if not info.st_ino or info.st_nlink < 1:
                                problem(path, "STORAGE_ID_UNAVAILABLE")
                    except OSError:
                        problem(path, "STORAGE_UNREADABLE")
        except OSError:
            problem(directory, "STORAGE_UNREADABLE")

    try:
        # Reject redirected roots while excluding links encountered inside the tree.
        redirected = False
        for path in (base.parent, base):
            try:
                redirected = redirected or is_link(path.lstat())
            except FileNotFoundError:
                pass
        if redirected:
            incomplete.update(groups)
            problem(base, "STORAGE_LINK_ROOT")
        else:
            try:
                base.lstat()
            except FileNotFoundError:
                pass
            else:
                walk(base)
    except OSError:
        incomplete.update(groups)
        problem(base, "STORAGE_UNREADABLE")

    # A second metadata pass detects replacements, link-count changes and directory edits.
    for path, (info, _) in files.items():
        try:
            if _signature(path.lstat()) != _signature(info):
                problem(path, "STORAGE_CHANGED")
        except OSError:
            problem(path, "STORAGE_CHANGED")
    for path, info in directories.items():
        try:
            if _signature(path.lstat()) != _signature(info):
                problem(path, "STORAGE_CHANGED")
        except OSError:
            problem(path, "STORAGE_CHANGED")

    by_id = defaultdict(list)
    for info, key in files.values():
        by_id[(info.st_dev, info.st_ino)].append((info, key))
    counts = Counter(key for _, key in files.values())
    logical = Counter()
    unique = Counter()
    shared = Counter()
    exclusive = Counter()
    total_shared = total_exclusive = 0
    for info, key in files.values():
        logical[key] += info.st_size
    for entries in by_id.values():
        info = entries[0][0]
        if any(_signature(other) != _signature(info) for other, _ in entries):
            incomplete.update(key for _, key in entries)
        refs = Counter(key for _, key in entries)
        for key, count in refs.items():
            unique[key] += info.st_size
            (exclusive if info.st_nlink == count else shared)[key] += info.st_size
        if info.st_nlink == len(entries):
            total_exclusive += info.st_size
        else:
            total_shared += info.st_size

    for key, group in groups.items():
        usage = unknown_usage() if key in incomplete else StorageUsage(file_count=counts[key],
            logical_bytes=logical[key], unique_bytes=unique[key], shared_bytes=shared[key], exclusive_bytes=exclusive[key])
        groups[key] = group.model_copy(update=usage.model_dump())
    totals = unknown_usage() if incomplete else StorageUsage(file_count=len(files), logical_bytes=sum(logical.values()),
        unique_bytes=total_shared + total_exclusive, shared_bytes=total_shared, exclusive_bytes=total_exclusive)
    return RuntimeStorage(complete=not incomplete, totals=totals, groups=list(groups.values()),
                          warnings=warnings, skipped_links=skipped_links)
