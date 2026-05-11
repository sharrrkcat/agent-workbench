from __future__ import annotations

import sys
from types import ModuleType

import pytest

from scripts.download_knowledge_model import build_parser, download_model, target_path, validate_target


def test_validate_target_accepts_safe_folder_names() -> None:
    assert validate_target("all-MiniLM-L6-v2") == "all-MiniLM-L6-v2"
    assert validate_target("bge_m3.1") == "bge_m3.1"


@pytest.mark.parametrize("value", ["../x", "/abs", "nested/path", "nested\\path", "bad name", ""])
def test_validate_target_rejects_unsafe_names(value: str) -> None:
    with pytest.raises(Exception):
        validate_target(value)


def test_parser_requires_model_type_model_id_and_target() -> None:
    parser = build_parser()
    args = parser.parse_args(["--type", "embedding", "--model-id", "sentence-transformers/all-MiniLM-L6-v2", "--target", "mini"])
    assert args.type == "embedding"
    assert args.model_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert args.target == "mini"
    with pytest.raises(SystemExit):
        parser.parse_args(["--type", "bad", "--model-id", "x", "--target", "safe"])


def test_target_path_uses_project_model_directories(tmp_path) -> None:
    assert target_path(tmp_path, "embedding", "mini") == tmp_path / "data" / "models" / "embeddings" / "mini"
    assert target_path(tmp_path, "reranker", "ranker") == tmp_path / "data" / "models" / "rerankers" / "ranker"


def test_download_model_prints_clear_dependency_hint_when_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(RuntimeError) as exc:
        download_model("embedding", "sentence-transformers/all-MiniLM-L6-v2", "mini", repo_root=tmp_path)
    assert "sentence-transformers is not installed" in str(exc.value)
    assert "uv sync --extra knowledge" in str(exc.value)


def test_download_model_saves_embedding_and_reranker_with_stubbed_dependency(monkeypatch, tmp_path) -> None:
    module = ModuleType("sentence_transformers")
    saved: list[tuple[str, str]] = []

    class FakeModel:
        def __init__(self, model_id: str) -> None:
            self.model_id = model_id

        def save(self, destination: str) -> None:
            saved.append((self.model_id, destination))

    module.SentenceTransformer = FakeModel  # type: ignore[attr-defined]
    module.CrossEncoder = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    embedding_path = download_model("embedding", "sentence-transformers/all-MiniLM-L6-v2", "mini", repo_root=tmp_path)
    reranker_path = download_model("reranker", "BAAI/bge-reranker-v2-m3", "ranker", repo_root=tmp_path)

    assert embedding_path == tmp_path / "data" / "models" / "embeddings" / "mini"
    assert reranker_path == tmp_path / "data" / "models" / "rerankers" / "ranker"
    assert saved == [
        ("sentence-transformers/all-MiniLM-L6-v2", str(embedding_path)),
        ("BAAI/bge-reranker-v2-m3", str(reranker_path)),
    ]
