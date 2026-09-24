"""Small, dependency-free validation shared by isolated runtime families."""
import json
import sys
from pathlib import Path, PurePosixPath

_network_blocked = False


def require_offline():
    global _network_blocked
    if _network_blocked:
        return
    def reject_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            print("ONNX worker network access rejected", flush=True)
            raise RuntimeError("ONNX worker network access is disabled")
    sys.addaudithook(reject_network)
    _network_blocked = True


class WorkerError(Exception):
    def __init__(self, code, status=422):
        self.code, self.status = code, status


def publish_ready(path: Path, value: dict):
    # The supervisor polls for existence, so never expose a partially written file.
    pending = path.with_suffix('.tmp')
    pending.write_text(json.dumps(value), encoding='utf-8')
    pending.replace(path)


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise WorkerError("INVALID_REQUEST")


def strings(value, limit=2048):
    if not isinstance(value, list) or not 1 <= len(value) <= limit or any(not isinstance(x, str) or not x.strip() for x in value):
        raise WorkerError("INVALID_REQUEST")
    return value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise WorkerError("INVALID_REQUEST")
    return value


def safe_reference(ref):
    if not isinstance(ref, str) or not ref or "\\" in ref or ":" in ref or PurePosixPath(ref).is_absolute() or any(
        part in {"", ".", ".."} or part.rstrip(" .") != part for part in ref.split("/")
    ):
        raise WorkerError("INVALID_REQUEST")
    return ref


def local_model(root: Path, ref, *, wd14=False, tts=False):
    path = (root / safe_reference(ref)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise WorkerError("INVALID_REQUEST")
    if not path.is_dir():
        raise WorkerError("MODEL_NOT_FOUND", 404)
    # Validate links before any loader follows tokenizer or checkpoint references.
    if any(not item.resolve().is_relative_to(root.resolve()) for item in path.rglob("*")):
        raise WorkerError("INVALID_REQUEST")
    if tts:
        if __package__:
            from .tts_catalog import model_files
        else:
            from tts_catalog import model_files
        if not model_files(path):
            raise WorkerError("MODEL_NOT_FOUND", 404)
    elif wd14:
        if not all((path / name).is_file() for name in ("model.onnx", "selected_tags.csv")):
            raise WorkerError("MODEL_NOT_FOUND", 404)
    else:
        if not (path / "config.json").is_file() or not any(
            item.is_file() and item.name.startswith(("model", "pytorch_model"))
            and item.suffix in {".bin", ".safetensors"} for item in path.iterdir()
        ):
            raise WorkerError("MODEL_NOT_FOUND", 404)
        for name in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
            index = path / name
            if not index.is_file():
                continue
            try:
                value = json.loads(index.read_text(encoding="utf-8"))
                shards = value["weight_map"]
                if not isinstance(shards, dict) or not shards:
                    raise ValueError()
                for shard in set(shards.values()):
                    target = (path / safe_reference(shard)).resolve()
                    if not target.is_relative_to(path) or not target.is_file():
                        raise ValueError()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise WorkerError("MODEL_NOT_FOUND", 404) from exc
    return path
