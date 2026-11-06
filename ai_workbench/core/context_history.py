"""Projected history items consumed by bounded conversation compaction."""
from dataclasses import dataclass
from datetime import datetime

from ai_workbench.core.context import _project, _trace_message, message_text, persona_context_prefix
from ai_workbench.core.schema.context_snapshot import ContextTrace


@dataclass
class HistoryItem:
    message_id: str
    created_at: datetime
    turn_id: str
    messages: list[dict]
    trace: ContextTrace
    summary_text: str
    count: int = 1
    qq_batch_id: int | None = None

    @property
    def key(self):
        return self.qq_batch_id if self.qq_batch_id is not None else (self.created_at, self.message_id)


class ConversationHistory:
    def __init__(self, messages, session_id, policy, current, through=None):
        self.messages, self.session_id, self.policy = messages, session_id, policy
        self.exclude_id = current.message_id if current else None
        self.before = (current.created_at, current.message_id) if current else None
        self.through = through

    def counts(self):
        return self.messages.context_history_counts(self.session_id, self.exclude_id, through=self.through)

    def checkpoint_key(self, checkpoint):
        return (checkpoint.boundary_created_at, checkpoint.boundary_message_id)

    def iterate(self, *, after=None, before=None, ascending=False):
        for row in self.messages.iter_context_history(self.session_id, self.exclude_id,
                after=after, before=before if before is not None else self.before, through=self.through, ascending=ascending):
            attachments = self.policy.include_attachments == "explicit"
            item = _project(row, include_attachments=attachments)
            turn = self.messages.context_turn_id(row)
            trace = ContextTrace()
            if item is not None:
                _trace_message(trace, row, 0, item, "history", attachments, turn_id=turn)
            text = "" if row.role == "system" else message_text(row, include_attachments=attachments)
            yield HistoryItem(row.message_id, row.created_at, turn, [item] if item is not None else [], trace,
                f"\n[{row.role}; message={row.message_id}]\n{persona_context_prefix(row)}{text}\n" if text else "")
