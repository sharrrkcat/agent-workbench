"""CPU implementations imported exclusively by the managed worker."""
from __future__ import annotations

import base64
import csv
from io import BytesIO
from pathlib import Path

if __package__:
    from .protocol import WorkerError
else:
    from protocol import WorkerError


def images(values):
    import binascii
    from PIL import Image
    result = []
    for value in values:
        if not value.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")):
            raise WorkerError("INVALID_REQUEST")
        try:
            raw = base64.b64decode(value.split(",", 1)[1], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise WorkerError("INVALID_REQUEST") from exc
        if len(raw) > 10 * 1024 * 1024:
            raise WorkerError("REQUEST_TOO_LARGE", 413)
        try:
            with Image.open(BytesIO(raw)) as image:
                if image.width * image.height > 40_000_000:
                    raise WorkerError("REQUEST_TOO_LARGE", 413)
                result.append(image.convert("RGB"))
        except WorkerError:
            raise
        except (OSError, ValueError) as exc:
            raise WorkerError("INVALID_REQUEST") from exc
    return result


class Engine:
    def __init__(self, path: Path, kind, params, options):
        import torch
        from transformers import AutoModel, AutoModelForSequenceClassification, AutoProcessor, AutoTokenizer, AutoImageProcessor
        self.kind, self.params, self.options = kind, params, options
        self.torch = torch
        torch.set_num_threads(options["intraop_threads"])
        kwargs = {"local_files_only": True, "trust_remote_code": False}
        if kind == "vision" and params["architecture"] == "wd14":
            import onnxruntime as ort
            settings = ort.SessionOptions()
            settings.intra_op_num_threads = options["intraop_threads"]
            self.model = ort.InferenceSession(str(path / "model.onnx"), sess_options=settings, providers=["CPUExecutionProvider"])
            with (path / "selected_tags.csv").open(encoding="utf-8") as stream:
                self.tags = list(csv.DictReader(stream))
            return
        if kind in {"embedding", "reranker"}:
            self.processor = AutoTokenizer.from_pretrained(path, **kwargs)
            cls = AutoModel if kind == "embedding" else AutoModelForSequenceClassification
        elif kind == "vision":
            from transformers import Florence2ForConditionalGeneration
            cls = Florence2ForConditionalGeneration
            self.processor = AutoProcessor.from_pretrained(path, **kwargs)
        else:
            cls = AutoModel
            self.processor = AutoImageProcessor.from_pretrained(path, **kwargs)
        model, loading = cls.from_pretrained(path, output_loading_info=True, **kwargs)
        if loading.get("missing_keys") or loading.get("mismatched_keys"):
            raise WorkerError("MODEL_UNAVAILABLE", 503)
        if kind == "image_embedding":
            supported = {"clip": {"clip"}, "siglip2": {"siglip", "siglip2"}, "dinov2": {"dinov2"}}
            if model.config.model_type not in supported[params["architecture"]]:
                raise WorkerError("UNSUPPORTED_CAPABILITY")
        self.model = model.to("cpu").float().eval()

    def embed(self, texts):
        torch = self.torch
        torch.set_num_threads(self.options["intraop_threads"])
        with torch.inference_mode():
            inputs = self.processor(texts, padding=True, truncation=True, max_length=512, return_tensors="pt")
            outputs = self.model(**inputs).last_hidden_state
            mask = inputs["attention_mask"].unsqueeze(-1)
            vectors = (outputs * mask).sum(1) / mask.sum(1).clamp(min=1)
        return {"vectors": vectors.tolist()}

    def rerank(self, query, documents):
        torch = self.torch
        torch.set_num_threads(self.options["intraop_threads"])
        with torch.inference_mode():
            inputs = self.processor([query] * len(documents), documents, padding=True, truncation=True, max_length=512, return_tensors="pt")
            logits = self.model(**inputs).logits
            if logits.shape[-1] == 1:
                scores = logits.squeeze(-1).sigmoid()
            elif logits.shape[-1] == 2:
                scores = logits.softmax(-1)[:, 1]
            else:
                raise WorkerError("UNSUPPORTED_CAPABILITY")
        return {"scores": scores.tolist()}

    def image_embed(self, values):
        self.torch.set_num_threads(self.options["intraop_threads"])
        with self.torch.inference_mode():
            inputs = self.processor(images=images(values), return_tensors="pt")
            if self.params["architecture"] == "dinov2":
                vectors = self.model(**inputs).last_hidden_state[:, 0]
            else:
                vectors = self.model.get_image_features(**inputs)
        return {"vectors": vectors.tolist()}

    def vision(self, values):
        pictures = images(values)
        if self.params["architecture"] == "wd14":
            import numpy as np
            from PIL import Image
            model_input = self.model.get_inputs()[0]
            size = model_input.shape[1]
            if not isinstance(size, int):
                raise WorkerError("UNSUPPORTED_CAPABILITY")
            outputs = []
            for picture in pictures:
                side = max(picture.size)
                square = Image.new("RGB", (side, side), "white")
                square.paste(picture, ((side - picture.width) // 2, (side - picture.height) // 2))
                tensor = np.asarray(square.resize((size, size), Image.Resampling.BICUBIC), dtype=np.float32)[:, :, ::-1][None]
                scores = self.model.run(None, {model_input.name: tensor})[0][0]
                if len(scores) != len(self.tags):
                    raise WorkerError("MODEL_UNAVAILABLE", 503)
                outputs.append({"tags": [{"name": tag["name"], "score": float(score), "category": tag["category"]} for tag, score in zip(self.tags, scores) if float(score) >= 0.35]})
            return {"outputs": outputs}
        tasks = {"caption": "<CAPTION>", "detailed_caption": "<DETAILED_CAPTION>", "more_detailed_caption": "<MORE_DETAILED_CAPTION>", "ocr": "<OCR>"}
        task = tasks.get(self.params.get("task", "caption"))
        if task is None:
            raise WorkerError("UNSUPPORTED_CAPABILITY")
        results = []
        self.torch.set_num_threads(self.options["intraop_threads"])
        with self.torch.inference_mode():
            for picture in pictures:
                inputs = self.processor(text=task, images=picture, return_tensors="pt")
                generated = self.model.generate(**inputs, max_new_tokens=256, do_sample=False)
                text = self.processor.batch_decode(generated, skip_special_tokens=False)[0]
                parsed = self.processor.post_process_generation(text, task=task, image_size=picture.size)
                results.append({"text": str(parsed[task])})
        return {"outputs": results}
