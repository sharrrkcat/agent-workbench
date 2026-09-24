"""WD14-family CPU ONNX inference, imported only in an isolated worker."""
import base64
import csv
from io import BytesIO
import math

if __package__:
    from .common import WorkerError, require_offline
    from .timing import stage
else:
    from common import WorkerError, require_offline
    from timing import stage


class WD14Engine:
    def __init__(self, path, kind, params, options):
        require_offline()
        self.kind = kind
        with stage("engine_imports"):
            import numpy as np
            import onnxruntime as ort
            from PIL import Image
        self.np, self.Image = np, Image
        try:
            with stage("labels"):
                with (path / "selected_tags.csv").open(encoding="utf-8-sig", newline="") as source:
                    self.labels = [(row["name"], {0: "general", 4: "character", 9: None}[int(row["category"])])
                                   for row in csv.DictReader(source)]
            with stage("onnx_session"):
                settings = ort.SessionOptions()
                settings.intra_op_num_threads = options["intraop_threads"]
                settings.log_severity_level = 3
                self.model = ort.InferenceSession(str(path / "model.onnx"), sess_options=settings,
                                                 providers=["CPUExecutionProvider"])
                input_info = self.model.get_inputs()[0]
                self.input_name = input_info.name
                self.output_name = self.model.get_outputs()[0].name
                self.image_size = (int(input_info.shape[2]), int(input_info.shape[1]))
        except (OSError, ValueError, TypeError, KeyError, IndexError, csv.Error) as exc:
            raise WorkerError("MODEL_UNAVAILABLE", 503) from exc

    def _image_batch(self, url):
        # ModelManager has already decoded, oriented and composited this static PNG.
        Image, np = self.Image, self.np
        with Image.open(BytesIO(base64.b64decode(url.partition(",")[2], validate=True))) as source:
            rgb = source.convert("RGB")
        side = max(rgb.size)
        square = Image.new("RGB", (side, side), "white")
        square.paste(rgb, ((side - rgb.width) // 2, (side - rgb.height) // 2))
        resized = square.resize(self.image_size, resample=Image.Resampling.BICUBIC)
        bgr = np.asarray(resized, dtype=np.float32)[:, :, ::-1]
        return np.ascontiguousarray(np.expand_dims(bgr, axis=0))

    def tags(self, images, thresholds):
        outputs = []
        try:
            for index, image in enumerate(images):
                (batch_scores,) = self.model.run([self.output_name], {self.input_name: self._image_batch(image)})
                (scores,) = batch_scores
                tags = []
                # Exact unpacking and zip preserve the actual CSV-to-output mapping.
                for (name, category), raw_score in zip(self.labels, scores, strict=True):
                    score = float(raw_score)
                    if not math.isfinite(score) or not 0 <= score <= 1:
                        raise WorkerError("MODEL_UNAVAILABLE", 503)
                    if category is not None and score >= thresholds[category]:
                        tags.append({"name": name, "category": category, "score": score})
                tags.sort(key=lambda tag: -tag["score"])
                outputs.append({"object": "image.tags", "index": index, "tags": tags})
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            raise WorkerError("MODEL_UNAVAILABLE", 503) from exc
        return {"outputs": outputs}
