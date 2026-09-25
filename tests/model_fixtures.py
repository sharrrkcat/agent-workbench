import json
from pathlib import Path

import httpx

from ai_workbench.core.models.openai_adapter import OpenAIAdapter


def write_local_model(root: Path, reference: str, engine: str) -> Path:
    """Write a minimal recognizable model package under an isolated test root."""
    path = root / "data/models" / reference
    path.mkdir(parents=True, exist_ok=True)
    if engine == "qwen3tts":
        from tests.audio_fixtures import qwen_model
        return qwen_model(path)
    files = {
        "llama-server": {"model.gguf": b"fixture"},
        "transformers": {"config.json": b"{}", "model.safetensors": b"fixture"},
        "kokoro": {"config.json": b'{"model_type":"style_text_to_speech_2"}',
            "tokenizer.json": b"{}", "tokenizer_config.json": b"{}", "model.onnx": b"fixture"},
        "chatterbox": {name: b"fixture" for name in ("ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json")},
        "wd14": {"model.onnx": b"fixture", "selected_tags.csv": b"name,category\ntag,0\n"},
    }[engine]
    for name, data in files.items():
        (path / name).write_bytes(data)
    return path


def resolve_local_profile(root: Path, profile):
    from ai_workbench.core.models.resolution import configure_profile, resolve_profile
    return configure_profile(resolve_profile(root, profile))


class MockOpenAI:
    def __init__(self, response="reply"):
        self.response = response
        self.calls = []
        self.failure = None
        self.stream_events = None

    def factory(self, provider):
        return OpenAIAdapter(provider, transport=httpx.MockTransport(self.handle))

    async def handle(self, request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "fake"}, {"id": "embed"}, {"id": "other"}]})
        data = json.loads(request.content)
        self.calls.append(data)
        if self.failure:
            return httpx.Response(self.failure, json={"error": {"message": "upstream-private-secret"}})
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": i, "embedding": [3.0, 4.0]} for i, _ in enumerate(data["input"])],
                                            "usage": {"prompt_tokens": len(data["input"]), "total_tokens": len(data["input"])}})
        if data.get("stream"):
            events = self.stream_events or [
                {"choices": [{"index": 0, "delta": {"role": "assistant", "content": self.response[:2]}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"content": self.response[2:]}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}},
            ]
            body = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=body)
        return httpx.Response(200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": self.response}, "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}})


def configure_model(client, *, kind="llm", alias="local", **overrides):
    providers = client.get("/api/models/providers").json()
    if providers:
        provider_id = providers[0]["id"]
    else:
        provider = client.post("/api/models/providers", json={'name': 'Test', 'connection': {'base_url': 'http://provider.test/v1', 'api_key': 'provider-private-key'}})
        assert provider.status_code == 200, provider.text
        provider_id = provider.json()["id"]
    payload = {"alias": alias, "name": alias, "kind": kind, "model_ref": "fake" if kind == "llm" else "embed", "external_enabled": True, 'source': {'type': 'provider', 'provider_profile_id': provider_id}, **overrides}
    profile = client.post("/api/models/profiles", json=payload)
    assert profile.status_code == 200, profile.text
    if kind == "llm":
        defaults = client.patch("/api/models/settings", json={"default_model_profile_id": profile.json()["id"]})
        assert defaults.status_code == 200, defaults.text
    return profile.json()
