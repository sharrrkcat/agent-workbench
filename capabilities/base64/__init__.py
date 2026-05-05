import base64
import binascii


class CapabilityRuntime:
    def encode(self, text: str) -> str:
        return base64.b64encode(text.encode("utf-8")).decode("ascii")

    def decode(self, text: str) -> str:
        try:
            decoded = base64.b64decode(text.encode("ascii"), validate=True)
            return decoded.decode("utf-8")
        except (binascii.Error, UnicodeEncodeError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid base64 input.") from exc

