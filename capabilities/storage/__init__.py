class CapabilityRuntime:
    def __init__(self) -> None:
        self._values = {}

    def get(self, key: str):
        return self._values.get(key)

    def set(self, key: str, value=None):
        self._values[key] = value
        return value
