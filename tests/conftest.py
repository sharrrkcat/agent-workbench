"""Suite-wide hygiene checks for user-owned model files.

Tests that need model fixtures must use ``tmp_path`` (and pass it as the
application root).  This guard makes an accidental write to the checkout's
``data/models`` directory fail the suite instead of leaving test artifacts
behind.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_ROOT = REPO_ROOT / "data" / "models"


def _snapshot_model_files() -> dict[str, tuple[int, str]]:
    if not MODELS_ROOT.is_dir():
        return {}
    snapshot: dict[str, tuple[int, str]] = {}
    for path in sorted(MODELS_ROOT.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        relative = path.relative_to(MODELS_ROOT).as_posix()
        snapshot[relative] = (path.stat().st_size, digest.hexdigest())
    return snapshot


@pytest.fixture(scope="session", autouse=True)
def repository_model_files_are_unchanged():
    before = _snapshot_model_files()
    yield
    after = _snapshot_model_files()
    if before == after:
        return
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
    details = []
    if added:
        details.append(f"added={added}")
    if removed:
        details.append(f"removed={removed}")
    if changed:
        details.append(f"changed={changed}")
    pytest.fail("tests modified repository data/models files: " + "; ".join(details), pytrace=False)
