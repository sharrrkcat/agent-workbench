import os
from typing import Any, Dict, List, Optional

import httpx


class CapabilityRuntime:
    def generate(
        self,
        prompt: str,
        model_config: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> str:
        return self.chat(
            messages=[{"role": "user", "content": prompt}],
            model_config=model_config,
            stream=stream,
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        model_config: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> str:
        config = _resolve_config(model_config or {})
        headers = {}
        if config.get("api_key"):
            headers["Authorization"] = f"Bearer {config['api_key']}"

        payload = {
            "model": config["model"],
            "messages": messages,
            "stream": stream,
        }
        with httpx.Client(timeout=float(config.get("timeout", 60))) as client:
            response = client.post(
                f"{config['base_url'].rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return message.get("content") or ""

    def unload(self, model_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "success": False,
            "unsupported": True,
            "message": "OpenAI-compatible unload is not supported by this runtime.",
        }

    def list_models(self, model_config: Optional[Dict[str, Any]] = None) -> List[str]:
        config = _resolve_config(model_config or {}, require_model=False)
        headers = {}
        if config.get("api_key"):
            headers["Authorization"] = f"Bearer {config['api_key']}"

        with httpx.Client(timeout=float(config.get("timeout", 60))) as client:
            response = client.get(f"{config['base_url'].rstrip('/')}/models", headers=headers)
            response.raise_for_status()
            data = response.json()

        models = data.get("data") or []
        return [item.get("id", "") for item in models if isinstance(item, dict) and item.get("id")]


def _resolve_config(model_config: Dict[str, Any], require_model: bool = True) -> Dict[str, Any]:
    base_url = os.getenv("AGENT_WORKBENCH_LLM_BASE_URL") or model_config.get("base_url") or "http://localhost:1234/v1"
    model = os.getenv("AGENT_WORKBENCH_LLM_MODEL") or model_config.get("model")
    api_key = os.getenv("AGENT_WORKBENCH_LLM_API_KEY") or model_config.get("api_key") or ""
    timeout = model_config.get("timeout") or 60

    if require_model and not model:
        raise ValueError("LLM model is required by manifest or AGENT_WORKBENCH_LLM_MODEL.")

    return {
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "timeout": timeout,
    }
