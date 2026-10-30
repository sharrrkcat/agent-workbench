"""Replay saved web evidence; --live runs isolated chats with the saved provider/key."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import re
from pathlib import Path
import sqlite3
import sys

import httpx
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_workbench.api.main import create_app
from ai_workbench.core.harness import ToolRegistry
from ai_workbench.core.harness.schema import ToolExecutionError
from unittest.mock import patch
from datetime import datetime
from ai_workbench.core.harness.schema import ToolExecutionContext
from ai_workbench.core.instructions import date_instruction
from ai_workbench.core.models.store import ModelProfileStore, ProviderProfileStore
from ai_workbench.core.models.token_counting import estimate_input_tokens
from ai_workbench.core.personas import PersonaStore
from ai_workbench.core.schema.persona import PersonaCreate, USER_PERSONA_ID
from ai_workbench.core.time import utc_now
from ai_workbench.core.web_content import normalize_url, clean_content, page_title, QueryRelevance, infer_date, is_expired, BM25, paragraphs
from ai_workbench.core.web_render import web_model_text
from ai_workbench.core.web_schemas import ProviderFetchResult, ProviderSearchResult, WebPage, WebToolsSettingsPatch
from ai_workbench.core.web_tools import CITATION_INSTRUCTION, WEB_CONTENT_INSTRUCTION, WebToolsService, WebToolsSettingsStore


def baseline(database: Path, session_id: str):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        session = dict(db.execute("SELECT * FROM sessionrecord WHERE session_id=?", (session_id,)).fetchone())
        parts = [part for row in db.execute("SELECT parts_json FROM messagerecord WHERE session_id=? ORDER BY created_at", (session_id,))
                 for part in json.loads(row[0])]
        pages = [dict(row) for row in db.execute("SELECT p.* FROM web_pages p WHERE EXISTS "
            "(SELECT 1 FROM web_session_pages s WHERE s.url_key=p.url_key AND s.session_id=?)", (session_id,))]
        snapshots = [json.loads(row[0]) for row in db.execute("SELECT s.context_snapshot_json FROM runsteprecord s "
            "JOIN runrecord r ON r.run_id=s.run_id WHERE r.session_id=? AND s.kind='model' ORDER BY s.created_at", (session_id,))]
    return session, {"session": session_id, "parts": parts, "pages": pages, "snapshots": snapshots}


class ReplayProvider:
    def __init__(self, saved):
        self.searches, self.fetches = {}, {}
        cache = {normalize_url(page["raw_url"]): page for page in saved["pages"]}
        self.results = {part["tool_call_id"]: part for part in saved["parts"] if part["type"] == "tool_result"}
        for part in self.results.values():
            if part["status"] != "success":
                continue
            data = part["data"]
            if part["tool_name"] == "web_search":
                for index, query in enumerate(data["searches"]):
                    pages = []
                    for page in data["results"]:
                        if index not in page["matched_queries"]:
                            continue
                        stored = cache.get(normalize_url(page["url"]))
                        content = stored["content"] if stored and stored["content_src"] == "search" else page["content"]
                        pages.append(WebPage(url=page["url"], title=page["title"], content=content))
                    self.searches[query["query"]] = pages
            elif part["tool_name"] == "web_fetch":
                self.fetches[normalize_url(data["url"])] = ProviderFetchResult(provider="replay", url=data["url"],
                    title=data["title"], content=data["content"])

    async def search(self, request, api_key):
        return ProviderSearchResult(provider="replay", query=request.query, results=self.searches[request.query])

    async def fetch(self, request, api_key):
        return self.fetches[normalize_url(request.url)]


def rankings(provider, arguments, acquired):
    # This diagnostic corpus contains saved displayed pages, not discarded provider candidates.
    pages = {normalize_url(page.url): page for query in arguments["searches"] for page in provider.searches[query["query"]]}
    entries = []
    for page in pages.values():
        title = page_title(page.content, page.title, page.url)
        body = clean_content(page.content, title, page.url)[0]
        entries.append((page.url, title, body))
    texts = [title + "\n" + body for _, title, body in entries]
    parts = [paragraphs(body) for _, _, body in entries]
    ranker = BM25([part.text for group in parts for part in group])
    output = []
    for query in arguments["searches"]:
        relevance, offset = QueryRelevance(query["query"], texts), 0
        for index, (url, title, body) in enumerate(entries):
            coverage = relevance.coverage(index)
            date = infer_date(url, body, acquired.astimezone().date(), acquired)
            expired = is_expired(date, query.get("recency", "any"), acquired.astimezone().date())
            missing = sorted(relevance.query.required - relevance.matches[index])
            score = sum(sorted((ranker.score(offset+i, relevance.query.words) for i in range(len(parts[index]))), reverse=True)[:2])
            offset += len(parts[index])
            output.append({"query": query["query"], "url": url, "title": title, "coverage": coverage, "bm25": score,
                "missing_required": missing, "date": date.model_dump(),
                "decision": "missing_required" if missing else "low_coverage" if coverage < .6 else "expired" if expired else "eligible"})
    return output


async def replay(question, saved):
    provider = ReplayProvider(saved)
    settings = WebToolsSettingsStore()
    settings.patch(WebToolsSettingsPatch(api_key="offline-replay"))
    web = WebToolsService(settings, provider)
    registry = ToolRegistry()
    web.register(registry)
    context = ToolExecutionContext(session_id="offline-replay", web_sources={})
    request = {"messages": [{"role": "system", "content": date_instruction("en", utc_now().astimezone().date())},
                            {"role": "user", "content": question}],
               "tools": [{"type": "function", "function": {"name": spec.name, "description": spec.description,
                          "parameters": spec.parameters}} for spec in registry.list()]}
    request["tools"][0]["function"]["description"] += " " + WEB_CONTENT_INSTRUCTION + " " + CITATION_INSTRUCTION
    records, peaks = [], []
    for call in (part for part in saved["parts"] if part["type"] == "tool_call"):
        name, arguments = call["tool_name"], call["arguments"]
        original = provider.results[call["tool_call_id"]]
        acquired = datetime.fromisoformat(original["data"]["retrieved_at"].replace("Z", "+00:00"))
        request["messages"].append({"role": "assistant", "content": None, "tool_calls": [{"id": call["tool_call_id"],
            "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]})
        field = "searches_used" if name == "web_search" else "fetches_used"
        setattr(context.web_budget, field, getattr(context.web_budget, field) + 1)
        with patch("ai_workbench.core.web_tools.utc_now", return_value=acquired):
            try:
                data = await registry.execute(name, arguments, context)
                status, error = "success", None
            except ToolExecutionError as exc:
                data, status, error = {}, "error", exc.code
            text, truncated = web_model_text(name, status, data, error)
        assert len(text) <= (5000 if name == "web_search" else 4500) and not truncated
        request["messages"].append({"role": "tool", "tool_call_id": call["tool_call_id"], "content": text})
        record = {"tool": name, "status": status, "error_code": error, "output_chars": len(text), "data": data}
        if name == "web_search":
            record["rankings"] = rankings(provider, arguments, acquired)
        records.append(record)
        peaks.append(estimate_input_tokens(request))
    return {"limitation": "Only saved displayed results are replayed; the original discarded provider candidates are unavailable. "
            "Ranking diagnostics use that reduced corpus; fixed tests separately cover complete candidate sets.",
            "estimated_input_tokens_by_call": peaks, "estimated_peak_input_tokens": max(peaks),
            "tool_calls": dict(Counter(item["tool"] for item in records)), "results": records}


async def live(database, session, question, output):
    # Only saved model/provider/persona/settings reads touch the source DB. No QQ bindings are copied.
    source = create_engine("sqlite:///" + database.resolve().as_uri() + "?mode=ro&uri=true")
    config = json.loads(session["configuration_json"])
    profile = ModelProfileStore(source).get(config["model_profile_id"])
    if profile.source is None or profile.source.type != "provider":
        raise ValueError("Live acceptance requires the baseline's external LLM profile")
    provider = ProviderProfileStore(source).get(profile.source.provider_profile_id)
    personas = PersonaStore(source)
    agent = personas.get(config["persona_id"])
    user = personas.get(USER_PERSONA_ID)
    settings = WebToolsSettingsStore(source).get()
    source.dispose()
    app = create_app(use_memory=True, root=output / "runtime")
    state = app.state.runtime_state
    state.provider_profiles.create(provider)
    state.model_profiles.create(profile)
    copied_agent = state.personas.create(PersonaCreate(name=agent.name, system_prompt=agent.system_prompt, collection="agent"))
    state.personas.update(USER_PERSONA_ID, {"name": user.name, "system_prompt": user.system_prompt})
    state.web_tools.settings.patch(WebToolsSettingsPatch(**settings.model_dump(exclude={"provider"})))
    config["persona_id"] = copied_agent.id
    config["tools_allowed"] = ["web_search", "web_fetch"]
    reports = []
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://acceptance") as client:
        for label, prompt in [("baseline-question", question), ("insufficient-evidence",
            "剑网3在2028年10月30日将上线的赛季，官方确定会赠送多少小时点卡和哪些限定坐骑？")]:
            response = await client.post("/api/sessions", json=config)
            response.raise_for_status()
            sid = response.json()["session_id"]
            print(f"Live acceptance started: {label}, session={sid}", flush=True)
            response = await client.post(f"/api/sessions/{sid}/messages", json={"content": prompt}, headers={"X-UI-Language": "zh-CN"})
            response.raise_for_status()
            payload = response.json()
            run_id = payload["run"]["run_id"]
            steps = state.runs.list_steps(run_id)
            model_calls = []
            for step in steps:
                if step.kind != "model":
                    continue
                usage = step.metadata.get("llm", {}).get("usage") or {}
                model_calls.append({"round": step.metadata.get("round"), "prompt_tokens": usage.get("prompt_tokens"),
                    "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                    "estimated_input_tokens": step.metadata.get("context", {}).get("budget", {}).get("input_tokens")})
            messages = state.messages.messages_for_run(run_id)
            tool_results = [part for message in messages for part in message.parts if part["type"] == "tool_result"]
            answers = ["\n".join(part["text"] for part in message.parts if part["type"] == "text")
                       for message in messages if message.role == "assistant"]
            actual = [call["prompt_tokens"] for call in model_calls if call["prompt_tokens"] is not None]
            report = {"label": label, "session_id": sid, "run_id": run_id, "model": profile.alias,
                "status": payload["run"]["status"], "error_code": payload["run"].get("error_code"),
                "model_calls": model_calls, "peak_prompt_tokens": max(actual) if actual else None,
                "answer": answers[-1] if answers else "", "tool_results": tool_results,
                "tool_metrics": [{"tool_name": step.metadata["tool_name"], **step.metadata["web"]}
                                 for step in steps if "web" in step.metadata]}
            report["passed_size_and_completion"] = (report["status"] == "DONE" and len(actual) == len(model_calls)
                and max(actual, default=40001) <= 40000 and all(metric["output_chars"] <=
                    (5000 if metric["tool_name"] == "web_search" else 4500) for metric in report["tool_metrics"]))
            source_ids = {page["source_id"] for part in tool_results if part["status"] == "success"
                for page in part["data"].get("results", [part["data"]]) if page.get("source_id")}
            report["invalid_source_ids"] = sorted(set(re.findall(r"\[(W[1-9]\d*)\]", report["answer"])) - source_ids)
            report["passed_source_ids"] = not report["invalid_source_ids"]
            (output / f"{label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({key: report[key] for key in ("label", "status", "peak_prompt_tokens", "passed_size_and_completion", "passed_source_ids")}), flush=True)
            reports.append(report)
    return reports


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/cogita.db")
    parser.add_argument("--session", required=True, help="Saved baseline session containing original provider page results")
    parser.add_argument("--output", type=Path, default=ROOT / "build/web-research-acceptance")
    parser.add_argument("--live", action="store_true", help="Send billable requests using saved provider and AnySearch settings")
    parser.add_argument("--replay-input", type=Path, help="Saved baseline.json captured before cache cleanup")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session, saved = baseline(args.database, args.session)
    if args.replay_input:
        saved = json.loads(args.replay_input.read_text(encoding="utf-8"))
    else:
        (args.output / "baseline.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    question = next(part["text"] for part in saved["parts"] if part["type"] == "text")
    results = [part for part in saved["parts"] if part["type"] == "tool_result"]
    report = {"baseline_session": args.session, "baseline_tool_calls": dict(Counter(part["tool_name"] for part in results)),
        "baseline_estimated_input_tokens": [item["budget"]["input_tokens"] for item in saved["snapshots"]]}
    report["replay"] = await replay(question, saved)
    (args.output / "offline-replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"offline_estimated_peak_input_tokens": report["replay"]["estimated_peak_input_tokens"],
                      "tool_calls": report["replay"]["tool_calls"]}), flush=True)
    if args.live:
        live_reports = await live(args.database, session, question, args.output)
        return 0 if all(item["passed_size_and_completion"] and item["passed_source_ids"] for item in live_reports) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
