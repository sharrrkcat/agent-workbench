import base64
import copy
import hashlib
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import yaml


DEFAULT_CONFIG = {
    "base_url": "http://127.0.0.1:8188",
    "timeout_seconds": 30,
    "poll_interval_seconds": 1.0,
    "max_wait_seconds": 300,
    "verify_ssl": True,
    "default_image_response_mode": "base64",
    "enable_upload": True,
    "workflows_dir": "./data/comfyui/workflows",
    "presets_dir": "./data/comfyui/presets",
    "auto_create_missing_presets": True,
    "allow_workflow_file_write": True,
    "allow_preset_file_write": True,
}

SUPPORTED_PARAMETER_TYPES = {"text", "textarea", "integer", "float", "boolean", "enum", "json"}
PRESET_STATUS_VALUES = {"ready", "needs_mapping", "disabled"}
REPO_ROOT = Path(__file__).resolve().parents[2]


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

    def get_prompt_status(self, prompt_id: str, context: dict | None = None) -> dict:
        if not prompt_id:
            raise ComfyUIError("COMFYUI_WORKFLOW_INVALID", "prompt_id is required.")
        client = self._client_for(context)
        history_raw: Any = {}
        history_reachable = True
        try:
            history_raw = client.get_json(f"/history/{prompt_id}", not_found_code="COMFYUI_HISTORY_NOT_FOUND")
        except ComfyUIError as exc:
            if exc.code != "COMFYUI_HISTORY_NOT_FOUND":
                raise
            history_raw = {}

        if _history_entry(history_raw, prompt_id) is not None:
            return normalize_prompt_status(history_raw, {}, prompt_id, history_reachable=history_reachable)
        queue_raw = client.get_json("/queue")
        return normalize_prompt_status(history_raw, queue_raw, prompt_id, history_reachable=history_reachable)

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
        """Blocking convenience helper.

        Script Agents that need live progress or cancellation should use
        submit_workflow + get_prompt_status in their own async loop.
        """
        if not prompt_id:
            raise ComfyUIError("COMFYUI_WORKFLOW_INVALID", "prompt_id is required.")
        config = _runtime_config(context)
        timeout = float(timeout_seconds if timeout_seconds is not None else config["max_wait_seconds"])
        interval = float(poll_interval_seconds if poll_interval_seconds is not None else config["poll_interval_seconds"])
        started = time.monotonic()
        last_status: dict | None = None
        while True:
            status = self.get_prompt_status(prompt_id, context=context)
            last_status = status
            if status["completed"]:
                elapsed = time.monotonic() - started
                return {
                    "prompt_id": prompt_id,
                    "completed": True,
                    "timed_out": False,
                    "status": status["status"],
                    "outputs": status["outputs"],
                    "elapsed_seconds": round(elapsed, 3),
                    "history": status["raw"].get("history"),
                    "raw": status["raw"],
                }
            if status["failed"]:
                raise ComfyUIError(
                    "COMFYUI_PROMPT_FAILED",
                    "ComfyUI prompt execution failed.",
                    {"prompt_id": prompt_id, "status": status["status"], "error": status.get("error"), "raw": status.get("raw")},
                )
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                raise ComfyUIError(
                    "COMFYUI_TIMEOUT",
                    "Timed out waiting for ComfyUI prompt history.",
                    {
                        "prompt_id": prompt_id,
                        "elapsed_seconds": round(elapsed, 3),
                        "timeout_seconds": timeout,
                        "last_status": last_status,
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

    def free_memory(self, unload_models: bool = True, free_memory: bool = True, context: dict | None = None) -> dict:
        requested = {"unload_models": bool(unload_models), "free_memory": bool(free_memory)}
        response = None
        try:
            response = self._client_for(context)._request("POST", "/free", json=requested)
            if response.status_code >= 400:
                raise ComfyUIError(
                    "COMFYUI_BAD_RESPONSE",
                    f"ComfyUI returned HTTP {response.status_code}.",
                    {"status_code": response.status_code, "body": _safe_text(response)},
                )
            raw = {} if not response.content else response.json()
            return {
                "ok": True,
                "requested": requested,
                "status_code": response.status_code,
                "response": raw,
            }
        except ComfyUIError as exc:
            return {
                "ok": False,
                "requested": requested,
                "status_code": exc.detail.get("status_code"),
                "error": ComfyUIError("COMFYUI_FREE_MEMORY_FAILED", exc.message, exc.detail).to_dict(),
            }
        except ValueError as exc:
            return {
                "ok": False,
                "requested": requested,
                "status_code": response.status_code if response is not None else None,
                "error": ComfyUIError("COMFYUI_FREE_MEMORY_FAILED", "ComfyUI /free returned a non-JSON response.", {"error": str(exc)}).to_dict(),
            }

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

    def scan_workflow_library(self, context: dict | None = None) -> dict:
        config = _runtime_config(context)
        workflows_dir = _resolve_asset_dir(config["workflows_dir"])
        presets_dir = _resolve_asset_dir(config["presets_dir"])
        result = {
            "workflows_dir": str(workflows_dir),
            "presets_dir": str(presets_dir),
            "config": {
                "poll_interval_seconds": float(config["poll_interval_seconds"]),
                "max_wait_seconds": float(config["max_wait_seconds"]),
                "auto_create_missing_presets": bool(config["auto_create_missing_presets"]),
                "allow_preset_file_write": bool(config["allow_preset_file_write"]),
            },
            "workflows": [],
            "duplicates": [],
            "presets": [],
            "missing_preset_workflows": [],
            "created_draft_presets": [],
            "skipped_draft_presets": [],
            "errors": [],
            "warnings": [],
        }
        _ensure_asset_dir(workflows_dir, bool(config["allow_workflow_file_write"]), result, "workflows_dir")
        _ensure_asset_dir(presets_dir, bool(config["allow_preset_file_write"]), result, "presets_dir")

        workflows = _scan_workflows(workflows_dir)
        result["workflows"] = workflows
        by_hash: dict[str, list[str]] = {}
        for workflow in workflows:
            if workflow.get("valid") and workflow.get("hash"):
                by_hash.setdefault(workflow["hash"], []).append(workflow["file_name"])
        result["duplicates"] = [
            {"hash": hash_value, "file_names": names}
            for hash_value, names in sorted(by_hash.items())
            if len(names) > 1
        ]
        for duplicate in result["duplicates"]:
            duplicate_of = duplicate["file_names"][0]
            for workflow in workflows:
                if workflow["file_name"] in duplicate["file_names"][1:]:
                    workflow["duplicate_of"] = duplicate_of
                    workflow["warnings"].append("duplicate workflow content")

        presets = _scan_presets(presets_dir, workflows_dir, workflows)
        result["presets"] = presets
        referenced_hashes = {
            preset.get("workflow", {}).get("hash")
            for preset in presets
            if isinstance(preset.get("workflow"), dict) and preset.get("workflow", {}).get("hash")
        }
        for loaded in _load_preset_files(presets_dir):
            data = loaded.get("data") if isinstance(loaded, dict) else {}
            workflow_ref = data.get("workflow") if isinstance(data, dict) and isinstance(data.get("workflow"), dict) else {}
            if workflow_ref.get("hash"):
                referenced_hashes.add(workflow_ref["hash"])
        for workflow in workflows:
            reason = None
            if not workflow.get("valid"):
                reason = "unsupported_gui_format" if workflow.get("format") == "unsupported_gui_format" else "invalid_workflow"
                workflow["status"] = reason
                workflow["skipped_reason"] = reason
                continue
            if workflow.get("hash") in referenced_hashes:
                reason = "preset_already_exists_for_workflow"
                workflow["status"] = "mapped"
                workflow["skipped_reason"] = reason
                result["skipped_draft_presets"].append({"workflow_file_name": workflow["file_name"], "reason": reason})
                continue

            workflow["status"] = "missing_preset"
            workflow["skipped_reason"] = None
            missing_item = {"workflow_file_name": workflow["file_name"], "hash": workflow.get("hash"), "reason": "missing_preset"}
            result["missing_preset_workflows"].append(missing_item)

            if not bool(config["auto_create_missing_presets"]):
                reason = "auto_create_disabled"
            elif not bool(config["allow_preset_file_write"]):
                reason = "preset_write_disabled"
            elif not presets_dir.is_dir():
                reason = "directory_not_writable"
            else:
                draft = _create_draft_preset(presets_dir, workflow, presets)
                if draft:
                    result["created_draft_presets"].append(draft)
                    continue
                reason = "preset_file_exists"
            result["skipped_draft_presets"].append({"workflow_file_name": workflow["file_name"], "reason": reason})
        if result["created_draft_presets"]:
            result["presets"] = _scan_presets(presets_dir, workflows_dir, workflows)
        return result

    def list_workflows(self, context: dict | None = None) -> dict:
        scan = self.scan_workflow_library(context=context)
        return {
            "workflows_dir": scan["workflows_dir"],
            "workflows": scan["workflows"],
            "duplicates": scan["duplicates"],
            "summary": {"workflow_count": len(scan["workflows"])},
        }

    def list_presets(self, context: dict | None = None) -> dict:
        scan = self.scan_workflow_library(context=context)
        return {
            "presets_dir": scan["presets_dir"],
            "presets": scan["presets"],
            "summary": {"preset_count": len(scan["presets"])},
        }

    def validate_preset(
        self,
        preset_id: str | None = None,
        file_name: str | None = None,
        preset: dict | None = None,
        context: dict | None = None,
    ) -> dict:
        config = _runtime_config(context)
        workflows_dir = _resolve_asset_dir(config["workflows_dir"])
        presets_dir = _resolve_asset_dir(config["presets_dir"])
        workflows = _scan_workflows(workflows_dir)
        presets = _load_preset_files(presets_dir)
        if preset is None:
            loaded = _find_loaded_preset(presets, preset_id=preset_id, file_name=file_name)
            if loaded is None:
                return _preset_validation_result(preset_id or "", None, workflows_dir, workflows, presets, ["Preset was not found."], [])
            preset = loaded["data"]
            file_name = loaded["file_name"]
        return _validate_preset(preset, workflows_dir, workflows, presets, source_file_name=file_name)

    def load_preset(self, preset_id: str | None = None, file_name: str | None = None, context: dict | None = None) -> dict:
        config = _runtime_config(context)
        workflows_dir = _resolve_asset_dir(config["workflows_dir"])
        presets_dir = _resolve_asset_dir(config["presets_dir"])
        workflows = _scan_workflows(workflows_dir)
        presets = _load_preset_files(presets_dir)
        loaded = _find_loaded_preset(presets, preset_id=preset_id, file_name=file_name)
        if loaded is None:
            return {"found": False, "preset": None, "validation": _preset_validation_result(preset_id or "", None, workflows_dir, workflows, presets, ["Preset was not found."], [])}
        validation = _validate_preset(loaded["data"], workflows_dir, workflows, presets, source_file_name=loaded["file_name"])
        return {"found": True, "file_name": loaded["file_name"], "preset": loaded["data"], "validation": validation}

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


def normalize_prompt_status(
    history_payload: Any,
    queue_payload: Any,
    prompt_id: str,
    history_reachable: bool = True,
) -> dict:
    entry = _history_entry(history_payload, prompt_id)
    history_found = entry is not None
    queue_info = _queue_prompt_info(queue_payload, prompt_id)
    queue_complete = isinstance(queue_payload, dict)
    outputs = normalize_history_outputs(entry if entry is not None else {})
    error = _prompt_error(entry) if entry is not None else None

    if history_found:
        failed = bool(error)
        status = "failed" if failed else "completed"
        return {
            "prompt_id": prompt_id,
            "status": status,
            "completed": not failed,
            "failed": failed,
            "queue_position": None,
            "queue_state": "absent",
            "history_found": True,
            "outputs": outputs,
            "error": error,
            "raw": {"history": history_payload, "queue": queue_payload},
        }

    if queue_info["state"] == "running":
        status = "running"
    elif queue_info["state"] == "pending":
        status = "queued"
    elif history_reachable and queue_complete:
        status = "not_found"
    else:
        status = "unknown"

    return {
        "prompt_id": prompt_id,
        "status": status,
        "completed": False,
        "failed": False,
        "queue_position": queue_info["position"],
        "queue_state": queue_info["state"] if queue_info["state"] != "missing" else ("absent" if status == "not_found" else "unknown"),
        "history_found": False,
        "outputs": outputs,
        "error": None,
        "raw": {"history": history_payload, "queue": queue_payload},
    }


def _runtime_config(context: dict | None) -> dict:
    config = dict(DEFAULT_CONFIG)
    provided = (context or {}).get("capability_config") if isinstance(context, dict) else None
    if isinstance(provided, dict):
        config.update({key: value for key, value in provided.items() if value is not None})
    config["base_url"] = str(config["base_url"] or DEFAULT_CONFIG["base_url"]).rstrip("/")
    return config


def _resolve_asset_dir(value: str) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def _ensure_asset_dir(path: Path, allow_write: bool, result: dict, label: str) -> None:
    if path.exists():
        if not path.is_dir():
            result["errors"].append(f"{label} is not a directory: {path}")
        return
    if not allow_write:
        result["warnings"].append(f"{label} does not exist and write is disabled: {path}")
        return
    path.mkdir(parents=True, exist_ok=True)


def _is_safe_basename(file_name: Any) -> bool:
    if not isinstance(file_name, str) or not file_name.strip():
        return False
    name = file_name.strip()
    return name == os.path.basename(name) and not os.path.isabs(name) and "/" not in name and "\\" not in name and ".." not in Path(name).parts


def _workflow_hash(workflow: dict) -> str:
    canonical = json.dumps(workflow, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scan_workflows(workflows_dir: Path) -> list[dict]:
    if not workflows_dir.is_dir():
        return []
    return [_inspect_workflow_file(path) for path in sorted(workflows_dir.glob("*.json"))]


def _inspect_workflow_file(path: Path) -> dict:
    item = {
        "file_name": path.name,
        "hash": "",
        "valid": False,
        "format": "unknown",
        "node_count": 0,
        "class_types": [],
        "duplicate_of": None,
        "errors": [],
        "warnings": [],
    }
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        item["errors"].append(f"Invalid JSON: {exc}")
        return item
    if isinstance(workflow, dict) and {"nodes", "links", "widgets_values"}.intersection(workflow.keys()):
        item["format"] = "unsupported_gui_format"
        item["errors"].append("GUI-format workflow is unsupported; export an API-format workflow JSON file.")
        return item
    if not isinstance(workflow, dict) or not workflow:
        item["errors"].append("Workflow must be a non-empty top-level object.")
        return item
    nodes = [value for value in workflow.values() if isinstance(value, dict)]
    if not nodes or not any("class_type" in node or "inputs" in node for node in nodes):
        item["errors"].append("Workflow does not look like ComfyUI API format.")
        return item
    item["valid"] = True
    item["format"] = "api"
    item["node_count"] = len(nodes)
    item["class_types"] = sorted({str(node.get("class_type")) for node in nodes if node.get("class_type")})
    item["hash"] = _workflow_hash(workflow)
    return item


def _load_workflow(workflows_dir: Path, file_name: str) -> tuple[dict | None, dict | None]:
    if not _is_safe_basename(file_name):
        return None, {"valid": False, "errors": ["workflow.file_name must be a basename."]}
    path = workflows_dir / file_name
    if not path.is_file():
        return None, {"valid": False, "errors": ["Workflow file does not exist."]}
    inspected = _inspect_workflow_file(path)
    if not inspected["valid"]:
        return None, inspected
    return json.loads(path.read_text(encoding="utf-8")), inspected


def _load_preset_files(presets_dir: Path) -> list[dict]:
    if not presets_dir.is_dir():
        return []
    loaded = []
    for path in sorted([*presets_dir.glob("*.yaml"), *presets_dir.glob("*.yml")]):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            data = {"id": "", "_load_error": str(exc)}
        loaded.append({"file_name": path.name, "data": data})
    return loaded


def _scan_presets(presets_dir: Path, workflows_dir: Path, workflows: list[dict]) -> list[dict]:
    loaded = _load_preset_files(presets_dir)
    return [_validate_preset(item["data"], workflows_dir, workflows, loaded, source_file_name=item["file_name"]) for item in loaded]


def _find_loaded_preset(presets: list[dict], preset_id: str | None = None, file_name: str | None = None) -> dict | None:
    for item in presets:
        data = item.get("data") if isinstance(item, dict) else {}
        if file_name and item.get("file_name") == file_name:
            return item
        if preset_id and isinstance(data, dict) and data.get("id") == preset_id:
            return item
    return None


def _validate_preset(
    preset: dict | None,
    workflows_dir: Path,
    workflows: list[dict],
    loaded_presets: list[dict],
    source_file_name: str | None = None,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(preset, dict):
        return _preset_validation_result("", None, workflows_dir, workflows, loaded_presets, ["Preset must be a YAML object."], warnings, source_file_name)
    if preset.get("_load_error"):
        errors.append(f"Preset YAML could not be read: {preset['_load_error']}")
    known = {"id", "name", "description", "status", "workflow", "parameters", "output", "ui"}
    for key in sorted(set(preset) - known - {"_load_error"}):
        warnings.append(f"Unknown preset field: {key}")
    preset_id = str(preset.get("id") or "")
    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", preset_id):
        errors.append("Preset id is required and must be lowercase slug-like text.")
    ids = [item.get("data", {}).get("id") for item in loaded_presets if isinstance(item.get("data"), dict)]
    if preset_id and ids.count(preset_id) > 1:
        errors.append(f"Preset id is not unique: {preset_id}")
    if not preset.get("name"):
        errors.append("Preset name is required.")
    status = str(preset.get("status") or "ready")
    if status not in PRESET_STATUS_VALUES:
        errors.append(f"Unsupported preset status: {status}")
    ui = preset.get("ui") if "ui" in preset else None
    if ui is not None:
        if not isinstance(ui, dict):
            errors.append("ui must be an object.")
            ui = {}
        else:
            for key in sorted(set(ui) - {"sections"}):
                if key == "order":
                    errors.append("ui.order is not supported; reorder parameters instead.")
                else:
                    warnings.append(f"Unknown ui field: {key}")
            if "sections" in ui:
                sections = ui.get("sections")
                if not isinstance(sections, list):
                    errors.append("ui.sections must be an array.")
                else:
                    for index, section in enumerate(sections):
                        if not isinstance(section, dict):
                            errors.append(f"ui.sections[{index}] must be an object.")
                            continue
                        for key in sorted(set(section) - {"key", "title"}):
                            warnings.append(f"Unknown ui.sections[{index}] field: {key}")
                        if not isinstance(section.get("key"), str) or not section.get("key", "").strip():
                            errors.append(f"ui.sections[{index}].key is required.")
                        if "title" in section and section.get("title") is not None and not isinstance(section.get("title"), str):
                            errors.append(f"ui.sections[{index}].title must be a string.")
    workflow_ref = preset.get("workflow") if isinstance(preset.get("workflow"), dict) else {}
    workflow_file = workflow_ref.get("file_name")
    if not _is_safe_basename(workflow_file):
        errors.append("workflow.file_name must be a basename.")
        workflow_info = {"file_name": workflow_file or "", "exists": False, "hash": "", "hash_matches": False}
        workflow = None
        inspected = None
    else:
        workflow, inspected = _load_workflow(workflows_dir, workflow_file)
        workflow_hash = inspected.get("hash") if inspected else ""
        workflow_info = {
            "file_name": workflow_file,
            "exists": bool((workflows_dir / workflow_file).is_file()),
            "hash": workflow_hash or "",
            "hash_matches": True,
        }
        if inspected and not inspected.get("valid"):
            errors.extend(inspected.get("errors") or ["Workflow is invalid."])
        declared_hash = workflow_ref.get("hash")
        if declared_hash and workflow_hash and declared_hash != workflow_hash:
            workflow_info["hash_matches"] = False
            warnings.append("workflow.hash does not match the current workflow file canonical hash.")
    parameters = preset.get("parameters", [])
    if parameters is None and status == "needs_mapping":
        parameters = []
    if not isinstance(parameters, list):
        errors.append("parameters must be an array.")
        parameters = []
    names = []
    for parameter in parameters:
        if not isinstance(parameter, dict):
            errors.append("Each parameter must be an object.")
            continue
        if "id" in parameter and "name" not in parameter:
            errors.append("Use parameter.name instead of parameter.id.")
        if "target" in parameter or "input" in parameter:
            errors.append("Use mapping.node_id and mapping.input_path.")
        p_name = str(parameter.get("name") or "")
        if not p_name:
            errors.append("Parameter name is required.")
        names.append(p_name)
        p_type = parameter.get("type")
        if p_type not in SUPPORTED_PARAMETER_TYPES:
            errors.append(f"Unsupported parameter type for {p_name}: {p_type}")
        if p_type == "enum" and not parameter.get("options"):
            errors.append(f"Enum parameter '{p_name}' requires non-empty options.")
        if "default" in parameter and p_type in SUPPORTED_PARAMETER_TYPES and not _default_matches_type(parameter["default"], p_type):
            errors.append(f"Default value type does not match parameter type: {p_name}")
        if ("minimum" in parameter or "maximum" in parameter) and p_type not in {"integer", "float"}:
            errors.append(f"minimum/maximum only apply to numeric parameters: {p_name}")
        _validate_parameter_ui(parameter.get("ui"), p_name, errors, warnings)
        mapping = parameter.get("mapping")
        if status == "ready" and parameter.get("required") and not mapping:
            errors.append(f"Ready preset required parameter is missing mapping: {p_name}")
        if mapping:
            _validate_mapping(mapping, workflow, p_name, errors)
    duplicates = sorted({name for name in names if name and names.count(name) > 1})
    for name in duplicates:
        errors.append(f"Parameter name is not unique: {name}")
    output = preset.get("output") if isinstance(preset.get("output"), dict) else {}
    for key in sorted(set(output) - {"images"}):
        warnings.append(f"Unknown output field: {key}")
    if output.get("images", "all") != "all":
        errors.append("Only output.images=all is supported.")
    return _preset_validation_result(preset_id, preset, workflows_dir, workflows, loaded_presets, errors, warnings, source_file_name, status, workflow_info, len(parameters))


def _validate_parameter_ui(ui: Any, parameter_name: str, errors: list[str], warnings: list[str]) -> None:
    if ui is None:
        return
    label = parameter_name or "<unnamed>"
    if not isinstance(ui, dict):
        errors.append(f"parameter.ui must be an object: {label}")
        return
    for key in sorted(set(ui) - {"section", "span"}):
        if key == "order":
            errors.append(f"parameter.ui.order is not supported for {label}; reorder parameters instead.")
        else:
            warnings.append(f"Unknown parameter.ui field for {label}: {key}")
    section = ui.get("section")
    if section is not None and (not isinstance(section, str) or not section.strip()):
        errors.append(f"parameter.ui.section must be a non-empty string: {label}")
    span = ui.get("span")
    if span is not None and (not isinstance(span, int) or isinstance(span, bool) or span < 1 or span > 12):
        errors.append(f"parameter.ui.span must be an integer from 1 to 12: {label}")


def _preset_validation_result(
    preset_id: str,
    preset: dict | None,
    workflows_dir: Path,
    workflows: list[dict],
    loaded_presets: list[dict],
    errors: list[str],
    warnings: list[str],
    source_file_name: str | None = None,
    status: str | None = None,
    workflow_info: dict | None = None,
    parameter_count: int = 0,
) -> dict:
    workflow_ref = preset.get("workflow") if isinstance(preset, dict) and isinstance(preset.get("workflow"), dict) else {}
    return {
        "file_name": source_file_name or "",
        "preset_id": preset_id,
        "id": preset_id,
        "name": preset.get("name", "") if isinstance(preset, dict) else "",
        "valid": not errors,
        "status": status or (str(preset.get("status") or "ready") if isinstance(preset, dict) else "invalid"),
        "workflow": workflow_info or {
            "file_name": workflow_ref.get("file_name", ""),
            "exists": False,
            "hash": "",
            "hash_matches": False,
        },
        "parameter_count": parameter_count,
        "parameters": list(preset.get("parameters") or []) if isinstance(preset, dict) else [],
        "ui": copy.deepcopy(preset.get("ui") or {}) if isinstance(preset, dict) and isinstance(preset.get("ui"), dict) else {},
        "errors": errors,
        "warnings": warnings,
    }


def _validate_mapping(mapping: dict, workflow: dict | None, parameter_name: str, errors: list[str]) -> None:
    if not isinstance(mapping, dict):
        errors.append(f"mapping must be an object: {parameter_name}")
        return
    node_id = str(mapping.get("node_id") or "")
    input_path = mapping.get("input_path")
    if not node_id or not isinstance(input_path, list) or not input_path:
        errors.append(f"mapping requires node_id and input_path: {parameter_name}")
        return
    if not isinstance(workflow, dict):
        return
    if node_id not in workflow:
        errors.append(f"mapping.node_id does not exist for {parameter_name}: {node_id}")
        return
    current: Any = workflow[node_id]
    for segment in input_path:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            errors.append(f"mapping.input_path cannot be located for {parameter_name}: {input_path}")
            return


def _default_matches_type(value: Any, field_type: str) -> bool:
    if field_type in {"text", "textarea"}:
        return isinstance(value, str)
    if field_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "enum":
        return isinstance(value, str)
    if field_type == "json":
        return isinstance(value, (dict, list))
    return False


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "workflow"


def _create_draft_preset(presets_dir: Path, workflow: dict, existing_presets: list[dict]) -> dict | None:
    stem = Path(workflow["file_name"]).stem
    if stem.endswith(".workflow"):
        stem = stem[: -len(".workflow")]
    base_id = "auto_" + _slug(stem)
    existing_ids = {preset.get("id") for preset in existing_presets}
    preset_id = base_id
    if preset_id in existing_ids:
        preset_id = f"{base_id}_{workflow['hash'].split(':', 1)[1][:8]}"
    file_name = preset_id + ".yaml"
    path = presets_dir / file_name
    if path.exists():
        return None
    draft = {
        "id": preset_id,
        "name": f"{stem} (Unmapped)",
        "status": "needs_mapping",
        "workflow": {"file_name": workflow["file_name"], "hash": workflow["hash"]},
        "parameters": [],
        "output": {"images": "all"},
    }
    path.write_text(yaml.safe_dump(draft, sort_keys=False), encoding="utf-8")
    return {"id": preset_id, "file_name": file_name, "workflow_file_name": workflow["file_name"]}


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


def _queue_prompt_info(queue_payload: Any, prompt_id: str) -> dict:
    if not isinstance(queue_payload, dict):
        return {"state": "missing", "position": None}
    for entry in queue_payload.get("queue_running") or []:
        if _queue_entry_prompt_id(entry) == prompt_id:
            return {"state": "running", "position": None}
    for index, entry in enumerate(queue_payload.get("queue_pending") or []):
        if _queue_entry_prompt_id(entry) == prompt_id:
            return {"state": "pending", "position": index}
    return {"state": "missing", "position": None}


def _queue_entry_prompt_id(entry: Any) -> str:
    if isinstance(entry, dict):
        for key in ("prompt_id", "id"):
            if entry.get(key):
                return str(entry[key])
        prompt = entry.get("prompt")
        if isinstance(prompt, dict) and prompt.get("prompt_id"):
            return str(prompt["prompt_id"])
    if isinstance(entry, (list, tuple)):
        for value in entry:
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                nested = _queue_entry_prompt_id(value)
                if nested:
                    return nested
    return ""


def _prompt_error(entry: Any) -> dict | None:
    if not isinstance(entry, dict):
        return None
    candidates = []
    status = entry.get("status")
    candidates.append(entry)
    if isinstance(status, dict):
        candidates.append(status)
    for candidate in candidates:
        status_value = str(candidate.get("status_str") or candidate.get("status") or "").lower()
        completed = candidate.get("completed")
        has_error = any(candidate.get(key) for key in ("error", "exception_message", "node_errors"))
        if "fail" in status_value or "error" in status_value or completed is False and has_error or has_error:
            return _normalized_prompt_error(candidate)
    messages = entry.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if _message_indicates_failure(message):
                return _normalized_prompt_error({"messages": messages})
    return None


def _message_indicates_failure(message: Any) -> bool:
    if isinstance(message, str):
        value = message.lower()
        return "error" in value or "fail" in value or "exception" in value
    if isinstance(message, dict):
        return any(str(message.get(key) or "").lower() in {"execution_error", "error", "failed"} for key in ("type", "event"))
    if isinstance(message, (list, tuple)):
        return any(_message_indicates_failure(item) for item in message)
    return False


def _normalized_prompt_error(source: dict) -> dict:
    message = (
        source.get("exception_message")
        or source.get("error")
        or source.get("status_str")
        or source.get("status")
        or "ComfyUI prompt failed."
    )
    if isinstance(message, dict):
        message = message.get("message") or message.get("error") or "ComfyUI prompt failed."
    detail = {
        key: source.get(key)
        for key in ("status", "status_str", "completed", "error", "exception_message", "node_errors", "messages")
        if source.get(key) is not None
    }
    return {"message": str(message)[:500], "detail": detail}


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
