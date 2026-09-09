"""Read-only model-file inventory. Scanning never imports an inference runtime."""

from pathlib import Path
from ai_workbench.workers.tts_catalog import model_files

ROOTS = {"llm": "llms", "embedding": "embeddings", "reranker": "rerankers",
         "image_embedding": "image_embeddings", "vision": "vision", "tts": "tts"}


def inventory(repo_root: Path, kind: str | None = None) -> list[dict]:
    root = (repo_root / "data" / "models").resolve()
    items = []
    for model_kind, directory in ROOTS.items():
        if kind is not None and model_kind != kind:
            continue
        base = root / directory
        if not base.is_dir():
            continue
        seen = set()
        for path in sorted(base.rglob("*")):
            resolved = path.resolve()
            if not resolved.is_relative_to(base.resolve()) or not path.is_file():
                continue
            target = None
            if model_kind == "tts":
                if path.name == "model.onnx" and model_files(path.parent):
                    target = path.parent
            elif path.suffix.lower() == ".gguf" and not path.name.lower().startswith("mmproj"):
                target = path
            elif path.name in {"config.json", "model.onnx"} and model_kind != "tts":
                target = path.parent
            if target is None or target in seen:
                continue
            seen.add(target)
            items.append({"kind": model_kind, "name": target.name,
                          "model_ref": target.relative_to(root).as_posix(),
                          "state": "unavailable", "error_code": "MODEL_UNAVAILABLE"})
    return items
