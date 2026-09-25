"""Native text-pair scoring, imported only inside the isolated reranker worker."""
if __package__:
    from .common import WorkerError, require_offline
    from .timing import stage
else:
    from common import WorkerError, require_offline
    from timing import stage


class RerankerEngine:
    def __init__(self, path, options, information):
        require_offline()
        with stage("import_torch"):
            import torch
        with stage("import_sentence_transformers"):
            from sentence_transformers import CrossEncoder
        self.torch = torch
        self.device, self.batch_size = options["device"], options["max_batch_size"]
        with stage("device_setup"):
            torch.set_num_threads(options["intraop_threads"])
            if self.device == "cuda" and not torch.cuda.is_available():
                raise WorkerError("RUNTIME_DEVICE_UNAVAILABLE", 503)
            self.device_name = torch.cuda.get_device_name(0) if self.device == "cuda" else "CPU"
        with stage("model_load"):
            self.model = CrossEncoder(str(path), device=self.device, backend="torch",
                local_files_only=True, trust_remote_code=False,
                model_kwargs={"dtype": "auto" if self.device == "cuda" else torch.float32,
                              "local_files_only": True, "trust_remote_code": False},
                processor_kwargs={"local_files_only": True, "trust_remote_code": False},
                config_kwargs={"local_files_only": True, "trust_remote_code": False})
            self.model.eval()
            if self.model.num_labels != 1:
                raise WorkerError("UNSUPPORTED_CAPABILITY")
            self.model.max_seq_length = information["max_seq_length"]
            self.dtype = self.model.dtype

    def rerank(self, query, documents):
        with self.torch.inference_mode():
            scores = self.model.predict([(query, document) for document in documents],
                batch_size=self.batch_size, show_progress_bar=False, convert_to_tensor=True).float()
            if tuple(scores.shape) != (len(documents),) or not self.torch.isfinite(scores).all().item():
                raise WorkerError("MODEL_UNAVAILABLE", 503)
            return {"scores": scores.cpu().tolist()}
