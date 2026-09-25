"""Local Sentence Transformers metadata, without inference imports or model hashes."""
import json
from pathlib import Path

if __package__:
    from .common import WorkerError, safe_reference
else:
    from common import WorkerError, safe_reference


POOLING_FLAGS = {
    "pooling_mode_cls_token": "cls", "pooling_mode_max_tokens": "max",
    "pooling_mode_mean_tokens": "mean", "pooling_mode_mean_sqrt_len_tokens": "mean_sqrt_len_tokens",
    "pooling_mode_weightedmean_tokens": "weightedmean", "pooling_mode_lasttoken": "lasttoken",
}
TRANSFORMER_CONFIG_FILES = ("sentence_bert_config.json", "sentence_roberta_config.json",
    "sentence_distilbert_config.json", "sentence_camembert_config.json", "sentence_albert_config.json",
    "sentence_xlm-roberta_config.json", "sentence_xlnet_config.json")


def package_path(root: Path, model_ref: str) -> Path:
    path = (root / safe_reference(model_ref)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise WorkerError("INVALID_REQUEST")
    if not path.is_dir():
        raise WorkerError("MODEL_NOT_FOUND", 404)
    return path


def package_file(path: Path, name: str) -> Path:
    target = (path / safe_reference(name)).resolve() if name else path
    if not target.is_relative_to(path):
        raise WorkerError("INVALID_REQUEST")
    return target


def inspect_embedding(root: Path, model_ref: str, parameters: dict | None = None) -> dict:
    path = package_path(root, model_ref)
    diagnostics = []

    def problem(file, code, message, *, blocking=True):
        diagnostics.append({"file": file, "code": code, "message": message, "blocking": blocking})

    def read(name, *, required=False, array=False):
        file = package_file(path, name)
        try:
            value = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(value, list if array else dict):
                raise ValueError()
            return value
        except FileNotFoundError:
            if required:
                problem(name, "missing_config", "Required model configuration is missing.")
        except (OSError, ValueError):
            problem(name, "invalid_config", "Configuration has an invalid JSON structure.")
        return [] if array else {}

    def positive(value, file, field):
        if type(value) is int and value > 0:
            return value
        problem(file, "invalid_field", f"The declared {field} must be a positive integer.")
        return None

    config = read("config_sentence_transformers.json")
    if config.get("model_type", "SentenceTransformer") != "SentenceTransformer":
        problem("config_sentence_transformers.json", "unsupported_configuration", "A dense Sentence Transformer package is required.")
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict) or any(not isinstance(k, str) or not k or not isinstance(v, str) for k, v in prompts.items()):
        problem("config_sentence_transformers.json", "invalid_field", "Prompts must map names to text.")
        prompts = {}
    default_prompt = config.get("default_prompt_name")
    if default_prompt is not None and (not isinstance(default_prompt, str) or default_prompt not in prompts):
        problem("config_sentence_transformers.json", "invalid_field", "The default prompt must name a declared prompt.")
        default_prompt = None
    similarity = config.get("similarity_fn_name") or "cosine"
    if similarity not in ("cosine", "dot"):
        problem("config_sentence_transformers.json", "unsupported_configuration", "Only cosine and dot similarity are supported.")
        similarity = None

    def prompt_for(purpose, names):
        selected = (parameters or {}).get(purpose + "_prompt_name")
        if selected is not None:
            if not isinstance(selected, str) or selected not in prompts:
                problem("config_sentence_transformers.json", "invalid_prompt", f"The selected {purpose} prompt is not declared by this directory.")
                return None
            return selected
        selected = next((name for name in names if name in prompts), default_prompt)
        if purpose == "query" and prompts and selected is None:
            problem("config_sentence_transformers.json", "ambiguous_prompt", "Select a declared query prompt for this task.")
        return selected

    query_prompt = prompt_for("query", ("query", "web_search_query"))
    document_prompt = prompt_for("document", ("document", "passage", "corpus"))
    raw_modules = read("modules.json", required=True, array=True)
    if not raw_modules:
        problem("modules.json", "missing_pipeline", "An explicit embedding pipeline is required; default pooling is not inferred.")
    modules, pooling, token_limits = [], [], []
    dimensions, model_type, normalize = None, None, None
    names = set()
    for index, module in enumerate(raw_modules):
        if (not isinstance(module, dict) or any(not isinstance(module.get(key), str) for key in ("name", "path", "type"))
                or not module["name"] or module["name"] in names or type(module.get("idx", index)) is not int
                or module.get("idx", index) != index):
            problem("modules.json", "invalid_field", "Pipeline modules require unique names, ordered indices, local paths and class names.")
            continue
        names.add(module["name"])
        module_path = module["path"]
        package_file(path, module_path)
        modules.append({key: module[key] for key in ("name", "path", "type")})
        if not module["type"].startswith("sentence_transformers."):
            problem("modules.json", "remote_code", "Custom module code is unsupported.")
            continue
        kind = module["type"].rsplit(".", 1)[-1]
        prefix = module_path + "/" if module_path else ""
        filename = prefix + "config.json"
        if kind == "Transformer":
            backbone = read(filename, required=True)
            declared_type = backbone.get("model_type")
            if not isinstance(declared_type, str) or not declared_type:
                problem(filename, "invalid_field", "The Transformer must declare its model_type.")
            else:
                model_type = declared_type
            tokenizer = read(prefix + "tokenizer_config.json")
            # Use the metadata filenames recognized by native Transformer.load_config.
            transformer_file = next((prefix + name for name in TRANSFORMER_CONFIG_FILES
                if package_file(path, prefix + name).is_file()), prefix + TRANSFORMER_CONFIG_FILES[0])
            transformer_config = read(transformer_file)
            limits = []
            for owner, settings, field in ((filename, backbone, "max_position_embeddings"),
                    (prefix + "tokenizer_config.json", tokenizer, "model_max_length"),
                    (transformer_file, transformer_config, "max_seq_length")):
                if settings.get(field) is not None:
                    if field == "max_position_embeddings" and settings[field] == -1:
                        continue
                    limit = positive(settings[field], owner, field)
                    if limit is not None and limit < 10**20:
                        limits.append(limit)
            if not limits:
                problem(filename, "missing_token_limit", "No finite native text limit could be determined.")
            processing = transformer_config.get("processing_kwargs", {})
            if not isinstance(processing, dict) or any(not isinstance(processing.get(key, {}), dict) for key in ("text", "common")):
                problem(transformer_file, "invalid_field", "Processing options must contain configuration objects.")
            else:
                explicit_limit = processing.get("text", {}).get("max_length", processing.get("common", {}).get("max_length"))
                for field, value in (("processing max_length", explicit_limit),
                        ("query_length", transformer_config.get("query_length")),
                        ("document_length", transformer_config.get("document_length"))):
                    if value is not None:
                        limit = positive(value, transformer_file, field)
                        if limit is not None and limits and limit > min(limits):
                            problem(transformer_file, "unsupported_configuration", "Explicit processing limits exceed the native model/tokenizer limit.")
                        if field == "processing max_length" and limit is not None:
                            token_limits.append(limit)
            token_limits.extend(limits)
            normalize = False
        elif kind == "Pooling":
            settings = read(filename, required=True)
            dimension = settings.get("embedding_dimension", settings.get("word_embedding_dimension"))
            dimension = positive(dimension, filename, "embedding_dimension")
            modes = settings.get("pooling_mode")
            if modes is None:
                flags = {key: value for key, value in settings.items() if key.startswith("pooling_mode_")}
                if any(type(value) is not bool for value in flags.values()) or flags.keys() - POOLING_FLAGS.keys():
                    problem(filename, "invalid_field", "Pooling flags must be booleans.")
                modes = [mode for key, mode in POOLING_FLAGS.items() if flags.get(key) is True]
            elif isinstance(modes, str):
                modes = [modes]
            if not isinstance(modes, list) or not modes or any(not isinstance(mode, str) or not mode for mode in modes):
                problem(filename, "missing_pooling", "An explicit pooling mode is required.")
                modes = []
            elif any(mode not in POOLING_FLAGS.values() for mode in modes):
                problem(filename, "unsupported_configuration", "The declared pooling mode is unsupported.")
            include_prompt = settings.get("include_prompt", True)
            if type(include_prompt) is not bool:
                problem(filename, "invalid_field", "include_prompt must be a boolean.")
                include_prompt = None
            pooling.append({"module": module["name"], "modes": modes, "include_prompt": include_prompt})
            dimensions = dimension * len(modes) if dimension and modes else None
            normalize = False
        elif kind == "Dense":
            settings = read(filename, required=True)
            dimensions = positive(settings.get("out_features"), filename, "out_features")
            normalize = False
        elif kind == "Normalize":
            # Native Normalize has no required files; its declared path need not exist.
            normalize = True
        elif kind not in {"Dropout", "WeightedLayerPooling"}:
            problem("modules.json", "unsupported_configuration", "The declared module's dense embedding semantics cannot be inspected.")
            dimensions, normalize = None, None
    if raw_modules and not pooling:
        problem("modules.json", "missing_pooling", "An explicit supported pooling stage is required.")
    truncate = config.get("truncate_dim")
    if truncate is not None:
        truncate = positive(truncate, "config_sentence_transformers.json", "truncate_dim")
        if truncate and dimensions:
            if truncate < dimensions:
                normalize = False
            dimensions = min(truncate, dimensions)
    return {"kind": "embedding", "model_ref": model_ref, "model_type": model_type,
        "modules": modules, "pooling": pooling, "normalize": normalize, "dimensions": dimensions,
        "max_seq_length": min(token_limits) if token_limits else None, "similarity": similarity,
        "prompts": prompts, "query_prompt_name": query_prompt, "document_prompt_name": document_prompt,
        "diagnostics": diagnostics}


def load_configuration(root: Path, model_ref: str, parameters: dict) -> tuple[Path, dict]:
    information = inspect_embedding(root, model_ref, parameters)
    if any(item["blocking"] for item in information["diagnostics"]):
        raise WorkerError("UNSUPPORTED_CAPABILITY")
    path = package_path(root, model_ref)
    validate_module_files(path, information["modules"])
    return path, information


def validate_module_files(path: Path, modules: list[dict]) -> None:
    # Check links and shard references at the resource boundary, never file contents.
    for entry in path.rglob("*"):
        package_file(path, entry.relative_to(path).as_posix())
    for module in modules:
        directory = package_file(path, module["path"])
        if not directory.is_dir():
            if module["type"].rsplit(".", 1)[-1] == "Normalize":
                continue
            raise WorkerError("MODEL_NOT_FOUND", 404)
        if module["type"].rsplit(".", 1)[-1] == "Transformer" and not any(
            item.is_file() and item.name.startswith(("model", "pytorch_model"))
            and item.suffix in {".safetensors", ".bin"} for item in directory.iterdir()
        ):
            raise WorkerError("MODEL_NOT_FOUND", 404)
        for name in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
            index = directory / name
            if index.is_file():
                try:
                    shards = json.loads(index.read_text(encoding="utf-8"))["weight_map"]
                    if not isinstance(shards, dict) or not shards:
                        raise ValueError()
                    for shard in set(shards.values()):
                        target = package_file(path, (directory / safe_reference(shard)).relative_to(path).as_posix())
                        if not target.is_file():
                            raise ValueError()
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise WorkerError("MODEL_NOT_FOUND", 404) from exc
