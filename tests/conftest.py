"""Suite-wide hygiene checks for user-owned model files.

Tests that need model fixtures must use ``tmp_path`` (and pass it as the
application root). This guard detects additions and removals in the checkout's
``data/models`` directory without reading model contents or calculating hashes.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_ROOT = REPO_ROOT / "data" / "models"


def _snapshot_model_files() -> set[str]:
    if not MODELS_ROOT.is_dir():
        return set()
    return {path.relative_to(MODELS_ROOT).as_posix() for path in MODELS_ROOT.rglob("*")
            if not path.is_symlink() and path.is_file()}


@pytest.fixture(scope="session", autouse=True)
def repository_model_files_are_unchanged():
    before = _snapshot_model_files()
    yield
    after = _snapshot_model_files()
    if before == after:
        return
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    details = []
    if added:
        details.append(f"added={added}")
    if removed:
        details.append(f"removed={removed}")
    pytest.fail("tests added or removed repository data/models files: " + "; ".join(details), pytrace=False)


@pytest.fixture(autouse=True)
def cogita_responses_match_openapi(monkeypatch, request):
    """Existing domain regressions also verify the actual HTTP response schema."""
    from fastapi.testclient import TestClient
    from tests.openapi_assertions import validate_cogita_response

    original = TestClient.request
    validators = {}
    coverage = getattr(request.config, "_cogita_openapi_coverage", None)
    if coverage is None:
        coverage = request.config._cogita_openapi_coverage = set()

    def checked(client, *args, **kwargs):
        response = original(client, *args, **kwargs)
        operation = validate_cogita_response(client.app, response, validators)
        if operation is not None:
            coverage.add(operation)
        return response

    monkeypatch.setattr(TestClient, "request", checked)


def pytest_terminal_summary(terminalreporter, config):
    coverage = getattr(config, "_cogita_openapi_coverage", set())
    operations = {(path, method) for path, method, _ in coverage}
    terminalreporter.write_line(
        f"OpenAPI response validation: {len(operations)} HTTP operations, {len(coverage)} operation/status combinations."
    )
