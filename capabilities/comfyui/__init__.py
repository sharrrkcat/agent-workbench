import base64
import mimetypes
import time
from typing import Any
from urllib.parse import urljoin

import httpx


DEFAULT_CONFIG = {
    "base_url": "http://127.0.0.1:8188",
    "timeout_seconds": 30,
    "poll_interval_seconds": 1.0,
    "max_wait_seconds": 300,
    "verify_ssl": True,
    "default_image_response_mode": "base64",
    "enable_upload": True,
}


class ComfyUIError(ValueError):
    def __init__(self, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail}


class ComfyUIClient:
    def __init__(self, config: dict | None = None, client: httpx.Client | None = None) -> None:
        self.config = _runtime_config({"capability_config": config or {}})
        self.base_url = str(self.config["base_url"]).rstrip("/") + "/"
        self.timeout = float(self.config["timeout_seconds"])
        self._client = client

    def get_json(self, endpoint: str, params: dict | None = None, not_found_code: str | None = None) -> Any:
        response = self._request("GET", endpoint, params=params, not_found_code=not_found_code)
        return self._json(response)

    def post_json(self, endpoint: str, payload: dict | None = None, not_found_code: str | None = None) -> Any:
        response = self._request("POST", endpoint, json=payload or {}, not_found_code=not_found_code)
        if not response.content:
            return {}
        return self._json(response)

    def get_bytes(self, endpoint: str, params: dict | None = None, not_found_code: str | None = None) -> tuple[bytes, str]:
        response = self._request("GET", endpoint, params=params, not_found_code=not_found_code)
        return response.content, _response_mime_type(response, params or {})

    def post_multipart(self, endpoint: str, data: dict, files: dict, not_found_code: str | None = None) -> Any:
        response = self._request("POST", endpoint, data=data, files=files, not_found_code=not_found_code)
        if not response.content:
            return {}
        return self._json(response)

    def _request(self, method: str, endpoint: str, not_found_code: str | None = None, **kwargs) -> httpx.Response:
        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=self.timeout,
            verify=bool(self.config["verify_ssl"]),
            headers={"User-Agent": "agent-workbench/0.1"},
        )
        try:
            response = client.request(method, self._url(endpoint), timeout=self.timeout, **kwargs)
            if response.status_code == 404 and not_found_code:
                raise ComfyUIError(not_found_code, "ComfyUI output or history entry was not found.", {"status_code": 404})
            response.raise_for_status()
            return response
        except ComfyUIError:
            raise
        except httpx.TimeoutException as exc:
            raise ComfyUIError("COMFYUI_TIMEOUT", "ComfyUI request timed out.", {"error": str(exc)}) from exc
        except httpx.ConnectError as exc:
            raise ComfyUIError("COMFYUI_UNREACHABLE", "ComfyUI service is unreachable.", {"error": str(exc)}) from exc
        except httpx.NetworkError as exc:
            raise ComfyUIError("COMFYUI_UNREACHABLE", "ComfyUI network request failed.", {"error": str(exc)}) from exc
        except httpx.HTTPStatusError as exc:
            raise ComfyUIError(
                "COMFYUI_BAD_RESPONSE",
                f"ComfyUI returned HTTP {exc.response.status_code}.",
                {"status_code": exc.response.status_code, "body": _safe_text(exc.response)},
            ) from exc
        except httpx.HTTPError as exc:
            raise ComfyUIError("COMFYUI_UNREACHABLE", "ComfyUI HTTP request failed.", {"error": str(exc)}) from exc
        finally:
            if owns_client:
                client.close()

    def _json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise ComfyUIError(
                "COMFYUI_BAD_RESPONSE",
                "ComfyUI returned a non-JSON response.",
                {"status_code": response.status_code, "body": _safe_text(response)},
            ) from exc

    def _url(self, endpoint: str) -> str:
        return urljoin(self.base_url, endpoint.lstrip("/"))


class CapabilityRuntime:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def test_connection(self, context: dict | None = None) -> dict:
        client = self._client_for(context)
        checks = {
            "queue": _try_json(lambda: client.get_json("/queue")),
            "object_info": _try_json(lambda: client.get_json("/object_info")),
            "system_stats": _try_json(lambda: client.get_json("/system_stats")),
        }
        available = {name: result["ok"] for name, result in checks.items()}
        reachable = any(available.values())
        checked = [f"/{name}" for name in checks]
        if not reachable:
            first_error = next((result["error"] for result in checks.values() if result.get("error")), None)
            return {
                "reachable": False,
                "base_url": client.base_url.rstrip("/"),
                "checked_endpoint": checked[0],
                "checked_endpoints": checked,
                "queue_available": False,
                "object_info_available": False,
                "system_stats_available": False,
                "summary": "ComfyUI is unreachable.",
                "error": first_error,
            }
        object_info = checks["object_info"].get("data") if checks["object_info"]["ok"] else {}
        node_count = len(object_info) if isinstance(object_info, dict) else 0
        return {
            "reachable": True,
            "base_url": client.base_url.rstrip("/"),
            "checked_endpoint": next(f"/{name}" for name, ok in available.items() if ok),
            "checked_endpoints": checked,
            "queue_available": available["queue"],
            "object_info_available": available["object_info"],
            "system_stats_available": available["system_stats"],
            "node_count": node_count,
            "summary": f"ComfyUI is reachable; {node_count} node definitions reported.",
        }

    def get_queue(self, context: dict | None = None) -> dict:
        raw = self._client_for(context).get_json("/queue")
        running = raw.get("queue_running", []) if isinstance(raw, dict) else []
        pending = raw.get("queue_pending", []) if isinstance(raw, dict) else []
        return {
            "running": running,
            "pending": pending,
            "summary": {"running_count": len(running), "pending_count": len(pending)},
            "raw": raw,
        }

    def get_history(self, prompt_id: str | None = None, context: dict | None = None) -> dict:
        endpoint = f"/history/{prompt_id}" if prompt_id else "/history"
        raw = self._client_for(context).get_json(endpoint, not_found_code="COMFYUI_HISTORY_NOT_FOUND")
        entry = _history_entry(raw, prompt_id)
        found = entry is not None if prompt_id else isinstance(raw, dict)
        outputs = normalize_history_outputs(entry if entry is not None else raw)
        return {"prompt_id": prompt_id or "", "raw": raw, "found": found, "outputs": outputs}

    def submit_workflow(
        self,
        workflow: dict | None = None,
        client_id: str | None = None,
        extra_data: dict | None = None,
        context: dict | None = None,
        prompt: dict | None = None,
    ) -> dict:
        prompt_payload = workflow if workflow is not None else prompt
        if not isinstance(prompt_payload, dict) or not prompt_payload:
            raise ComfyUIError(
                "COMFYUI_WORKFLOW_INVALID",
                "Workflow must be a non-empty JSON object.",
                {"received_type": type(prompt_payload).__name__},
            )
        payload: dict[str, Any] = {"prompt": prompt_payload}
        if client_id:
            payload["client_id"] = client_id
        if extra_data is not None:
            if not isinstance(extra_data, dict):
                raise ComfyUIError("COMFYUI_WORKFLOW_INVALID", "extra_data must be an object.")
            payload["extra_data"] = extra_data
        raw = self._client_for(context).post_json("/prompt", payload)
        if not isinstance(raw, dict):
            raise ComfyUIError("COMFYUI_BAD_RESPONSE", "ComfyUI /prompt response was not an object.", {"raw": raw})
        node_errors = raw.get("node_errors") or {}
        prompt_id = raw.get("prompt_id") or ""
        accepted = bool(prompt_id) and not bool(node_errors)
        result = {
            "prompt_id": prompt_id,
            "number": raw.get("number"),
            "node_errors": node_errors,
            "accepted": accepted,
            "raw": raw,
        }
        if not prompt_id:
            result["error"] = ComfyUIError("COMFYUI_PROMPT_REJECTED", "ComfyUI rejected the workflow.", {"raw": raw}).to_dict()
        elif node_errors:
            result["error"] = ComfyUIError(
                "COMFYUI_PROMPT_REJECTED",
                "ComfyUI reported workflow node errors.",
                {"node_errors": node_errors, "raw": raw},
            ).to_dict()
        return result

    def wait_for_prompt(
        self,
        prompt_id: str,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        context: dict | None = None,
    ) -> dict:
        if not prompt_id:
            raise ComfyUIError("COMFYUI_WORKFLOW_INVALID", "prompt_id is required.")
        config = _runtime_config(context)
        timeout = float(timeout_seconds if timeout_seconds is not None else config["max_wait_seconds"])
        interval = float(poll_interval_seconds if poll_interval_seconds is not None else config["poll_interval_seconds"])
        started = time.monotonic()
        last_history: dict | None = None
        while True:
            history = self.get_history(prompt_id, context=context)
            last_history = history
            if history["found"]:
                elapsed = time.monotonic() - started
                return {
                    "prompt_id": prompt_id,
                    "completed": True,
                    "timed_out": False,
                    "history": history,
                    "outputs": history["outputs"],
                    "elapsed_seconds": round(elapsed, 3),
                }
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                raise ComfyUIError(
                    "COMFYUI_TIMEOUT",
                    "Timed out waiting for ComfyUI prompt history.",
                    {
                        "prompt_id": prompt_id,
                        "elapsed_seconds": round(elapsed, 3),
                        "timeout_seconds": timeout,
                        "last_history": last_history,
                    },
                )
            time.sleep(max(0.0, interval))

    def extract_outputs(self, history: dict, context: dict | None = None) -> dict:
        return normalize_history_outputs(history)

    def fetch_image(
        self,
        filename: str,
        subfolder: str = "",
        type: str = "output",
        as_base64: bool | None = None,
        context: dict | None = None,
    ) -> dict:
        if not filename:
            raise ComfyUIError("COMFYUI_OUTPUT_NOT_FOUND", "Image filename is required.")
        config = _runtime_config(context)
        use_base64 = as_base64 if as_base64 is not None else config["default_image_response_mode"] == "base64"
        params = {"filename": filename, "subfolder": subfolder or "", "type": type or "output"}
        content, mime_type = self._client_for(context).get_bytes("/view", params=params, not_found_code="COMFYUI_OUTPUT_NOT_FOUND")
        payload = {
            "filename": filename,
            "subfolder": subfolder or "",
            "type": type or "output",
            "mime_type": mime_type,
            "size_bytes": len(content),
        }
        if use_base64:
            payload["data_base64"] = base64.b64encode(content).decode("ascii")
        else:
            payload["bytes_metadata"] = {"available": True, "encoding": "raw", "size_bytes": len(content)}
        return payload

    def collect_images_for_prompt(self, prompt_id: str, include_binary: bool = False, context: dict | None = None) -> dict:
        history = self.get_history(prompt_id, context=context)
        outputs = history["outputs"]
        images = []
        for image in outputs["images"]:
            item = dict(image)
            if include_binary:
                fetched = self.fetch_image(
                    image["filename"],
                    subfolder=image.get("subfolder", ""),
                    type=image.get("type", "output"),
                    as_base64=True,
                    context=context,
                )
                item.update({key: fetched[key] for key in ("mime_type", "size_bytes", "data_base64")})
            images.append(item)
        return {"prompt_id": prompt_id, "images": images, "summary": {"image_count": len(images)}, "outputs": outputs}

    def interrupt(self, context: dict | None = None) -> dict:
        try:
            raw = self._client_for(context).post_json("/interrupt", {})
            return {"ok": True, "message": "Interrupt requested.", "raw": raw}
        except ComfyUIError as exc:
            return {
                "ok": False,
                "message": "ComfyUI interrupt request failed.",
                "error": ComfyUIError("COMFYUI_INTERRUPT_FAILED", exc.message, exc.detail).to_dict(),
            }

    def upload_image(
        self,
        filename: str,
        data_base64: str | None = None,
        content: bytes | str | None = None,
        overwrite: bool = False,
        type: str = "input",
        subfolder: str = "",
        context: dict | None = None,
    ) -> dict:
        config = _runtime_config(context)
        if not bool(config["enable_upload"]):
            raise ComfyUIError("COMFYUI_UPLOAD_FAILED", "ComfyUI image upload is disabled.")
        image_bytes = _coerce_upload_bytes(data_base64=data_base64, content=content)
        data = {"overwrite": str(bool(overwrite)).lower(), "type": type or "input", "subfolder": subfolder or ""}
        files = {"image": (filename, image_bytes, _guess_mime_type(filename))}
        try:
            raw = self._client_for(context).post_multipart("/upload/image", data=data, files=files)
        except ComfyUIError as exc:
            raise ComfyUIError("COMFYUI_UPLOAD_FAILED", "ComfyUI image upload failed.", exc.detail) from exc
        if not isinstance(raw, dict):
            raise ComfyUIError("COMFYUI_BAD_RESPONSE", "ComfyUI upload response was not an object.", {"raw": raw})
        return {
            "name": raw.get("name") or filename,
            "subfolder": raw.get("subfolder") or subfolder or "",
            "type": raw.get("type") or type or "input",
            "uploaded": True,
            "raw": raw,
        }

    def get_object_info(self, context: dict | None = None) -> dict:
        raw = self._client_for(context).get_json("/object_info")
        if not isinstance(raw, dict):
            raise ComfyUIError("COMFYUI_BAD_RESPONSE", "ComfyUI object_info response was not an object.", {"raw": raw})
        return {"raw": raw, "node_count": len(raw), "keys": sorted(str(key) for key in raw.keys())}

    def _client_for(self, context: dict | None = None) -> ComfyUIClient:
        return ComfyUIClient(_runtime_config(context), self._client)


def get_runtime() -> CapabilityRuntime:
    return CapabilityRuntime()


def normalize_history_outputs(history: dict | None) -> dict:
    entry = _history_entry(history, None) if isinstance(history, dict) else None
    if entry is None:
        entry = history if isinstance(history, dict) else {}
    prompt_nodes = _prompt_nodes(entry)
    outputs = entry.get("outputs", {}) if isinstance(entry, dict) else {}
    images: list[dict] = []
    files: list[dict] = []
    text: list[dict] = []
    if isinstance(outputs, dict):
        for node_id, node_output in outputs.items():
            if not isinstance(node_output, dict):
                continue
            node_label = _node_label(prompt_nodes, str(node_id))
            for image in node_output.get("images") or []:
                if isinstance(image, dict) and image.get("filename"):
                    images.append(_file_ref(image, str(node_id), node_label, "image"))
            for key, values in node_output.items():
                if key in {"images", "text"}:
                    continue
                if isinstance(values, list):
                    for value in values:
                        if isinstance(value, dict) and value.get("filename"):
                            files.append(_file_ref(value, str(node_id), node_label, key))
            for value in node_output.get("text") or []:
                text.append({"node_id": str(node_id), "node_label": node_label, "text": str(value)})
    return {
        "images": images,
        "files": files,
        "text": text,
        "summary": {"image_count": len(images), "file_count": len(files), "text_count": len(text)},
    }


def _runtime_config(context: dict | None) -> dict:
    config = dict(DEFAULT_CONFIG)
    provided = (context or {}).get("capability_config") if isinstance(context, dict) else None
    if isinstance(provided, dict):
        config.update({key: value for key, value in provided.items() if value is not None})
    config["base_url"] = str(config["base_url"] or DEFAULT_CONFIG["base_url"]).rstrip("/")
    return config


def _try_json(fn) -> dict:
    try:
        return {"ok": True, "data": fn()}
    except ComfyUIError as exc:
        return {"ok": False, "error": exc.to_dict()}


def _history_entry(history: dict | None, prompt_id: str | None) -> dict | None:
    if not isinstance(history, dict):
        return None
    if prompt_id:
        entry = history.get(prompt_id)
        return entry if isinstance(entry, dict) else None
    if "outputs" in history:
        return history
    if len(history) == 1:
        only = next(iter(history.values()))
        return only if isinstance(only, dict) else None
    return None


def _prompt_nodes(entry: dict) -> dict:
    prompt = entry.get("prompt") if isinstance(entry, dict) else None
    if isinstance(prompt, list) and len(prompt) >= 3 and isinstance(prompt[2], dict):
        return prompt[2]
    if isinstance(prompt, dict):
        return prompt
    return {}


def _node_label(prompt_nodes: dict, node_id: str) -> str:
    node = prompt_nodes.get(node_id) if isinstance(prompt_nodes, dict) else None
    if not isinstance(node, dict):
        return ""
    meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
    return str(meta.get("title") or node.get("class_type") or "")


def _file_ref(value: dict, node_id: str, node_label: str, kind: str) -> dict:
    filename = str(value.get("filename") or "")
    subfolder = str(value.get("subfolder") or "")
    item_type = str(value.get("type") or "output")
    fmt = _format_from_filename(filename)
    return {
        "filename": filename,
        "subfolder": subfolder,
        "type": item_type,
        "node_id": node_id,
        "node_label": node_label,
        "format": fmt,
        "display_name": "/".join(part for part in [subfolder, filename] if part),
        "kind": kind,
    }


def _format_from_filename(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return suffix


def _safe_text(response: httpx.Response) -> str:
    try:
        return response.text[:500]
    except Exception:
        return ""


def _response_mime_type(response: httpx.Response, params: dict) -> str:
    header = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if header:
        return header
    return _guess_mime_type(str(params.get("filename") or ""))


def _guess_mime_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _coerce_upload_bytes(data_base64: str | None = None, content: bytes | str | None = None) -> bytes:
    if data_base64:
        raw = data_base64.split(",", 1)[1] if data_base64.strip().startswith("data:") and "," in data_base64 else data_base64
        try:
            return base64.b64decode(raw, validate=True)
        except Exception as exc:
            raise ComfyUIError("COMFYUI_UPLOAD_FAILED", "Invalid upload image base64.") from exc
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    raise ComfyUIError("COMFYUI_UPLOAD_FAILED", "Upload image content is required.")
