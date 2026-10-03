"""Event observation belongs to tests, not to the production transport."""
from ai_workbench.core.events import EventBus


class RecordingEventBus(EventBus):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recorded = []

    def emit(self, *args, **kwargs):
        event = super().emit(*args, **kwargs)
        self.recorded.append(event)
        return event

    def list_events(self):
        return list(self.recorded)
