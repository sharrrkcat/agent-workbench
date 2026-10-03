"""Conversation cursors and the in-memory implementation of bounded history reads."""
import base64
import binascii
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_workbench.core.time import ensure_utc


class HistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: str | None = Field(default=None, max_length=1024)
    after: str | None = Field(default=None, max_length=1024)
    around: str | None = Field(default=None, max_length=1024)
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def one_direction(self):
        if sum(value is not None for value in (self.before, self.after, self.around)) > 1:
            raise ValueError("Use only one of before, after or around")
        return self


class HistoryCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    created_at: datetime
    kind: Literal[0, 1]
    id: str

    def key(self):
        return ensure_utc(self.created_at), self.kind, self.id

    def encode(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode()

    @classmethod
    def decode(cls, value: str, session_id: str):
        try:
            cursor = cls.model_validate_json(base64.b64decode(value, altchars=b"-_", validate=True))
            if cursor.session_id != session_id:
                raise ValueError("Cursor belongs to another session")
            return cursor
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid history cursor") from exc


def cursor_for(session_id, key):
    return HistoryCursor(session_id=session_id, created_at=key[0], kind=key[1], id=key[2]).encode()


def page_envelope(session_id, keys, numbers, items, version, has_before, has_after, active_run=None):
    return {"items": [{**item, "id": key[2], "number": number, "cursor": cursor_for(session_id, key),
                       "created_at": ensure_utc(key[0]).isoformat()} for key, number, item in zip(keys, numbers, items)],
            "before_cursor": cursor_for(session_id, keys[0]) if keys else None,
            "after_cursor": cursor_for(session_id, keys[-1]) if keys else None,
            "has_before": has_before, "has_after": has_after, "history_version": version, "active_run": active_run}


class MemoryHistoryReader:
    def __init__(self, sessions, messages, runs):
        self.sessions, self.messages, self.runs = sessions, messages, runs

    def page(self, session_id: str, query: HistoryQuery, *, users: bool = False):
        session = self.sessions.get_session(session_id)
        messages = self.messages.list_messages(session_id)
        runs = self.runs.list_runs(session_id)
        all_items = sorted([(ensure_utc(m.created_at), 0, m.message_id) for m in messages if m.role == "user" or not m.run_id]
                           + [(ensure_utc(r.created_at), 1, r.run_id) for r in runs])
        numbers = {key: index + 1 for index, key in enumerate(all_items)}
        user_ids = {m.message_id for m in messages if m.role == "user"}
        candidates = [key for key in all_items if not users or key[1] == 0 and key[2] in user_ids]
        value = query.before or query.after or query.around
        anchor = HistoryCursor.decode(value, session_id).key() if value else None
        if query.around:
            earlier = [key for key in candidates if key < anchor][-(query.limit // 2):] if query.limit > 1 else []
            chosen = earlier + [key for key in candidates if key >= anchor][:query.limit - len(earlier)]
        elif query.after:
            chosen = [key for key in candidates if key > anchor][:query.limit]
        else:
            chosen = [key for key in candidates if anchor is None or key < anchor][-query.limit:]
        items = []
        for key in chosen:
            if key[1] == 0:
                message = self.messages.get_message(key[2])
                if users:
                    from ai_workbench.core.message_parts import text_from_parts
                    items.append({"kind": "user", "summary": text_from_parts(message.parts)[:160]})
                else:
                    items.append({"kind": "message", "message": message.model_dump(mode="json")})
            else:
                items.append({"kind": "reply", "run": self._run(key[2]),
                              "messages": [m.model_dump(mode="json") for m in self.messages.messages_for_run(key[2])]})
        active = next((r for r in reversed(runs) if r.status.value in {"PENDING", "RUNNING", "CANCELLING", "WAITING_FOR_USER"}), None)
        return page_envelope(session_id, chosen, [numbers[key] for key in chosen], items, session.history_version,
            bool(chosen and candidates[0] < chosen[0]), bool(chosen and candidates[-1] > chosen[-1]),
            active.model_dump(mode="json") if active and not users else None)

    def _run(self, run_id):
        return {**self.runs.get_run(run_id).model_dump(mode="json"),
                "steps": [s.model_dump(mode="json") for s in self.runs.list_steps(run_id)]}

    def reference_numbers(self, session_id, ids):
        messages = self.messages.list_messages(session_id)
        runs = self.runs.list_runs(session_id)
        keys = sorted([(ensure_utc(m.created_at), 0, m.message_id) for m in messages if m.role == "user" or not m.run_id]
                      + [(ensure_utc(r.created_at), 1, r.run_id) for r in runs])
        numbers = {key[2]: index + 1 for index, key in enumerate(keys)}
        result = {id: number for id, number in numbers.items() if id in ids}
        for message in messages:
            if message.message_id in ids and message.role != "user" and message.run_id in numbers:
                result[message.message_id] = numbers[message.run_id]
        return result
