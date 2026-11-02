"""Bounded private history tools; caller identity comes from the active Harness."""
import json
from itertools import islice

from ai_workbench.core.context import _eligible, message_text
from ai_workbench.core.context_history import ConversationHistory
from ai_workbench.core.harness.schema import ToolExecutionError, ToolSpec
from ai_workbench.core.history_retrieval import text_tokens
from ai_workbench.core.qq_context import QQContextHistory
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.context_budget import ContextLimits
from ai_workbench.core.schema.retrieval import CONTEXT_TOOL_NAMES, RetrievalCheckpoint


def clip_text(text, offset, limit):
    high = min(len(text), offset + limit * 8)
    low = offset
    while low < high:
        middle = (low + high + 1) // 2
        if text_tokens(text[offset:middle]) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[offset:low], low if low < len(text) else None


class RetrievalTools:
    def __init__(self, sessions, messages, runs, qq_store, retrieval):
        self.sessions, self.messages, self.runs, self.qq_store = sessions, messages, runs, qq_store
        self.retrieval = retrieval

    def register(self, registry):
        scope = {"type": "string", "enum": ["history", "run"]}
        cursor = {"type": ["string", "null"], "maxLength": 256}
        specs = [
            ("context_list", "List source IDs and short previews in this conversation or completed current-run records.",
             {"scope": scope, "cursor": cursor, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["scope"]),
            ("context_search", "Search a bounded page of projected text. Continue with next_cursor even when items is empty.",
             {"scope": scope, "query": {"type": "string", "minLength": 1, "maxLength": 512}, "cursor": cursor}, ["scope", "query"]),
            ("context_read", "Read a bounded text range using a returned source ID. Old images return descriptions only.",
             {"source_id": {"type": "string", "maxLength": 256}, "offset": {"type": "integer", "minimum": 0},
              "max_tokens": {"type": "integer", "minimum": 1, "maximum": 4096}}, ["source_id"]),
            ("context_checkpoint_update", "Replace memory (commit only on successful run) or progress (this run only). Cite source IDs. Both share a token allowance. Empty text clears that checkpoint.",
             {"scope": {"type": "string", "enum": ["memory", "progress"]}, "text": {"type": "string", "maxLength": 65536},
              "references": {"type": "array", "items": {"type": "string", "maxLength": 256}, "maxItems": 64, "uniqueItems": True}},
             ["scope", "text", "references"]),
        ]
        for name, description, properties, required in specs:
            async def handler(arguments, context, operation=name):
                return await self.execute(operation, arguments, context)
            registry.register(ToolSpec(name=name, description=description,
                parameters={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
                handler=handler, direct_callable=False, scope="context"))

    async def execute(self, operation, args, context):
        state = context.harness_state
        if state is None or state.retrieval is None or context.session_id != state.retrieval.session.session_id:
            raise ToolExecutionError("CONTEXT_TOOL_UNAVAILABLE", "Context tools require an active on-demand history run.")
        work = state.retrieval
        if self.sessions.get_session(context.session_id).history_version != work.session.history_version:
            raise ToolExecutionError("CONTEXT_HISTORY_CHANGED", "History changed during this run; the frozen context remains unchanged.")
        reader = RetrievalReader(self.messages, self.qq_store, context, state)
        allowance = max(1, work.output_tokens - 128)
        if operation == "context_read":
            record = reader.read(args["source_id"])
            offset = args.get("offset", 0)
            text, next_offset = clip_text(record["text"], offset, min(allowance, args.get("max_tokens", 4096)))
            return {"source_id": record["source_id"], "text": text, "offset": offset,
                "next_offset": next_offset, "truncated": next_offset is not None}
        if operation == "context_checkpoint_update":
            references = []
            for source_id in args["references"]:
                if source_id.startswith("checkpoint:"):
                    raise ToolExecutionError("CONTEXT_SOURCE_FORBIDDEN", "Cite original history or completed tool records, not another checkpoint.")
                record = reader.read(source_id)
                references.append(record["source_id"])
                if args["scope"] == "memory" and reader.qq and not source_id.startswith("batch:"):
                    raise ToolExecutionError("CONTEXT_SOURCE_FORBIDDEN", "QQ memory must cite submitted batches with confirmed delivery history.")
            other = work.progress if args["scope"] == "memory" else work.session.memory
            checkpoint = RetrievalCheckpoint(text=args["text"], references=references)
            config = self.runs.get_config_snapshot(context.run_id)
            profile = self.retrieval.models.profile(config["model_profile_id"], "llm")
            cost = await self.retrieval.count_checkpoints(profile, ContextLimits.model_validate(config["context_limits"]), (checkpoint, other))
            if cost > work.checkpoint_tokens:
                raise ToolExecutionError("CONTEXT_CHECKPOINT_LIMIT", "The combined checkpoints exceed the token allowance.",
                    {"max_tokens": work.checkpoint_tokens})
            work.checkpoint_body_tokens = cost
            if args["scope"] == "memory":
                work.session.memory = checkpoint
            else:
                work.progress = checkpoint
            return {"source_id": "checkpoint:" + checkpoint.checkpoint_id, "scope": args["scope"],
                "tokens": text_tokens(checkpoint.text), "max_tokens": work.checkpoint_tokens}
        search = operation == "context_search"
        count = 128 if search else args.get("limit", 20)
        entries = iter(reader.iterate(args["scope"], args.get("cursor")))
        items, last = [], args.get("cursor")
        scanned = 0
        for record in islice(entries, count):
            scanned += 1
            needle = args.get("query", "")
            found = record["text"].find(needle)
            if found >= 0:
                offset = max(0, found - 80)
                preview, _ = clip_text(record["text"], offset, min(120, allowance))
                item = {"source_id": record["source_id"], "time": record.get("time"), "preview": preview, "offset": offset}
                if len(items) >= 20 or text_tokens(json.dumps([*items, item], ensure_ascii=False)) > allowance:
                    return {"items": items, "scanned": scanned - 1, "next_cursor": last, "has_more": True}
                items.append(item)
            last = record["source_id"]
        more = next(entries, None) is not None
        return {"items": items, "scanned": scanned, "next_cursor": last if more else None, "has_more": more}


class RetrievalReader:
    def __init__(self, messages, qq_store, context, state):
        self.messages, self.qq_store, self.context, self.state = messages, qq_store, context, state
        self.work = state.retrieval
        self.current = messages.get_message(self.work.input_id) if self.work.input_id else None
        self.qq = bool(self.current and "qq_batch_id" in self.current.metadata)
        self.policy = ContextPolicy(history_enabled=self.work.history_enabled,
            include_attachments=self.work.session.include_attachments)
        self.call_sources = {row.metadata["tool_call_id"]: row
            for row in messages.messages_for_run(context.run_id) if row.role == "tool" and row.metadata.get("tool_call_id")}

    def history(self):
        if not self.work.history_enabled:
            raise ToolExecutionError("CONTEXT_HISTORY_DISABLED", "Previous conversation history is disabled.")
        if self.qq:
            return QQContextHistory(self.qq_store, self.messages, self.context.session_id, self.policy, self.current)
        return ConversationHistory(self.messages, self.context.session_id, self.policy, self.current)

    def record(self, item):
        return {"source_id": f"batch:{item.qq_batch_id}" if item.qq_batch_id else "message:" + item.message_id,
            "time": item.created_at.isoformat(), "text": item.summary_text}

    def run_records(self):
        if self.current:
            if self.qq:
                yield self.read("batch:" + str(self.current.metadata["qq_batch_id"]))
            else:
                yield {"source_id": "message:" + self.current.message_id, "time": self.current.created_at.isoformat(),
                    "text": message_text(self.current, include_attachments=self.policy.include_attachments == "explicit")}
        calls = {}
        for item in self.state.transcript:
            for call in item.get("tool_calls", []):
                if call["function"]["name"] not in CONTEXT_TOOL_NAMES:
                    calls[call["id"]] = call
            if item.get("role") == "tool" and item.get("tool_call_id") in calls:
                call = calls[item["tool_call_id"]]
                source = self.call_sources[call["id"]]
                yield {"source_id": "message:" + source.message_id, "call_id": call["id"],
                    "time": source.created_at.isoformat(),
                    "text": message_text(source, include_attachments=self.policy.include_attachments == "explicit")}

    def iterate(self, scope, cursor):
        if scope == "run":
            records = list(self.run_records())
            ids = [item["source_id"] for item in records]
            if cursor and cursor not in ids:
                raise ToolExecutionError("CONTEXT_SOURCE_NOT_FOUND", "The cursor is not part of this run.")
            yield from records[ids.index(cursor) + 1 if cursor else 0:]
            return
        history = self.history()
        before = None
        if cursor:
            self.read(cursor)
            if self.qq and cursor.startswith("batch:"):
                before = int(cursor[6:])
            elif not self.qq and cursor.startswith("message:"):
                row = self.messages.get_message(cursor[8:])
                before = (row.created_at, row.message_id)
                if self.current and before >= (self.current.created_at, self.current.message_id):
                    raise ToolExecutionError("CONTEXT_SOURCE_NOT_FOUND", "Use run scope for records from the current input onward.")
            else:
                raise ToolExecutionError("CONTEXT_SOURCE_NOT_FOUND", "The cursor is not conversation history.")
        for item in history.iterate(before=before):
            if item.summary_text:
                yield self.record(item)

    def read(self, source_id):
        for checkpoint in (self.work.session.memory, self.work.progress):
            if source_id == "checkpoint:" + checkpoint.checkpoint_id:
                return {"source_id": source_id, "text": checkpoint.text}
        if source_id.startswith("call:"):
            for item in self.run_records():
                if item.get("call_id") == source_id[5:]:
                    return item
        elif source_id.startswith("message:"):
            try:
                row = self.messages.get_message(source_id[8:])
            except KeyError:
                row = None
            current = not self.qq and row and self.current and row.message_id == self.current.message_id
            completed = row and row.run_id == self.context.run_id and any(m.get("tool_call_id") == row.metadata.get("tool_call_id")
                for m in self.state.transcript if m.get("role") == "tool") and row.metadata.get("tool") not in CONTEXT_TOOL_NAMES
            if row and row.session_id == self.context.session_id and (current or completed or (not self.qq and self.work.history_enabled
                    and _eligible(row) and (self.current is None or (row.created_at, row.message_id) < (self.current.created_at, self.current.message_id)))):
                text = message_text(row, include_attachments=self.policy.include_attachments == "explicit")
                if text:
                    return {"source_id": source_id, "time": row.created_at.isoformat(), "text": text}
        elif source_id.startswith("batch:") and self.qq:
            try:
                number = int(source_id[6:])
            except ValueError:
                number = -1
            current = self.current.metadata["qq_batch_id"]
            if number == current or (self.work.history_enabled and 0 < number < current):
                history = QQContextHistory(self.qq_store, self.messages, self.context.session_id, self.policy, self.current)
                for item in history.iterate(after=number - 1, before=number + 1):
                    return self.record(item)
        raise ToolExecutionError("CONTEXT_SOURCE_NOT_FOUND", "The source is unavailable in this conversation or current run.")
