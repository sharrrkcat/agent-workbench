"""Application-owned lifecycle around the pinned Transformers v5 serve engine."""
import sys

if __package__:
    from .common import WorkerError
else:
    from common import WorkerError

_network_blocked = False


class StopFilter:
    def __init__(self, stops):
        self.stops = [value for value in stops if value]
        self.pending = ""
        self.stopped = False

    def feed(self, text="", *, final=False):
        if self.stopped:
            return ""
        self.pending += text
        matches = [position for stop in self.stops if (position := self.pending.find(stop)) >= 0]
        if matches:
            result = self.pending[:min(matches)]
            self.pending, self.stopped = "", True
            return result
        keep = 0 if final else max((size for stop in self.stops for size in range(1, min(len(stop), len(self.pending) + 1))
                                   if self.pending.endswith(stop[:size])), default=0)
        result = self.pending[:-keep] if keep else self.pending
        self.pending = self.pending[-keep:] if keep else ""
        return result


def require_offline():
    global _network_blocked
    if _network_blocked:
        return

    def reject_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            raise RuntimeError("Transformers worker network access is disabled")

    sys.addaudithook(reject_network)
    _network_blocked = True


class TransformersEngine:
    def __init__(self, path, options):
        require_offline()
        import torch
        from transformers import AutoConfig, AutoModelForCausalLM, AutoModelForMultimodalLM, AutoProcessor
        from transformers.cli.serving.chat_completion import ChatCompletionHandler
        from transformers.cli.serving.model_manager import ModelManager
        from transformers.cli.serving.utils import GenerationState, get_response_template
        from transformers.models.auto.modeling_auto import MODEL_FOR_MULTIMODAL_LM_MAPPING_NAMES
        from transformers.utils import logging

        logging.disable_progress_bar()
        torch.set_num_threads(options["intraop_threads"])
        device = "cpu"
        device_name = "CPU"
        if options["device"] == "cuda":
            try:
                if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
                    raise RuntimeError("CUDA is unavailable")
                torch.cuda.set_device(0)
                torch.empty(1, device="cuda:0")
                device, device_name = "cuda:0", torch.cuda.get_device_name(0)
            except Exception as exc:
                raise WorkerError("RUNTIME_DEVICE_UNAVAILABLE", 503) from exc

        class LocalModelManager(ModelManager):
            # The upstream cache key is opaque. Request bodies never become paths
            # or Hub names, including local filenames containing an '@' character.
            def _load_processor(self, _model_id):
                return AutoProcessor.from_pretrained(path, local_files_only=True, trust_remote_code=False)

            def _load_model(self, _model_id, tqdm_class=None, progress_callback=None):
                config = AutoConfig.from_pretrained(path, local_files_only=True, trust_remote_code=False)
                model_class = AutoModelForMultimodalLM if config.model_type in MODEL_FOR_MULTIMODAL_LM_MAPPING_NAMES else AutoModelForCausalLM
                model, loading = model_class.from_pretrained(
                    path, config=config, local_files_only=True, trust_remote_code=False,
                    device_map=device, dtype="float32" if device == "cpu" else "auto",
                    attn_implementation="sdpa", tqdm_class=tqdm_class, output_loading_info=True,
                )
                if loading.get("missing_keys") or loading.get("mismatched_keys"):
                    raise WorkerError("MODEL_UNAVAILABLE", 503)
                model.eval()
                expected = torch.device(device)
                if any(parameter.device != expected for parameter in model.parameters()):
                    raise WorkerError("RUNTIME_DEVICE_UNAVAILABLE", 503)
                return model

        class LocalChatCompletionHandler(ChatCompletionHandler):
            def __init__(self, manager, generation, stops):
                super().__init__(manager, generation)
                self.content_stop = StopFilter(stops)
                self.reasoning_stop = StopFilter(stops)

            def _build_generation_config(self, body, model_generation_config, use_cb=False):
                config = super()._build_generation_config(body, model_generation_config, use_cb=use_cb)
                if body.get("temperature") is not None:
                    config.do_sample = body["temperature"] > 0
                    if not config.do_sample:
                        config.temperature = 1.0
                elif body.get("top_p") is not None:
                    config.do_sample = True
                return config

            def _build_chunk_sse(self, *args, **kwargs):
                final = kwargs.get("finish_reason") is not None
                for key, filter_ in (("content", self.content_stop), ("reasoning_content", self.reasoning_stop)):
                    value = kwargs.get(key)
                    if value is not None or final:
                        value = filter_.feed(value or "", final=final)
                        kwargs[key] = value or None
                if final and kwargs["finish_reason"] != "tool_calls" and (self.content_stop.stopped or self.reasoning_stop.stopped):
                    kwargs["finish_reason"] = "stop"
                # v5.16.1 omits the OpenAI terminal sentinel and includes matched
                # stop strings. Keep those transport adaptations version-owned.
                return super()._build_chunk_sse(*args, **kwargs) + ("data: [DONE]\n\n" if final else "")

            def _build_completion(self, request_id, content, model_id, finish_reason, usage=None, tool_calls=None, reasoning_content=None):
                content = self.content_stop.feed(content or "", final=True)
                reasoning_content = self.reasoning_stop.feed(reasoning_content or "", final=True) or None
                if finish_reason != "tool_calls" and (self.content_stop.stopped or self.reasoning_stop.stopped):
                    finish_reason = "stop"
                result = super()._build_completion(request_id, content, model_id, finish_reason,
                    usage=usage, tool_calls=tool_calls, reasoning_content=reasoning_content)
                if tool_calls and not content:
                    result["choices"][0]["message"]["content"] = None
                return result

        self.manager = LocalModelManager(device=device, dtype="float32" if device == "cpu" else "auto",
                                         model_timeout=-1, force_model="managed", trust_remote_code=False,
                                         attn_implementation="sdpa")
        self.generation = GenerationState(continuous_batching=False, compile=False)
        self.handler_type = LocalChatCompletionHandler
        resident = self.manager.loaded_models["managed@main"]
        template = get_response_template(resident.processor, resident.model)
        self.metadata = {"protocol_version": 1, "device": device, "device_name": device_name,
                         "dtype": str(resident.model.dtype), "tool_calls": bool(template and template.get("fields", {}).get("tool_calls"))}

    async def chat(self, body, request_id):
        if (body.get("tools") or any(message.get("tool_calls") or message["role"] == "tool" for message in body["messages"])) and not self.metadata["tool_calls"]:
            raise WorkerError("UNSUPPORTED_CAPABILITY")
        stops = body.get("stop") or []
        handler = self.handler_type(self.manager, self.generation, [stops] if isinstance(stops, str) else stops)
        return await handler.handle_request(body, request_id)

    def close(self):
        self.generation.shutdown()
        self.manager.shutdown()
