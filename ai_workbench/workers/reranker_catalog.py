"""Native CrossEncoder directory metadata, without inference imports or model hashes."""
import json
from pathlib import Path

if __package__:
    from .common import WorkerError
    from .embedding_catalog import TRANSFORMER_CONFIG_FILES, package_file, package_path, validate_module_files
else:
    from common import WorkerError
    from embedding_catalog import TRANSFORMER_CONFIG_FILES, package_file, package_path, validate_module_files


def sequence_classifier(config):
    architectures = config.get("architectures", [])
    return (isinstance(architectures, list) and bool(architectures)
        and isinstance(architectures[0], str) and architectures[0].endswith("ForSequenceClassification"))


def is_reranker_directory(path: Path) -> bool:
    """Recognize package roots; inference validity belongs to inspection/loading."""
    if package_file(path, "modules.json").is_file():
        return True
    try:
        config = json.loads(package_file(path, "config.json").read_text(encoding="utf-8"))
        return isinstance(config, dict) and sequence_classifier(config)
    except (OSError, ValueError):
        return False


def inspect_reranker(root: Path, model_ref: str) -> dict:
    path = package_path(root, model_ref)
    diagnostics = []

    def problem(file, code, message):
        diagnostics.append({"file": file, "code": code, "message": message, "blocking": True})

    def read(name, *, required=False, array=False):
        try:
            value = json.loads(package_file(path, name).read_text(encoding="utf-8"))
            if not isinstance(value, list if array else dict):
                raise ValueError()
            return value
        except FileNotFoundError:
            if required:
                problem(name, "missing_config", "Required model configuration is missing.")
        except (OSError, ValueError):
            problem(name, "invalid_config", "Configuration has an invalid JSON structure.")
        return [] if array else {}

    config = read("config_sentence_transformers.json")
    if config.get("model_type", "CrossEncoder") != "CrossEncoder":
        problem("config_sentence_transformers.json", "unsupported_configuration", "A joint-input CrossEncoder is required.")
    prompts, prompt_name = config.get("prompts", {}), config.get("default_prompt_name")
    if (not isinstance(prompts, dict) or any(not isinstance(key, str) or not key or not isinstance(value, str)
            for key, value in prompts.items())):
        problem("config_sentence_transformers.json", "invalid_field", "Prompts must map names to text.")
        prompts = {}
    if prompt_name is not None and (not isinstance(prompt_name, str) or prompt_name not in prompts):
        problem("config_sentence_transformers.json", "invalid_field", "The default prompt must name a declared prompt.")
        prompt_name = None

    explicit = package_file(path, "modules.json").is_file()
    raw_modules = read("modules.json", array=True) if explicit else [{"idx": 0, "name": "0", "path": "",
        "type": "sentence_transformers.base.modules.transformer.Transformer"}]
    modules, names = [], set()
    for index, module in enumerate(raw_modules):
        if (not isinstance(module, dict) or any(not isinstance(module.get(key), str) for key in ("name", "path", "type"))
                or not module["name"] or module["name"] in names or type(module.get("idx", index)) is not int
                or module.get("idx", index) != index):
            problem("modules.json", "invalid_field", "Modules require unique names, ordered indices, local paths and class names.")
            continue
        names.add(module["name"])
        package_file(path, module["path"])
        modules.append({key: module[key] for key in ("name", "path", "type")})
    kinds = [module["type"].rsplit(".", 1)[-1] for module in modules]
    if not kinds or kinds[0] != "Transformer" or kinds.count("Transformer") != 1:
        problem("modules.json", "unsupported_configuration", "A single joint-input Transformer must start the pipeline.")
    for module, kind in zip(modules, kinds):
        if not module["type"].startswith("sentence_transformers."):
            problem("modules.json", "remote_code", "Custom module code is unsupported.")
        elif kind not in {"Transformer", "LogitScore", "Pooling", "Dense", "Normalize", "Dropout", "WeightedLayerPooling"}:
            problem("modules.json", "unsupported_configuration", "This module's joint-input scoring semantics are unsupported.")

    prefix = modules[0]["path"] + "/" if modules and modules[0]["path"] else ""
    backbone_file, tokenizer_file = prefix + "config.json", prefix + "tokenizer_config.json"
    backbone, tokenizer = read(backbone_file, required=True), read(tokenizer_file)
    model_type = backbone.get("model_type")
    if not isinstance(model_type, str) or not model_type:
        problem(backbone_file, "invalid_field", "The Transformer must declare its model_type.")
        model_type = None
    transformer_file = next((prefix + name for name in TRANSFORMER_CONFIG_FILES
        if package_file(path, prefix + name).is_file()), prefix + TRANSFORMER_CONFIG_FILES[0])
    transformer = read(transformer_file) if explicit else {}
    task = transformer.get("transformer_task", "feature-extraction") if explicit else "sequence-classification"
    if not explicit and not sequence_classifier(backbone):
        problem(backbone_file, "missing_scoring", "A causal or feature model requires an explicit native scoring pipeline.")
    if task not in {"sequence-classification", "text-generation", "feature-extraction"}:
        problem(transformer_file, "unsupported_configuration", "Only joint text-pair scoring is supported.")
    modalities = transformer.get("modality_config", {})
    if not isinstance(modalities, dict) or modalities.keys() - {"text", "message"}:
        problem(transformer_file, "unsupported_configuration", "Only text and query/document message inputs are supported.")
    if transformer.get("query_expansion") is not None:
        problem(transformer_file, "unsupported_configuration", "Late-interaction query expansion is unsupported.")

    method, labels = None, None
    output = transformer.get("module_output_name", {"text-generation": "causal_logits",
        "feature-extraction": "token_embeddings"}.get(task, "scores"))
    if task == "sequence-classification":
        id2label = backbone.get("id2label", {})
        labels = len(id2label) if isinstance(id2label, dict) and id2label else backbone.get("num_labels")
        if labels != 1 or type(labels) is not int or output != "scores" or not sequence_classifier(backbone):
            problem(backbone_file, "missing_scoring", "A saved single-score sequence-classification head is required.")
            labels = None
        else:
            method = "sequence_classification"
    for module, kind in zip(modules[1:], kinds[1:]):
        filename = (module["path"] + "/" if module["path"] else "") + "config.json"
        settings = read(filename, required=kind not in {"Normalize", "Dropout"})
        if kind == "Dense" and "activation_function" in settings and (
                not isinstance(settings["activation_function"], str) or not settings["activation_function"].startswith("torch.")):
            problem(filename, "remote_code", "Custom activation code is unsupported.")
        if kind == "LogitScore":
            tokens = [settings.get("true_token_id")]
            if settings.get("false_token_id") is not None:
                tokens.append(settings["false_token_id"])
            vocab = backbone.get("vocab_size")
            if (task != "text-generation" or settings.get("module_input_name", "causal_logits") != output
                    or any(type(token) is not int or token < 0 or type(vocab) is int and token >= vocab for token in tokens)):
                problem(filename, "missing_scoring", "LogitScore requires declared vocabulary tokens and matching causal logits.")
            else:
                method, labels = "logit_score", 1
        elif kind == "Dense" and settings.get("module_output_name") == "scores":
            if type(settings.get("out_features")) is not int or settings["out_features"] != 1:
                problem(filename, "missing_scoring", "The scoring projection must produce one value per pair.")
            else:
                method, labels = "dense", 1
    if method is None:
        problem("modules.json" if explicit else backbone_file, "missing_scoring", "A native single-score head is required; no scoring head is inferred.")

    processor = transformer.get("processor_kwargs", {})
    has_template = False
    if task == "text-generation":
        template = tokenizer.get("chat_template")
        template_file = prefix + "chat_template.jinja"
        if package_file(path, template_file).is_file():
            try:
                template = package_file(path, template_file).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                problem(template_file, "invalid_config", "The chat template cannot be read.")
        if isinstance(processor, dict) and "chat_template" in processor:
            template = processor["chat_template"]
        if isinstance(template, list):
            template = next((item.get("template") for item in template if isinstance(item, dict) and item.get("name") == "default"), None)
        elif isinstance(template, dict):
            template = template.get("default")
        has_template = isinstance(template, str) and bool(template.strip())
        if not has_template:
            problem(template_file, "missing_template", "A native query/document chat template is required.")

    native_settings = backbone.get("sentence_transformers", {})
    if not isinstance(native_settings, dict):
        problem(backbone_file, "invalid_field", "Sentence Transformers settings must be an object.")
        native_settings = {}
    activation = next((value for value in (config.get("activation_fn"), native_settings.get("activation_fn"),
        backbone.get("sbert_ce_default_activation_function")) if value is not None), "torch.nn.modules.activation.Sigmoid")
    if not isinstance(activation, str) or not activation.startswith("torch."):
        problem("config_sentence_transformers.json", "remote_code", "Custom activation code is unsupported.")
        activation = None
    limits = []
    for owner, settings, field in ((backbone_file, backbone, "max_position_embeddings"),
            (tokenizer_file, tokenizer, "model_max_length"), (transformer_file, transformer, "max_seq_length")):
        value = settings.get(field)
        if value is None or field == "max_position_embeddings" and value == -1:
            continue
        if type(value) is not int or value <= 0:
            problem(owner, "invalid_field", "Text limits must be positive integers.")
        elif value < 10**20:
            limits.append(value)
    processing = transformer.get("processing_kwargs", {})
    if (not isinstance(processing, dict) or any(not isinstance(value, dict) for value in processing.values())
            or not isinstance(processor, dict)):
        problem(transformer_file, "invalid_field", "Processing options must contain configuration objects.")
    else:
        processing_limit = processing.get("text", {}).get("max_length", processing.get("common", {}).get("max_length"))
        for value in (processor.get("model_max_length"), processing_limit):
            if value is not None:
                if type(value) is not int or value <= 0 or limits and value > min(limits):
                    problem(transformer_file, "unsupported_configuration", "Explicit processing limits exceed native capacity or are invalid.")
                else:
                    limits.append(value)
    if not limits:
        problem(backbone_file, "missing_token_limit", "No finite native text limit could be determined.")
    return {"kind": "reranker", "model_ref": model_ref, "architecture": "cross-encoder" if method else None,
        "model_type": model_type, "modules": modules, "scoring": {"method": method, "activation": activation},
        "max_seq_length": min(limits) if limits else None, "has_chat_template": has_template,
        "default_prompt_name": prompt_name, "diagnostics": diagnostics}


def load_configuration(root: Path, model_ref: str) -> tuple[Path, dict]:
    information = inspect_reranker(root, model_ref)
    if information["diagnostics"]:
        raise WorkerError("UNSUPPORTED_CAPABILITY")
    path = package_path(root, model_ref)
    validate_module_files(path, information["modules"])
    return path, information
