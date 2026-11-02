"""Compare bounded history reads in fresh processes without loading any models."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import gc
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def measure(rows: int, strategy: str = 'token_budget'):
    import psutil
    from sqlalchemy import insert
    from sqlmodel import SQLModel
    from ai_workbench.core.context import ContextBuilder
    from ai_workbench.core.context_compaction import ContextCompactionService
    from ai_workbench.core.history_retrieval import HistoryRetrieval
    from ai_workbench.core.schema.context_budget import ContextBudgetStats
    from ai_workbench.core.schema.context_policy import ContextPolicy
    from ai_workbench.core.history_page import HistoryQuery
    from ai_workbench.db.database import get_engine
    from ai_workbench.db.history_page import SqlHistoryReader
    from ai_workbench.db.models import MessageRecord
    from ai_workbench.db.stores import SqlSessionStore, SqlMessageStore

    with TemporaryDirectory(prefix="cogita-history-memory-") as root:
        engine = get_engine(f"sqlite:///{Path(root) / 'history.db'}")
        SQLModel.metadata.create_all(engine)
        sessions = SqlSessionStore(engine)
        session = sessions.create_session()
        sid = session.session_id
        beginning = datetime(2026, 1, 1, tzinfo=timezone.utc)
        parts = json.dumps([{"id": "t", "type": "text", "text": "x" * 1024}])
        with engine.begin() as connection:
            for start in range(0, rows, 1000):
                connection.execute(insert(MessageRecord), [{"message_id": f"m-{i:08}", "session_id": sid,
                    "role": "user", "parts_json": parts, "created_at": beginning + timedelta(seconds=i)}
                    for i in range(start, min(rows, start + 1000))])
        messages, reader = SqlMessageStore(engine), SqlHistoryReader(engine)
        current = messages.add_message(sid, 'user', 'current')
        class CountOnly:
            async def measure_chat(self, _profile, request, _limits):
                return ContextBudgetStats(configured_window_tokens=4096, window_tokens=4096,
                    input_budget_tokens=2662, input_tokens=len(request.model_dump_json()) // 4,
                    counting='estimated', output_tokens=1024, margin_tokens=410, removed_turns=0)
        compaction = ContextCompactionService(sessions=sessions, messages=messages, runs=None, events=None, model_manager=CountOnly())
        if strategy == 'history_retrieval':
            class MeasuredRetrieval(HistoryRetrieval):
                def record_reset(self, *args, **kwargs):
                    pass  # Measure selection memory independently of snapshot persistence.
            compaction = MeasuredRetrieval(sessions, messages,
                SimpleNamespace(update_harness_state=lambda *_: None), None, CountOnly())
        policy = ContextPolicy(strategy=strategy, message_window={'max_messages': 5}, compaction={'enabled': False})
        config = SimpleNamespace(context_policy=policy, context_limits=None, harness_enabled=True,
            generation=SimpleNamespace(model_dump=lambda **_: {}))
        profile = SimpleNamespace(id='count-only', alias='count-only',
            request_options=SimpleNamespace(skip_vision_capability_check=False))
        support = SimpleNamespace(vision=SimpleNamespace(state='unsupported'))
        def read():
            built = ContextBuilder(messages).build(sid, 'current', current_message_id=current.message_id)
            context, trace, _ = asyncio.run(compaction.prepare(session=session, config=config, run=SimpleNamespace(run_id='memory-check'),
                base=built.messages, trace=built.trace, current=current, profile=profile, support=support,
                max_image_bytes=1024, reasoning=False))
            page = reader.page(sid, HistoryQuery())
            return len(context), len(page["items"]), len(trace.exclusions)
        for _ in range(2):
            read()
        gc.collect()
        process = psutil.Process()
        before_rss = process.memory_info().rss
        tracemalloc.start()
        measurements = []
        for _ in range(3):
            tracemalloc.reset_peak()
            baseline = tracemalloc.get_traced_memory()[0]
            selected, displayed, exclusions = read()
            measurements.append(tracemalloc.get_traced_memory()[1] - baseline)
            gc.collect()
        result = {"rows": rows, "peak_python_bytes": max(measurements), "rss_before": before_rss,
                  "rss_after": process.memory_info().rss, "context_messages": selected, "history_items": displayed,
                  "exclusion_groups": exclusions}
        tracemalloc.stop()
        engine.dispose()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int)
    parser.add_argument("--strategy", choices=('token_budget', 'message_window', 'history_retrieval'), default='token_budget')
    parser.add_argument("--output", type=Path, default=Path("build/history-memory.json"))
    args = parser.parse_args()
    if args.rows:
        print(json.dumps(measure(args.rows, args.strategy)))
        return
    reports = [json.loads(subprocess.check_output([sys.executable, str(Path(__file__).resolve()), "--rows", str(rows), '--strategy', args.strategy], text=True))
               for rows in (10000, 100000)]
    ratio = reports[1]["peak_python_bytes"] / reports[0]["peak_python_bytes"]
    result = {"strategy": args.strategy, "measurements": reports, "peak_ratio": ratio, "passed": ratio <= 2
              and all(row["history_items"] == 50 and row["context_messages"] <= 101 and row["exclusion_groups"] <= 3 for row in reports)
              and (args.strategy != 'message_window' or all(row['context_messages'] == 6 for row in reports))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
