from fastapi import HTTPException


def error_response(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def raise_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail=error_response(code, message))

