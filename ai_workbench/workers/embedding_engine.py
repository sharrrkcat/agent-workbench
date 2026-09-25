"""Native dense text embedding execution, imported only inside the worker."""
if __package__:
    from .common import WorkerError, require_offline
    from .timing import stage
else:
    from common import WorkerError, require_offline
    from timing import stage


class EmbeddingEngine:
    def __init__(self, path, options, information):
        require_offline()
        with stage("import_torch"):
            import torch
        with stage("import_sentence_transformers"):
            from sentence_transformers import SentenceTransformer
        self.torch, self.information = torch, information
        self.device = options["device"]
        self.batch_size = options["max_batch_size"]
        with stage("device_setup"):
            torch.set_num_threads(options["intraop_threads"])
            if self.device == "cuda" and not torch.cuda.is_available():
                raise WorkerError("RUNTIME_DEVICE_UNAVAILABLE", 503)
            self.device_name = torch.cuda.get_device_name(0) if self.device == "cuda" else "CPU"
        with stage("model_load"):
            self.model = SentenceTransformer(str(path), device=self.device, backend="torch",
                local_files_only=True, trust_remote_code=False,
                model_kwargs={"dtype": "auto" if self.device == "cuda" else torch.float32,
                              "local_files_only": True, "trust_remote_code": False},
                processor_kwargs={"local_files_only": True, "trust_remote_code": False},
                config_kwargs={"local_files_only": True, "trust_remote_code": False})
            self.model.eval()
            if information["max_seq_length"] is not None:
                self.model.max_seq_length = information["max_seq_length"]
            self.dimensions = self.model.get_embedding_dimension()
            if (type(self.dimensions) is not int or self.dimensions < 1
                    or information["dimensions"] is not None and self.dimensions != information["dimensions"]):
                raise WorkerError("EMBEDDING_DIMENSION_MISMATCH")
            self.dtype = self.model.dtype

    def embed(self, texts, purpose, dimensions):
        if dimensions is not None and dimensions != self.dimensions:
            raise WorkerError("EMBEDDING_DIMENSION_MISMATCH")
        prompt_name = self.information[purpose + "_prompt_name"]
        # Explicit empty prompt prevents a query-oriented default leaking into documents.
        prompt = self.information["prompts"][prompt_name] if prompt_name is not None else ""
        with self.torch.inference_mode():
            output = self.model.encode(texts, prompt=prompt, task=purpose,
                batch_size=self.batch_size, show_progress_bar=False,
                convert_to_tensor=True, normalize_embeddings=False)
            output = output.float()
            if (output.ndim != 2 or tuple(output.shape) != (len(texts), self.dimensions)
                    or not self.torch.isfinite(output).all().item()
                    or (output.norm(dim=1) == 0).any().item()):
                raise WorkerError("EMBEDDING_DIMENSION_MISMATCH", 503)
            return {"vectors": output.cpu().tolist(), "similarity": self.information["similarity"]}
