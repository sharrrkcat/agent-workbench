"""Normalize model output and settle one assistant draft on every exit path."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from ai_workbench.core.schema.message import MessageSchema


PartKind = Literal["text", "reasoning"]


class ThinkParser:
    """Incremental model markers, with Markdown code and escapes left literal."""

    def __init__(self, emit: Callable[[PartKind, str], None]) -> None:
        self.emit = emit
        self.pending = ""
        self.reasoning = False
        self.fence: tuple[str, int] | None = None
        self.inline_ticks = 0
        self.indent = 0
        self.line_prefix = True
        self.finished = False

    def feed(self, text: str, *, final: bool = False) -> None:
        if self.finished:
            raise ValueError("Output has already ended")
        self.pending += text
        segments: list[str] = []

        def flush() -> None:
            if segments:
                self.emit("reasoning" if self.reasoning else "text", "".join(segments))
                segments.clear()

        def consume(length: int) -> None:
            value = self.pending[:length]
            self.pending = self.pending[length:]
            segments.append(value)
            for char in value:
                if char == "\n":
                    self.indent = 0
                    self.line_prefix = True
                elif char == " " and self.line_prefix:
                    self.indent += 1
                elif char == "\t" and self.line_prefix:
                    self.indent += 4
                elif char != "\r":
                    self.line_prefix = False

        while self.pending:
            char = self.pending[0]
            if not self.fence and not self.inline_ticks and self.indent >= 4:
                consume(1)
                continue
            if char == "\\" and not self.fence and not self.inline_ticks:
                if len(self.pending) == 1 and not final:
                    break
                consume(min(2, len(self.pending)))
                continue
            if char in {"`", "~"}:
                length = len(self.pending) - len(self.pending.lstrip(char))
                if length == len(self.pending) and not final:
                    break
                if self.fence:
                    if self.line_prefix and self.indent < 4 and char == self.fence[0] and length >= self.fence[1]:
                        suffix = self.pending[length:].split("\n", 1)[0]
                        if not suffix.strip():
                            if "\n" not in self.pending and not final:
                                break
                            self.fence = None
                elif self.line_prefix and self.indent < 4 and length >= 3 and not self.inline_ticks:
                    self.fence = (char, length)
                elif char == "`":
                    if self.inline_ticks == length:
                        self.inline_ticks = 0
                    elif not self.inline_ticks:
                        self.inline_ticks = length
                consume(length)
                continue
            if char == "<" and not self.fence and not self.inline_ticks:
                marker = "</think>" if self.reasoning else "<think>"
                if self.pending.startswith(marker):
                    flush()
                    self.pending = self.pending[len(marker):]
                    self.reasoning = not self.reasoning
                    continue
                if marker.startswith(self.pending) and not final:
                    break
            consume(1)
        flush()
        self.finished = final


class AssistantDraft:
    def __init__(self, *, messages, events, session_id: str, run_id: str, message_id: str,
                 config, parent_message_id: str | None, streamed: bool) -> None:
        self.messages = messages
        self.events = events
        self.streamed = streamed
        self.parts: list[dict[str, Any]] = []
        self.raw_content = ""
        self.reasoning_content = ""
        self.seq = 0
        self.saved: MessageSchema | None = None
        self.parser = ThinkParser(self._append_part)
        self.message = MessageSchema(
            message_id=message_id, session_id=session_id, run_id=run_id, role="assistant",
            speaker_type="assistant", speaker_id=config.persona_id, speaker_name=config.persona_name,
            parent_message_id=parent_message_id,
            metadata={"speaker_avatar_attachment_id": config.avatar_attachment_id, "streamed": streamed},
        )
        draft = self.message.model_copy(update={"metadata": {**self.message.metadata, "streaming": True}})
        self._emit("message_started", {"message": draft.model_dump(mode="json"), "seq": 0})

    def append(self, content: str | None = None, reasoning_content: str | None = None) -> None:
        if reasoning_content:
            self.reasoning_content += reasoning_content
            self._append_part("reasoning", reasoning_content)
        if content:
            self.raw_content += content
            self.parser.feed(content)

    def _append_part(self, kind: PartKind, text: str) -> None:
        if not text:
            return
        if not self.parts or self.parts[-1]["type"] != kind:
            part = {"id": f"{self.message.message_id}-part-{len(self.parts) + 1}", "type": kind, "text": ""}
            if kind == "text":
                part["format"] = "markdown"
            self.parts.append(part)
        part = self.parts[-1]
        part["text"] += text
        if self.streamed:
            self.seq += 1
            self._emit("message_delta", {"seq": self.seq, "part_id": part["id"], "part_type": kind, "delta": text})

    def persist(self, *, incomplete: bool = False, extra_parts: list[dict[str, Any]] | None = None,
                metadata: dict[str, Any] | None = None) -> MessageSchema | None:
        if self.saved is not None:
            return self.saved
        if not self.parser.finished:
            self.parser.feed("", final=True)
        parts = [*self.parts, *(extra_parts or [])]
        if incomplete and not parts:
            return None
        values = self.message.model_dump(exclude={"parts", "metadata", "created_at", "content_version"})
        self.saved = self.messages.add_message(
            **values, parts=parts,
            metadata={**self.message.metadata, **(metadata or {}), **({"incomplete": True} if incomplete else {})},
        )
        self._emit("message_completed", {"message": self.saved.model_dump(mode="json")})
        return self.saved

    @property
    def text(self) -> str:
        return "".join(part["text"] for part in self.parts if part["type"] == "text")

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.emit(event_type, session_id=self.message.session_id, run_id=self.message.run_id,
                         message_id=self.message.message_id, payload=payload)
