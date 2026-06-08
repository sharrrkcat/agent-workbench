from enum import Enum
from uuid import uuid4

from fastapi import HTTPException


class InferenceErrorCode(str, Enum):
    SERVICE_DISABLED = "INFERENCE_SERVICE_DISABLED"
    AUTH_REQUIRED = "INFERENCE_AUTH_REQUIRED"
    AUTH_INVALID = "INFERENCE_AUTH_INVALID"
    NOT_IMPLEMENTED = "INFERENCE_NOT_IMPLEMENTED"
    REQUEST_TOO_LARGE = "INFERENCE_REQUEST_TOO_LARGE"
    INVALID_REQUEST = "INFERENCE_INVALID_REQUEST"
    MODEL_INPUT_TYPE_UNSUPPORTED = "MODEL_INPUT_TYPE_UNSUPPORTED"


OPENAI_ERROR_CODES = {
    InferenceErrorCode.SERVICE_DISABLED: "inference_service_disabled",
    InferenceErrorCode.AUTH_REQUIRED: "inference_auth_required",
    InferenceErrorCode.AUTH_INVALID: "inference_auth_invalid",
    InferenceErrorCode.NOT_IMPLEMENTED: "inference_not_implemented",
    InferenceErrorCode.REQUEST_TOO_LARGE: "inference_request_too_large",
    InferenceErrorCode.INVALID_REQUEST: "inference_invalid_request",
    InferenceErrorCode.MODEL_INPUT_TYPE_UNSUPPORTED: "model_input_type_unsupported",
}


DEFAULT_MESSAGES = {
    InferenceErrorCode.SERVICE_DISABLED: "Stateless inference service is disabled.",
    InferenceErrorCode.AUTH_REQUIRED: "Inference API authentication is required.",
    InferenceErrorCode.AUTH_INVALID: "Inference API authentication is invalid.",
    InferenceErrorCode.NOT_IMPLEMENTED: "Inference endpoint is registered but not implemented yet.",
    InferenceErrorCode.REQUEST_TOO_LARGE: "Inference request is too large.",
    InferenceErrorCode.INVALID_REQUEST: "Inference request is invalid.",
    InferenceErrorCode.MODEL_INPUT_TYPE_UNSUPPORTED: "Model does not support this input type.",
}


def request_id() -> str:
    return str(uuid4())


def workbench_error_payload(
    code: InferenceErrorCode,
    message: str | None = None,
    *,
    request_id_value: str | None = None,
) -> dict:
    return {
        "error": {
            "code": code.value,
            "message": message or DEFAULT_MESSAGES[code],
            "request_id": request_id_value or request_id(),
        }
    }


def openai_error_payload(code: InferenceErrorCode, message: str | None = None) -> dict:
    return {
        "error": {
            "message": message or DEFAULT_MESSAGES[code],
            "type": "invalid_request_error",
            "code": OPENAI_ERROR_CODES[code],
        }
    }


def raise_workbench_inference_error(
    status_code: int,
    code: InferenceErrorCode,
    message: str | None = None,
) -> None:
    raise HTTPException(status_code=status_code, detail=workbench_error_payload(code, message))


def raise_openai_inference_error(
    status_code: int,
    code: InferenceErrorCode,
    message: str | None = None,
) -> None:
    raise HTTPException(status_code=status_code, detail=openai_error_payload(code, message))
