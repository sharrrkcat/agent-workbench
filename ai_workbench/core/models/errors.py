class ModelError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details

    def payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "type": "model_error", **({"details": self.details} if self.details else {})}}
