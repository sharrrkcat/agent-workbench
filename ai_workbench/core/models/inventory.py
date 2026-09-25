"""Read-only model-file inventory. Scanning never imports an inference runtime."""

from pathlib import Path
from ai_workbench.workers.common import WorkerError
from ai_workbench.workers.model_catalog import inspect_directory

ROOTS = {"llm": "llms", "embedding": "embeddings", "reranker": "rerankers",
         "image_embedding": "image_embeddings", "vision": "vision", "tts": "tts", "asr": "asr"}


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
            if model_kind == "vision":
                if path.name == "model.onnx" and (path.parent / "selected_tags.csv").is_file():
                    try:
                        inspect_directory(root, model_kind, path.parent.relative_to(root).as_posix()).require_complete()
                        target = path.parent
                    except WorkerError:
                        continue
            elif model_kind == "tts":
                if path.name in {"model.onnx", "t3_cfg.safetensors", "config.json"}:
                    try:
                        inspect_directory(root, model_kind, path.parent.relative_to(root).as_posix()).require_complete()
                        target = path.parent
                    except WorkerError:
                        continue
            elif model_kind in {"image_embedding", "asr"}:
                if path.name == "config.json":
                    target = path.parent
            elif model_kind == "embedding":
                if path.name == "modules.json":
                    target = path.parent
            elif model_kind == "reranker":
                if path.name in {"modules.json", "config.json"} and not any(
                    (parent / "modules.json").is_file() for parent in path.parent.parents
                    if parent.is_relative_to(base)
                ):
                    from ai_workbench.workers.reranker_catalog import is_reranker_directory
                    try:
                        if is_reranker_directory(path.parent.resolve()):
                            target = path.parent
                    except WorkerError:
                        continue
            elif path.suffix.lower() == ".gguf" and not path.name.lower().startswith("mmproj"):
                target = path.parent
            elif path.name in {"config.json", "model.onnx"} and model_kind != "tts":
                target = path.parent
            if target is None or target in seen:
                continue
            seen.add(target)
            items.append({"kind": model_kind, "name": target.name,
                          "model_ref": target.relative_to(root).as_posix(),
                          "state": "unavailable", "error_code": "MODEL_UNAVAILABLE"})
    return items
