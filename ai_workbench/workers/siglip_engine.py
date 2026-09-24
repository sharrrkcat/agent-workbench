"""Single-tower SigLIP inference. Heavy libraries are imported only inside the worker."""
import base64
import hashlib
from io import BytesIO
import json

if __package__:
    from .common import WorkerError, require_offline
    from .siglip_catalog import STRUCTURES, read_config
else:
    from common import WorkerError, require_offline
    from siglip_catalog import STRUCTURES, read_config

PIPELINE_VERSION = "siglip-pil-tokenizers-v1"
IMAGE_RULES = ("do_resize", "size", "resample", "do_rescale", "rescale_factor", "do_normalize",
               "image_mean", "image_std", "do_convert_rgb", "patch_size", "max_num_patches")


def signature(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def libraries():
    import torch
    import transformers
    import tokenizers
    from PIL import Image
    return torch, transformers, tokenizers, Image


def load_processing(path, structure, config, transformers, tokenizers):
    prefix = "Siglip2" if structure == "naflex" else "Siglip"
    processor = getattr(transformers, prefix + "ImageProcessorPil").from_dict(
        read_config(path / "preprocessor_config.json"))
    # Load the serialized backend directly: no SentencePiece conversion or remote code.
    tokenizer = transformers.PreTrainedTokenizerFast.from_pretrained(str(path),
        tokenizer_file=str(path / "tokenizer.json"), local_files_only=True, trust_remote_code=False)
    lowercase = tokenizer.init_kwargs.get("do_lower_case") is True
    if lowercase:
        original = tokenizer.backend_tokenizer.normalizer
        normalizers = [tokenizers.normalizers.Lowercase()]
        if original is not None:
            normalizers.append(original)
        # Backend normalization preserves added special tokens marked normalized=False.
        tokenizer.backend_tokenizer.normalizer = tokenizers.normalizers.Sequence(normalizers)
    text_length = config.text_config.max_position_embeddings
    attention_mask = "attention_mask" in tokenizer.model_input_names
    rules = {"pipeline": PIPELINE_VERSION, "structure": structure,
        "transformers": transformers.__version__, "tokenizers": tokenizers.__version__,
        "image": {"processor": type(processor).__name__, "input": "static-exif-white-rgb",
                  **{key: getattr(processor, key, None) for key in IMAGE_RULES}},
        "text": {"backend": signature(json.loads(tokenizer.backend_tokenizer.to_str())),
                 "lowercase": lowercase, "max_length": text_length, "padding": "max_length",
                 "truncation": True, "padding_side": tokenizer.padding_side,
                 "truncation_side": tokenizer.truncation_side, "add_special_tokens": True,
                 "attention_mask": attention_mask, "token_type_ids": False},
        "pooling": "pooler_output", "normalization": "float32-l2", "output_dtype": "float32"}
    return processor, tokenizer, rules


class SiglipEngine:
    def __init__(self, path, tower, options, revision):
        require_offline()
        raw_config = read_config(path / "config.json")
        structure = STRUCTURES.get(raw_config.get("model_type"))
        if structure is None:
            raise WorkerError("UNSUPPORTED_CAPABILITY")
        torch, transformers, tokenizers, self.Image = libraries()
        self.torch, self.tower, self.batch_size = torch, tower, options["max_batch_size"]
        torch.set_num_threads(options["intraop_threads"])
        cuda = options["device"] == "cuda"
        if cuda and not torch.cuda.is_available():
            raise WorkerError("RUNTIME_DEVICE_UNAVAILABLE", 503)
        self.device, self.dtype = ("cuda:0", torch.float16) if cuda else ("cpu", torch.float32)
        prefix = "Siglip2" if structure == "naflex" else "Siglip"
        config = getattr(transformers, prefix + "Config").from_dict(raw_config)
        self.processor, self.tokenizer, rules = load_processing(path, structure, config, transformers, tokenizers)
        self.text_length = config.text_config.max_position_embeddings
        self.attention_mask = rules["text"]["attention_mask"]
        model_type = getattr(transformers, prefix + ("VisionModel" if tower == "image" else "TextModel"))
        tower_config = config.vision_config if tower == "image" else config.text_config
        # Native loading owns checkpoint interpretation. Only the selected tower is instantiated.
        self.model = model_type.from_pretrained(str(path), config=tower_config, local_files_only=True,
            trust_remote_code=False, use_safetensors=True, dtype=self.dtype).to(self.device).eval()
        dimensions = self.model.config.hidden_size if tower == "image" else self.model.config.projection_size
        self.info = {"tower": tower, "device": options["device"],
            "device_name": torch.cuda.get_device_name(0) if cuda else "CPU",
            "dtype": "float16" if cuda else "float32", "output_dtype": "float32", "dimensions": dimensions,
            "model_revision": revision, "vector_space_id": signature({"model_revision": revision,
                "dimensions": dimensions, "rules": rules})}

    def embed(self, inputs):
        vectors = []
        with self.torch.inference_mode():
            for start in range(0, len(inputs), self.batch_size):
                values = inputs[start:start + self.batch_size]
                if self.tower == "image":
                    images = []
                    for value in values:
                        with self.Image.open(BytesIO(base64.b64decode(value.partition(",")[2], validate=True))) as source:
                            images.append(source.convert("RGB"))
                    batch = self.processor(images=images, return_tensors="pt")
                else:
                    batch = self.tokenizer(values, padding="max_length", truncation=True,
                        max_length=self.text_length, add_special_tokens=True, return_tensors="pt",
                        return_attention_mask=self.attention_mask, return_token_type_ids=False)
                batch = {key: value.to(device=self.device, dtype=self.dtype if value.is_floating_point() else value.dtype)
                         for key, value in batch.items()}
                pooled = self.model(**batch).pooler_output.float()
                normalized = self.torch.nn.functional.normalize(pooled, p=2, dim=-1)
                vectors.extend(normalized.cpu().tolist())
        return {**self.info, "vectors": vectors, "usage": None, "timing": None}
