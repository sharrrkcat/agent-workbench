from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StatelessPersistenceSnapshot:
    sessions: int
    messages: int
    runs: int
    run_steps: int
    run_events: int
    session_agent_state: int
    knowledge_sources: int
    knowledge_chunks: int
    knowledge_embeddings: int
    session_knowledge_bindings: int
    attachment_files: int


def capture_stateless_persistence_snapshot(state: Any) -> StatelessPersistenceSnapshot:
    return StatelessPersistenceSnapshot(
        sessions=len(_list_or_empty(state.sessions, "list_sessions")),
        messages=len(_list_or_empty(state.messages, "list_all_messages")),
        runs=len(_list_or_empty(state.runs, "list_all_runs")),
        run_steps=_count_run_steps(state),
        run_events=_count_run_events(state),
        session_agent_state=_count_session_agent_state(state),
        knowledge_sources=_count_knowledge_sources(state),
        knowledge_chunks=_count_knowledge_chunks(state),
        knowledge_embeddings=_count_knowledge_embeddings(state),
        session_knowledge_bindings=_count_session_knowledge_bindings(state),
        attachment_files=_count_attachment_files(),
    )


def assert_snapshot_unchanged(before: StatelessPersistenceSnapshot, after: StatelessPersistenceSnapshot) -> None:
    if before != after:
        raise AssertionError(f"Stateless persistence changed: before={before!r} after={after!r}")


def _list_or_empty(target: Any, method_name: str) -> list:
    method = getattr(target, method_name, None)
    if callable(method):
        return list(method())
    return []


def _count_run_steps(state: Any) -> int:
    runs = _list_or_empty(state.runs, "list_all_runs")
    return sum(len(state.runs.list_steps(run.run_id)) for run in runs if hasattr(state.runs, "list_steps"))


def _count_run_events(state: Any) -> int:
    runs = _list_or_empty(state.runs, "list_all_runs")
    store = getattr(state, "run_events", None)
    if not hasattr(store, "list_events"):
        return 0
    return sum(len(store.list_events(run.run_id)) for run in runs)


def _count_session_agent_state(state: Any) -> int:
    store = getattr(state, "session_agent_states", None)
    records = getattr(store, "_records", None)
    if isinstance(records, dict):
        return len(records)
    return 0


def _count_knowledge_sources(state: Any) -> int:
    knowledge = getattr(state, "knowledge", None)
    if not hasattr(knowledge, "list_knowledge_bases") or not hasattr(knowledge, "list_sources"):
        return 0
    return sum(len(knowledge.list_sources(kb.id)) for kb in knowledge.list_knowledge_bases())


def _count_knowledge_chunks(state: Any) -> int:
    knowledge = getattr(state, "knowledge", None)
    chunks = getattr(knowledge, "_chunks", None)
    if isinstance(chunks, dict):
        return len(chunks)
    return 0


def _count_knowledge_embeddings(state: Any) -> int:
    knowledge = getattr(state, "knowledge", None)
    embeddings = getattr(knowledge, "_embeddings", None)
    if isinstance(embeddings, dict):
        return len(embeddings)
    return 0


def _count_session_knowledge_bindings(state: Any) -> int:
    knowledge = getattr(state, "knowledge", None)
    bindings = getattr(knowledge, "_bindings", None)
    if isinstance(bindings, dict):
        return len(bindings)
    sessions = _list_or_empty(state.sessions, "list_sessions")
    if hasattr(knowledge, "list_session_bindings"):
        return sum(len(knowledge.list_session_bindings(session.session_id)) for session in sessions)
    return 0


def _count_attachment_files() -> int:
    try:
        from ai_workbench.core.attachments import attachments_root

        root = attachments_root()
    except Exception:
        return 0
    if not root.exists():
        return 0
    return sum(1 for path in Path(root).rglob("*") if path.is_file())
