from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


TARGET_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
MODEL_DIRS = {
    "embedding": "embeddings",
    "reranker": "rerankers",
}


def validate_target(value: str) -> str:
    target = value.strip()
    path = Path(target)
    if not target:
        raise argparse.ArgumentTypeError("target must not be empty.")
    if path.is_absolute() or ".." in path.parts or "/" in target or "\\" in target:
        raise argparse.ArgumentTypeError("target must be a safe folder name, not a path.")
    if not TARGET_NAME_RE.fullmatch(target):
        raise argparse.ArgumentTypeError("target may only contain letters, numbers, dot, dash, and underscore.")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download a Hugging Face / Sentence Transformers model into the local Knowledge model directory.",
    )
    parser.add_argument("--type", choices=sorted(MODEL_DIRS), required=True, help="Knowledge model type.")
    parser.add_argument("--model-id", required=True, help="Hugging Face or Sentence Transformers model id.")
    parser.add_argument("--target", type=validate_target, required=True, help="Safe target folder name under data/models.")
    return parser


def target_path(repo_root: Path, model_type: str, target: str) -> Path:
    return repo_root / "data" / "models" / MODEL_DIRS[model_type] / target


def download_model(model_type: str, model_id: str, target: str, repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    destination = target_path(root, model_type, target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if model_type == "embedding":
            from sentence_transformers import SentenceTransformer  # type: ignore

            model = SentenceTransformer(model_id)
        else:
            from sentence_transformers import CrossEncoder  # type: ignore

            model = CrossEncoder(model_id)
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed. Install Knowledge dependencies first, for example:\n"
            '  uv sync --extra knowledge\n'
            '  or: uv pip install ".[knowledge]"'
        ) from exc
    model.save(str(destination))
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        saved_path = download_model(args.type, args.model_id, args.target)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"saved path: {saved_path}")
    print("next step: Settings -> Knowledge -> Defaults -> Overview -> Scan local models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
