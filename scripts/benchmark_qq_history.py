"""Compare bounded QQ HTTP reads with the former request pattern in disposable SQLite databases.

Run: uv run python -m scripts.benchmark_qq_history --output build/qq-history-benchmark.json
No provider calls, OneBot connection, model loading or application lifespan is started.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from math import ceil
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, insert
from sqlmodel import Session, select

from ai_workbench.api.deps import build_runtime_state
from ai_workbench.api.routes import qq, tools
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.character import QQBotCharacter
from ai_workbench.db.models import MessageRecord, RunRecord, RunStepRecord
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery


def distribution(values):
    return {"p50_ms": round(median(values), 2), "p95_ms": round(sorted(values)[ceil(len(values) * .95) - 1], 2)}


def seed(state, count):
    character = QQBotCharacter(kind="qqbot", name="Benchmark", context_policy=ContextPolicy(), bot_account="12345", websocket_url="ws://127.0.0.1:1")
    state.characters.save(character)
    session = state.sessions.create_session(kind="qqbot", character_id=character.id, target_kind="group", target_id="7788")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with state.qq.store.engine.begin() as db:
        db.execute(insert(QQBinding), dict(session_id=session.session_id, character_id=character.id, target_kind="group", target_id="7788"))
        for offset in range(0, count, 5000):
            db.execute(insert(QQMessage), [dict(id=i, session_id=session.session_id, external_id=str(i), sender_id="7", sender_name="Participant",
                timestamp=(start + timedelta(seconds=i)).isoformat(), text=f"Input {i}: " + "text " * 20, disposition="batched", batch_id=(i - 1) // 10 + 1)
                for i in range(offset + 1, min(offset + 5000, count) + 1)])
        for offset in range(0, count // 10, 1000):
            ids = range(offset + 1, min(offset + 1000, count // 10) + 1)
            db.execute(insert(RunRecord), [dict(run_id=f"run-{i:06}", session_id=session.session_id, kind="chat", persona_id="", status="DONE",
                created_at=start + timedelta(seconds=i * 10, microseconds=500000), metadata_json='{"harness":true}',
                config_snapshot_json=json.dumps({"private": "context " * 100}), harness_state_json="{}") for i in ids])
            db.execute(insert(QQBatch), [dict(id=i, session_id=session.session_id, character_id=character.id, status="done", text="batch " * 100,
                run_id=f"run-{i:06}", created_at=(start + timedelta(seconds=i * 10)).timestamp()) for i in ids])
            db.execute(insert(QQDelivery), [dict(id=i, session_id=session.session_id, run_id=f"run-{i:06}", tool_call_id=f"call-{i}", status="sent",
                text="A confirmed QQ reply.", created_at=(start + timedelta(seconds=i * 10 + 1)).timestamp()) for i in ids])
            db.execute(insert(RunStepRecord), [dict(step_id=f"step-{i:06}", run_id=f"run-{i:06}", kind="model", status="completed",
                message="processing " * 100, context_snapshot_json=json.dumps({"private": "input " * 1000})) for i in ids])
            db.execute(insert(MessageRecord), [dict(message_id=f"message-{i:06}", session_id=session.session_id, run_id=f"run-{i:06}", role="assistant",
                speaker_type="assistant", speaker_id="", parts_json=json.dumps([{"id": "body", "type": "text", "text": "Internal processing. " * 50}]),
                metadata_json='{"qq_internal":true}') for i in ids])
    return character.id, session.session_id


def measure(count, iterations):
    with TemporaryDirectory(prefix="cogita-qq-benchmark-") as directory:
        root = Path(directory)
        state = build_runtime_state(root=root, database_url=f"sqlite:///{root / 'benchmark.db'}")
        character_id, session_id = seed(state, count)
        engine = state.qq.store.engine
        app = FastAPI()
        app.state.runtime_state = state
        app.include_router(qq.router)
        app.include_router(tools.router)

        # Benchmark-only endpoints reproduce the old fan-out, not application compatibility routes.
        @app.get("/__benchmark__/binding")
        def binding():
            return qq.binding_response(state, state.qq.store.get(QQBinding, session_id))

        @app.get("/__benchmark__/{kind}")
        def records(kind: str):
            model = {"messages": QQMessage, "batches": QQBatch, "deliveries": QQDelivery}[kind]
            with Session(engine) as db:
                query = select(model).where(model.session_id == session_id)
                if model in (QQMessage, QQDelivery):
                    query = query.where(model.deleted == False)
                rows = db.exec(query.order_by(model.id.desc()).limit(51)).all()
                return {"items": [row.model_dump(exclude={"deleted", "image_generation_keyword"}) for row in rows[:50]],
                    "next_cursor": rows[49].id if len(rows) > 50 else None}

        indexes = [index for table in (QQMessage.__table__, QQBatch.__table__, QQDelivery.__table__)
            for index in table.indexes if index.name in {"ix_qq_message_timeline", "ix_qq_batch_active_session", "ix_qq_program_timeline", "ix_qq_program_delivery_pending"}]
        sql_count = [0]
        def counted(*_):
            sql_count[0] += 1
        event.listen(engine, "before_cursor_execute", counted)
        results = {}
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=6) as pool:
            def get(url):
                response = client.get(url)
                response.raise_for_status()
                return response
            def former():
                base = list(pool.map(get, [f"/__benchmark__/{kind}" for kind in ("binding", "messages", "batches", "deliveries")]))
                ids = {row["run_id"] for response in base[2:] for row in response.json()["items"] if row["run_id"]}
                details = list(pool.map(get, [f"/api/tools/runs/{id}" for id in ids]))
                return 4 + len(ids), sum(len(response.content) for response in [*base, *details])
            def current():
                response = get(f"/api/qq/sessions/{session_id}/history")
                assert len(response.json()["items"]) == 50
                return 1, len(response.content)
            for index in indexes:
                index.drop(engine)
            for label, read in (("former_request_pattern", former), ("unified_history", current)):
                if label == "unified_history":
                    for index in indexes:
                        index.create(engine)
                read()
                times, statements, polling = [], [], []
                for _ in range(iterations):
                    sql_count[0] = 0
                    start = perf_counter()
                    requests, size = read()
                    times.append((perf_counter() - start) * 1000)
                    statements.append(sql_count[0])
                    start = perf_counter()
                    assert state.qq.programs.next_delivery(character_id) is None
                    polling.append((perf_counter() - start) * 1000)
                results[label] = {**distribution(times), "http_requests": requests, "response_bytes": size,
                    "sql_statements": max(statements), "idle_program_lookup": distribution(polling)}
        event.remove(engine, "before_cursor_execute", counted)
        state.events.close()
        engine.dispose()
        return {"incoming_messages": count, "runs": count // 10, **results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/qq-history-benchmark.json"))
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    report = {"environment": "Local warm SQLite/ASGI; former HTTP requests use six concurrent connections; no WAN or inference.",
        "results": [measure(count, args.iterations) for count in (10_000, 100_000)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
