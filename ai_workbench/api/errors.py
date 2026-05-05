from fastapi import HTTPException


from typing import Any, Dict


def error_response(code: str, message: str, details: Dict[str, Any] = None) -> dict:
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def raise_error(status_code: int, code: str, message: str, details: Dict[str, Any] = None) -> None:
    raise HTTPException(status_code=status_code, detail=error_response(code, message, details))
