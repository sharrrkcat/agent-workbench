"""Commit memory, working checkpoints and the terminal Run event together."""

import json
from uuid import uuid4

from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.time import utc_now
from ai_workbench.db.models import RunRecord, RunEventRecord, SessionRecord, ContextRetrievalRecord
from ai_workbench.db.stores import _run


def complete_memory_run(loop, run_id, state):
    memory = loop.durable_memory
    store = memory.service.store
    current = loop.runs.get_run(run_id)
    if current.status == RunStatus.DONE:
        return
    with store.transaction(conversation=True) as db:
        outcome = memory.commit_candidates(state.memory, current, db)
        # A conflicting memory commit cannot make a stale checkpoint valid.
        retrieval = state.retrieval
        if db is not None:
            row = db.get(RunRecord, run_id)
            if row.status not in {RunStatus.PENDING.value, RunStatus.RUNNING.value} or row.cancel_requested:
                raise ValueError("Only a running, uncancelled Run can complete")
            metadata = json.loads(row.metadata_json)
            if outcome is not None:
                metadata["memory"] = outcome
            row.metadata_json = json.dumps(metadata, ensure_ascii=False)
            row.harness_state_json = "{}"
            row.status = "DONE"
            row.current_step = row.stage = "done"
            row.updated_at = row.finished_at = utc_now()
            if retrieval is not None and retrieval.history_enabled and (outcome is None or outcome["status"] == "saved"):
                session = db.get(SessionRecord, current.session_id)
                if session.history_version == retrieval.session.history_version and (
                    state.memory is None or session.memory_version == state.memory.view.version):
                    db.merge(ContextRetrievalRecord(session_id=current.session_id, state_json=retrieval.session.model_dump_json()))
            db.add(row)
            db.flush()
            payload = {"run": _run(row).model_dump(mode="json")}
            db.add(RunEventRecord(event_id=str(uuid4()), run_id=run_id, session_id=current.session_id,
                type="run_completed", payload_json=json.dumps(payload, ensure_ascii=False)))
        else:
            if current.status not in {RunStatus.PENDING, RunStatus.RUNNING} or current.cancel_requested:
                raise ValueError("Only a running, uncancelled Run can complete")
            if outcome is not None:
                loop.runs.update_metadata(run_id, {**current.metadata, "memory": outcome})
            if retrieval is not None and (outcome is None or outcome["status"] == "saved"):
                session = loop.sessions.get_session(current.session_id)
                if state.memory is None or session.memory_version == state.memory.view.version:
                    loop.retrieval.commit(retrieval)
            loop.runs.update_harness_state(run_id, {})
            finished = loop.runs.update_status(run_id, RunStatus.DONE, current_step="done")
            payload = {"run": finished.model_dump(mode="json")}
            loop.events.run_event_store.add_event(run_id=run_id, session_id=current.session_id,
                type="run_completed", payload=payload)
    loop.events.emit("run_completed", run_id=run_id, session_id=current.session_id, payload=payload, persisted=True)
