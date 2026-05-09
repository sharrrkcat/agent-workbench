import base64
from pathlib import Path

import yaml

import httpx
import pytest

from capabilities.comfyui import CapabilityRuntime, ComfyUIError


PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"


def runtime_with(handler) -> CapabilityRuntime:
    return CapabilityRuntime(client=httpx.Client(transport=httpx.MockTransport(handler)))


def sample_history(prompt_id: str = "prompt-1") -> dict:
    return {
        prompt_id: {
            "prompt": [
                1,
                prompt_id,
                {
                    "9": {
                        "class_type": "SaveImage",
                        "_meta": {"title": "Final image"},
                    }
                },
                {},
            ],
            "outputs": {
                "9": {
                    "images": [
                        {
                            "filename": "Workbench_00001_.png",
                            "subfolder": "",
                            "type": "output",
                        }
                    ],
                    "text": ["done"],
                }
            },
        }
    }


def test_connection_success_reports_endpoint_availability() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []}, request=request)
        if request.url.path == "/object_info":
            return httpx.Response(200, json={"KSampler": {}, "SaveImage": {}}, request=request)
        if request.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {}}, request=request)
        return httpx.Response(404, request=request)

    result = runtime_with(handler).test_connection()

    assert result["reachable"] is True
    assert result["queue_available"] is True
    assert result["object_info_available"] is True
    assert result["system_stats_available"] is True
    assert result["node_count"] == 2


def test_connection_unreachable_returns_structured_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = runtime_with(handler).test_connection()

    assert result["reachable"] is False
    assert result["error"]["code"] == "COMFYUI_UNREACHABLE"
    assert "unreachable" in result["summary"]


def test_submit_workflow_success_posts_prompt_payload() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["json"] = request.read()
        return httpx.Response(200, json={"prompt_id": "abc", "number": 7, "node_errors": {}}, request=request)

    result = runtime_with(handler).submit_workflow({"1": {"class_type": "CheckpointLoaderSimple"}}, client_id="client-1")

    assert seen["path"] == "/prompt"
    assert b'"client_id":"client-1"' in seen["json"].replace(b" ", b"")
    assert result == {
        "prompt_id": "abc",
        "number": 7,
        "node_errors": {},
        "accepted": True,
        "raw": {"prompt_id": "abc", "number": 7, "node_errors": {}},
    }


def test_submit_workflow_rejects_invalid_workflow_locally() -> None:
    runtime = CapabilityRuntime()

    with pytest.raises(ComfyUIError) as exc:
        runtime.submit_workflow([])

    assert exc.value.code == "COMFYUI_WORKFLOW_INVALID"


def test_submit_workflow_preserves_node_errors_as_rejected_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"prompt_id": "abc", "number": 1, "node_errors": {"3": "bad node"}}, request=request)

    result = runtime_with(handler).submit_workflow({"3": {"class_type": "BadNode"}})

    assert result["accepted"] is False
    assert result["node_errors"] == {"3": "bad node"}
    assert result["error"]["code"] == "COMFYUI_PROMPT_REJECTED"


def test_get_queue_normalizes_running_and_pending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"queue_running": [["run"]], "queue_pending": [["wait"]]}, request=request)

    result = runtime_with(handler).get_queue()

    assert result["running"] == [["run"]]
    assert result["pending"] == [["wait"]]
    assert result["summary"] == {"running_count": 1, "pending_count": 1}


def test_get_history_success_includes_normalized_outputs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/history/prompt-1"
        return httpx.Response(200, json=sample_history(), request=request)

    result = runtime_with(handler).get_history("prompt-1")

    assert result["found"] is True
    assert result["outputs"]["summary"] == {"image_count": 1, "file_count": 0, "text_count": 1}
    assert result["outputs"]["images"][0]["node_label"] == "Final image"


def test_get_history_missing_prompt_returns_not_found_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    result = runtime_with(handler).get_history("missing")

    assert result["prompt_id"] == "missing"
    assert result["found"] is False
    assert result["outputs"]["summary"]["image_count"] == 0


def test_get_prompt_status_completed_includes_outputs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/history/prompt-1"
        return httpx.Response(200, json=sample_history(), request=request)

    result = runtime_with(handler).get_prompt_status("prompt-1")

    assert result["status"] == "completed"
    assert result["completed"] is True
    assert result["failed"] is False
    assert result["history_found"] is True
    assert result["outputs"]["summary"]["image_count"] == 1


def test_get_prompt_status_failed_normalizes_history_error() -> None:
    history = sample_history()
    history["prompt-1"]["status"] = {"status_str": "error", "completed": False}
    history["prompt-1"]["exception_message"] = "KSampler failed"
    history["prompt-1"]["node_errors"] = {"9": "bad input"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=history, request=request)

    result = runtime_with(handler).get_prompt_status("prompt-1")

    assert result["status"] == "failed"
    assert result["completed"] is False
    assert result["failed"] is True
    assert result["error"]["message"] == "KSampler failed"
    assert result["error"]["detail"]["node_errors"] == {"9": "bad input"}


def test_get_prompt_status_running_uses_queue_when_history_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/history"):
            return httpx.Response(200, json={}, request=request)
        return httpx.Response(200, json={"queue_running": [[3, "prompt-1", {}]], "queue_pending": []}, request=request)

    result = runtime_with(handler).get_prompt_status("prompt-1")

    assert result["status"] == "running"
    assert result["queue_state"] == "running"
    assert result["history_found"] is False


def test_get_prompt_status_queued_infers_queue_position() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/history"):
            return httpx.Response(200, json={}, request=request)
        return httpx.Response(
            200,
            json={"queue_running": [], "queue_pending": [[1, "other", {}], [2, "prompt-1", {}]]},
            request=request,
        )

    result = runtime_with(handler).get_prompt_status("prompt-1")

    assert result["status"] == "queued"
    assert result["queue_state"] == "pending"
    assert result["queue_position"] == 1


def test_get_prompt_status_not_found_when_history_and_queue_are_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/history"):
            return httpx.Response(200, json={}, request=request)
        return httpx.Response(200, json={"queue_running": [], "queue_pending": []}, request=request)

    result = runtime_with(handler).get_prompt_status("missing")

    assert result["status"] == "not_found"
    assert result["queue_state"] == "absent"
    assert result["completed"] is False


def test_get_prompt_status_unknown_when_queue_response_is_incomplete() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/history"):
            return httpx.Response(200, json={}, request=request)
        return httpx.Response(200, json=["unexpected"], request=request)

    result = runtime_with(handler).get_prompt_status("prompt-1")

    assert result["status"] == "unknown"
    assert result["queue_state"] == "unknown"


def test_extract_outputs_normalizes_typical_history() -> None:
    result = CapabilityRuntime().extract_outputs(sample_history())

    assert result["images"][0] == {
        "filename": "Workbench_00001_.png",
        "subfolder": "",
        "type": "output",
        "node_id": "9",
        "node_label": "Final image",
        "format": "png",
        "display_name": "Workbench_00001_.png",
        "kind": "image",
    }
    assert result["text"] == [{"node_id": "9", "node_label": "Final image", "text": "done"}]


def test_fetch_image_success_returns_base64_and_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/view"
        assert request.url.params["filename"] == "cat.png"
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG_BYTES, request=request)

    result = runtime_with(handler).fetch_image("cat.png")

    assert result["mime_type"] == "image/png"
    assert result["size_bytes"] == len(PNG_BYTES)
    assert result["data_base64"] == base64.b64encode(PNG_BYTES).decode("ascii")


def test_fetch_image_404_maps_to_output_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    with pytest.raises(ComfyUIError) as exc:
        runtime_with(handler).fetch_image("missing.png")

    assert exc.value.code == "COMFYUI_OUTPUT_NOT_FOUND"


def test_wait_for_prompt_success_polls_until_history_exists() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(200, json={}, request=request)
        return httpx.Response(200, json=sample_history(), request=request)

    result = runtime_with(handler).wait_for_prompt("prompt-1", timeout_seconds=1, poll_interval_seconds=0.01)

    assert calls["count"] == 3
    assert result["completed"] is True
    assert result["timed_out"] is False
    assert result["status"] == "completed"
    assert result["outputs"]["summary"]["image_count"] == 1


def test_wait_for_prompt_timeout_has_prompt_and_elapsed_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    with pytest.raises(ComfyUIError) as exc:
        runtime_with(handler).wait_for_prompt("slow", timeout_seconds=0.01, poll_interval_seconds=0)

    assert exc.value.code == "COMFYUI_TIMEOUT"
    assert exc.value.detail["prompt_id"] == "slow"
    assert exc.value.detail["timeout_seconds"] == 0.01
    assert "elapsed_seconds" in exc.value.detail
    assert "last_status" in exc.value.detail


def test_wait_for_prompt_failed_prompt_raises_structured_error() -> None:
    history = sample_history()
    history["prompt-1"]["status"] = {"status_str": "failed", "completed": False}
    history["prompt-1"]["exception_message"] = "node failed"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=history, request=request)

    with pytest.raises(ComfyUIError) as exc:
        runtime_with(handler).wait_for_prompt("prompt-1", timeout_seconds=1, poll_interval_seconds=0)

    assert exc.value.code == "COMFYUI_PROMPT_FAILED"
    assert exc.value.detail["prompt_id"] == "prompt-1"
    assert exc.value.detail["error"]["message"] == "node failed"


def test_collect_images_for_prompt_can_include_binary_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/history"):
            return httpx.Response(200, json=sample_history(), request=request)
        if request.url.path == "/view":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG_BYTES, request=request)
        return httpx.Response(404, request=request)

    result = runtime_with(handler).collect_images_for_prompt("prompt-1", include_binary=True)

    assert result["summary"] == {"image_count": 1}
    assert result["images"][0]["filename"] == "Workbench_00001_.png"
    assert result["images"][0]["data_base64"] == base64.b64encode(PNG_BYTES).decode("ascii")


def test_interrupt_success_and_failure_are_structured() -> None:
    ok_runtime = runtime_with(lambda request: httpx.Response(200, json={}, request=request))
    fail_runtime = runtime_with(lambda request: httpx.Response(500, text="nope", request=request))

    assert ok_runtime.interrupt()["ok"] is True
    failed = fail_runtime.interrupt()
    assert failed["ok"] is False
    assert failed["error"]["code"] == "COMFYUI_INTERRUPT_FAILED"


def test_free_memory_posts_default_payload_and_accepts_empty_success() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.read()
        return httpx.Response(200, content=b"", request=request)

    result = runtime_with(handler).free_memory()

    assert seen["path"] == "/free"
    assert b'"unload_models":true' in seen["body"].replace(b" ", b"")
    assert b'"free_memory":true' in seen["body"].replace(b" ", b"")
    assert result["ok"] is True
    assert result["requested"] == {"unload_models": True, "free_memory": True}
    assert result["status_code"] == 200
    assert result["response"] == {}


def test_free_memory_allows_independent_flags() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.read())
        return httpx.Response(200, json={"freed": True}, request=request)

    runtime = runtime_with(handler)
    unload_only = runtime.free_memory(free_memory=False)
    free_only = runtime.free_memory(unload_models=False)

    assert b'"free_memory":false' in seen[0].replace(b" ", b"")
    assert unload_only["requested"] == {"unload_models": True, "free_memory": False}
    assert b'"unload_models":false' in seen[1].replace(b" ", b"")
    assert free_only["requested"] == {"unload_models": False, "free_memory": True}


def test_free_memory_failure_is_structured() -> None:
    failed = runtime_with(lambda request: httpx.Response(404, text="missing", request=request)).free_memory()

    assert failed["ok"] is False
    assert failed["status_code"] == 404
    assert failed["error"]["code"] == "COMFYUI_FREE_MEMORY_FAILED"


def test_upload_image_builds_multipart_request() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["content_type"] = request.headers["content-type"]
        seen["body"] = request.read()
        return httpx.Response(200, json={"name": "input.png", "subfolder": "refs", "type": "input"}, request=request)

    result = runtime_with(handler).upload_image("input.png", data_base64=base64.b64encode(PNG_BYTES).decode("ascii"), subfolder="refs")

    assert seen["path"] == "/upload/image"
    assert "multipart/form-data" in seen["content_type"]
    assert b'filename="input.png"' in seen["body"]
    assert b'name="subfolder"' in seen["body"]
    assert b"refs" in seen["body"]
    assert result["uploaded"] is True
    assert result["name"] == "input.png"


def test_upload_image_manifest_declares_runtime_public_fields() -> None:
    manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / "capabilities" / "comfyui" / "capability.yaml").read_text())
    upload = next(method for method in manifest["methods"] if method["id"] == "upload_image")
    free = next(method for method in manifest["methods"] if method["id"] == "free_memory")

    assert set(upload["input_schema"]) == {"filename", "data_base64", "overwrite", "type", "subfolder"}
    assert set(free["input_schema"]) == {"unload_models", "free_memory"}


def test_comfyui_error_to_dict_stays_stable() -> None:
    error = ComfyUIError("COMFYUI_BAD_RESPONSE", "Bad response.", {"status_code": 500})

    assert error.to_dict() == {
        "code": "COMFYUI_BAD_RESPONSE",
        "message": "Bad response.",
        "detail": {"status_code": 500},
    }


def test_get_object_info_returns_node_count_and_keys() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"SaveImage": {}, "KSampler": {}}, request=request)

    result = runtime_with(handler).get_object_info()

    assert result["node_count"] == 2
    assert result["keys"] == ["KSampler", "SaveImage"]
