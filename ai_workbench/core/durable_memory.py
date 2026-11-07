"""Bounded foreground recall and validated main-model candidates."""

import json
from copy import deepcopy
from pydantic import ValidationError

from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.harness.schema import ToolExecutionError, ToolSpec
from ai_workbench.core.retrieval_tools import clip_text
from ai_workbench.core.memory_service import forget
from ai_workbench.core.memory_prompt import render_memory_index, replace_memory_index
from ai_workbench.core.schema.memory import (MemoryRunState, MemoryMutation, MemoryEntry,
    MemoryOrigin, MemoryWrite, MemoryContextReference)
from ai_workbench.core.schema.context_snapshot import ContextSource, ContextExclusion
from ai_workbench.core.time import utc_now


def reference(entry, reason):
    return MemoryContextReference(id=entry.id, revision=entry.revision, character_id=entry.character_id,
        persona_id=entry.persona_id, session_id=entry.session_id, pool=entry.pool, reason=reason)


class DurableMemory:
    def __init__(self, service, runs, models):
        self.service, self.runs, self.models = service, runs, models

    def start(self, run, config):
        if config.session_kind != "normal" or not config.memory_enabled:
            return None
        session = self.service.chat.sessions.get_session(run.session_id)
        return MemoryRunState(view=self.service.view(run.session_id), history_version=session.history_version)

    def register(self, registry):
        paging = {"offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}
        specs = [
            ("memory_list", "List remembered fact summaries. Continue using next_offset.", paging, []),
            ("memory_search", "Search remembered facts by literal text.",
                {**paging, "query": {"type": "string", "minLength": 1, "maxLength": 4000}}, ["query"]),
            ("memory_read", "Read up to eight remembered facts using their IDs.",
                {"ids": {"type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 128}}}, ["ids"]),
            ("memory_write", "Save a lasting user-confirmed fact. Omit id for a new entry; use a known memory ID to update an entry.",
                {"summary": {"type": "string", "minLength": 1, "maxLength": 160},
                 "body": {"type": "string", "minLength": 1, "maxLength": 2000},
                 "id": {"type": ["string", "null"], "minLength": 1, "maxLength": 128}},
                ["summary", "body"]),
            ("memory_forget", "Forget a remembered fact using its ID.",
                {"id": {"type": "string", "minLength": 1, "maxLength": 128}}, ["id"]),
        ]
        for name, description, properties, required in specs:
            async def handler(arguments, context, operation=name):
                try:
                    return self.execute(operation, arguments, context)
                except ChatError as exc:
                    raise ToolExecutionError(exc.code, exc.message) from exc
                except ValidationError as exc:
                    raise ToolExecutionError("INVALID_ARGUMENTS", "Supply a nonempty summary and body. Omit id for a new entry; use a known memory ID for an update.") from exc
            registry.register(ToolSpec(name=name, description=description,
                parameters={"type": "object", "properties": properties, "required": required,
                    "additionalProperties": False}, handler=handler, direct_callable=False, scope="memory"))

    def execute(self, operation, args, context):
        state = context.harness_state
        work = state.memory if state is not None else None
        if work is None or context.session_id != work.view.session_id:
            raise ToolExecutionError("MEMORY_TOOL_UNAVAILABLE", "Memory is unavailable.")
        self.check(work)
        if operation in {"memory_write", "memory_forget"}:
            return self.stage(operation, args, context)
        overlay = {item.entry.id: item.entry for item in work.mutations}
        if operation == "memory_read":
            entries = []
            for memory_id in args["ids"]:
                entry = overlay.get(memory_id) or self.service.get(memory_id, session_id=context.session_id)
                if entry.status != "active":
                    raise ToolExecutionError("MEMORY_UNAVAILABLE", "Memory is unavailable.")
                entries.append(entry)
            result = {"items": [entry.model_dump(mode="json", include={"id", "summary", "body", "observed_at"})
                for entry in entries]}
        else:
            offset, limit = args.get("offset", 0), args.get("limit", 20)
            entries, total = self.service.store.query(view=work.view, query=args.get("query", ""), offset=offset, limit=limit)
            result = {"items": [{"id": entry.id, "summary": entry.summary,
                "date": entry.observed_at.date().isoformat()} for entry in entries], "total": total,
                "next_offset": offset + len(entries) if offset + len(entries) < total else None}
        # Each tool result is bounded here; the complete per-call memory budget
        # also counts older results and index entries before model dispatch.
        count = self.models.reference_tokens.count_text
        allowance = max(0, work.allowance - 64)
        while result["items"] and count(json.dumps(result, ensure_ascii=False)) > allowance:
            last = result["items"][-1]
            if last.get("body"):
                last["body"], _ = clip_text(last["body"], 0, max(0, allowance // 3), count)
                last["truncated"] = True
                if count(json.dumps(result, ensure_ascii=False)) <= allowance:
                    break
            result["items"].pop()
            result["truncated"] = True
        if operation != "memory_read" and len(result["items"]) < len(entries):
            result["next_offset"] = args.get("offset", 0) + len(result["items"])
        returned = {item["id"] for item in result["items"]}
        for entry in entries:
            if entry.id in returned and entry.id not in overlay:
                work.references[entry.id] = entry.revision
        work.read_calls[context.tool_call_id] = list(returned)
        self.service.store.track(context.session_id, returned - set(overlay))
        return result

    def check(self, work):
        if work is None:
            return
        view = self.service.view(work.view.session_id)
        if view != work.view:
            raise ToolExecutionError("MEMORY_VIEW_CHANGED", "Memory access changed. Please try again.")
        for memory_id, revision in work.references.items():
            entry = self.service.store.get(memory_id)
            if entry is None or entry.revision != revision or not self.service.store.visible(entry, view):
                raise ToolExecutionError("MEMORY_VIEW_CHANGED", "A recalled memory changed. Please try again.")

    def recall(self, context, trace, work, query, input_budget):
        if work is None:
            return context, trace
        self.check(work)
        work.allowance = min(1024, max(0, input_budget // 10))
        pinned, _ = self.service.store.query(view=work.view, filters={"pinned": True}, limit=8)
        matches, _ = self.service.store.query(view=work.view, query=query, limit=16) if query.strip() else ([], 0)
        recent, total = self.service.store.query(view=work.view, limit=20)
        selected = []
        seen = set()
        for reason, entries in (("pinned", pinned), ("literal", matches), ("recent", recent if total <= 20 else recent[:3])):
            for entry in entries:
                if entry.id not in seen:
                    seen.add(entry.id)
                    selected.append((reason, entry))
        result, provenance = deepcopy(context), trace.model_copy(deep=True)
        sources = []
        count = self.models.reference_tokens.count_text
        empty_cost = count(render_memory_index()[0])
        for reason, entry in selected:
            source = ContextSource(id="memory:" + entry.id, kind="durable_memory", role="system",
                reference_id=entry.id, name=" ".join(entry.summary.split()), memory=reference(entry, reason))
            text, _ = render_memory_index([*sources, source], limited=total > len(sources) + 1)
            if count(text) - empty_cost > work.allowance:
                provenance.exclusions.append(ContextExclusion(kind="durable_memory", reason="token_limit", reference_id=entry.id))
                continue
            sources.append(source)
            work.references[entry.id] = entry.revision
        root = next(source for source in provenance.sources if source.kind == "memory_index")
        result[root.message_index]["content"] = replace_memory_index(result[root.message_index]["content"],
            provenance, sources, limited=total > len(sources))
        # Record dependencies before dispatch; later edits invalidate the Run view,
        # including an approval continuation whose context is already materialized.
        self.service.store.track(work.view.session_id, work.references)
        return result, provenance

    def stage(self, operation, arguments, context):
        state = context.harness_state
        work = state.memory
        self.check(work)
        run = self.runs.get_run(context.run_id)
        config = self.runs.get_config_snapshot(run.run_id)
        if config.get("memory_learning") != "automatic":
            raise ToolExecutionError("MEMORY_LEARNING_DISABLED", "Automatic memory learning is disabled.")
        prior = next((item for item in work.mutations if item.tool_call_id == context.tool_call_id), None)
        if prior:
            return {"id": prior.entry.id}
        if len(work.mutations) >= 8:
            raise ToolExecutionError("MEMORY_WRITE_LIMIT", "A run can propose at most eight memory changes.")
        current = None
        memory_id = arguments.get("id")
        if memory_id:
            candidate = next((item.entry for item in reversed(work.mutations) if item.entry.id == memory_id), None)
            current = candidate or self.service.store.get(memory_id)
            if (current is None or current.status == "deleted" or current.managed_by != "model"
                or current.pool != "character" or current.session_id != run.session_id
                or current.character_id != run.character_id or current.persona_id != run.persona_id):
                raise ToolExecutionError("MEMORY_NOT_WRITABLE", "This memory cannot be changed with memory tools.")
            if candidate is None:
                expected = work.references.get(memory_id)
                if expected is None:
                    raise ToolExecutionError("MEMORY_READ_REQUIRED", "Read this memory before changing it.")
                if current.revision != expected:
                    raise ToolExecutionError("MEMORY_CONFLICT", "The memory changed. Read it again before updating it.")
        if operation == "memory_forget":
            entry = forget(current)
        else:
            values = MemoryWrite.model_validate(arguments)
            if current:
                entry = current.model_copy(update={"summary": values.summary, "body": values.body,
                    "revision": current.revision + 1, "status": "active", "updated_at": utc_now(),
                    "origin": current.origin.model_copy(update={"run_id": run.run_id, "evidence": []})})
            else:
                entry = MemoryEntry(pool="character", character_id=run.character_id, persona_id=run.persona_id,
                    session_id=run.session_id, managed_by="model", summary=values.summary, body=values.body,
                    origin=MemoryOrigin(character_id=run.character_id, persona_id=run.persona_id,
                        session_id=run.session_id, run_id=run.run_id))
                # Exact reuse is local to this origin and audience; no cross-session deduplication.
                existing_records = {existing.id: existing for existing in self.service._all({"pool": "character", "session_id": run.session_id,
                    "persona_id": run.persona_id, "status": "active"})}
                existing_records.update((mutation.entry.id, mutation.entry) for mutation in work.mutations)
                for existing in existing_records.values():
                    if existing.status != "active":
                        continue
                    if existing.summary == entry.summary and existing.body == entry.body:
                        if not any(mutation.entry.id == existing.id for mutation in work.mutations):
                            work.references[existing.id] = existing.revision
                            self.service.store.track(context.session_id, [existing.id])
                        return {"id": existing.id}
        work.mutations.append(MemoryMutation(tool_call_id=context.tool_call_id,
            operation="forget" if operation == "memory_forget" else "write", entry=entry,
            expected_revision=current.revision if current else None))
        return {"id": entry.id}

    def validate_commit(self, work, run, transaction):
        self.check(work)
        session = self.service.chat.sessions.get_session(run.session_id)
        settings = self.service.chat.settings(session)
        if (session.history_version != work.history_version or session.bound_persona_id != run.persona_id
            or not settings.memory_enabled or settings.memory_learning != "automatic"):
            raise ToolExecutionError("MEMORY_SOURCE_CHANGED", "Memory inputs or learning settings changed before commit.")
        versions = {}
        for mutation in work.mutations:
            entry = mutation.entry
            current = versions.get(entry.id) or self.service.store.get(entry.id, transaction=transaction)
            if ((current.revision if current else None) != mutation.expected_revision
                or current and (current.status == "deleted" or current.managed_by != "model")):
                raise ToolExecutionError("MEMORY_CONFLICT", "A memory was edited or forgotten before commit.")
            if (entry.character_id, entry.persona_id, entry.session_id, entry.pool) != (
                    run.character_id, run.persona_id, run.session_id, "character"):
                raise ToolExecutionError("MEMORY_OWNER_MISMATCH", "A pending memory has another owner.")
            versions[entry.id] = entry

    def commit_candidates(self, work, run, transaction):
        if work is None or not work.mutations:
            return None
        try:
            self.validate_commit(work, run, transaction)
        except (ChatError, ToolExecutionError) as exc:
            return {"status": "not_saved", "code": exc.code, "count": len(work.mutations)}
        for mutation in work.mutations:
            self.service.store.save(mutation.entry, mutation.expected_revision, transaction=transaction)
        return {"status": "saved", "count": len(work.mutations)}
