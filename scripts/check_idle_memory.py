"""Measure full server startup and idle recovery with isolated, offline workloads."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

RESULT_PREFIX = "IDLE_MEMORY_RESULT "
ROOT = Path(__file__).resolve().parents[1]


def memory(process):
    def sample(item):
        info = item.memory_full_info()
        return {"pid": item.pid, "rss": info.rss, "pss": getattr(info, "pss", None),
                "swap": getattr(info, "swap", None)}
    value = sample(process)
    value["children"] = [sample(child) for child in process.children(recursive=True)]
    return value


def summarize(samples):
    rss = sorted(item["rss"] for item in samples)
    return {"samples": samples, "rss_median": statistics.median(rss), "rss_max": max(rss),
            "rss_p95": rss[min(len(rss) - 1, int(len(rss) * .95))],
            "child_rss_max": max(sum(child["rss"] for child in item["children"]) for item in samples)}


class MockProvider:
    """Deterministic OpenAI responses; no saved provider configuration is read."""
    def __init__(self):
        self.calls = 0

    def factory(self, provider):
        import httpx
        from ai_workbench.core.models.openai_adapter import OpenAIAdapter
        return OpenAIAdapter(provider, transport=httpx.MockTransport(self.respond))

    async def respond(self, request):
        import httpx
        body = json.loads(request.content)
        self.calls += 1
        qq = any(tool["function"]["name"] == "qq_send_message" for tool in body.get("tools", []))
        message = {"role": "assistant", "content": "Offline memory acceptance reply."}
        finish = "stop"
        if qq and body["messages"][-1]["role"] != "tool":
            message.update(content="", tool_calls=[{"id": f"memory-call-{self.calls}", "type": "function",
                "function": {"name": "qq_send_message", "arguments": json.dumps({"text": "Offline QQ reply."})}}])
            finish = "tool_calls"
        return httpx.Response(200, json={"choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}})

    async def search(self, arguments, _key):
        from ai_workbench.core.web_schemas import ProviderSearchResult, WebPage
        return ProviderSearchResult(provider="offline-memory", query=arguments.query,
            results=[WebPage(url="https://memory.example/article", title="Memory acceptance test",
                content="Memory acceptance test evidence. " * 50)])


class MockOneBot:
    def __init__(self):
        self.connections = set()
        self.sent = 0

    async def serve(self, websocket):
        self.connections.add(websocket)
        try:
            async for raw in websocket:
                request = json.loads(raw)
                action = request["action"]
                if action in {"send_group_msg", "send_private_msg"}:
                    self.sent += 1
                    data = {"message_id": 10000 + self.sent}
                elif action == "get_login_info":
                    data = {"user_id": 12345, "nickname": "Memory bot"}
                elif action == "get_group_info":
                    data = {"group_id": 7788, "group_name": "Memory group"}
                elif action in {"get_group_member_info", "get_stranger_info"}:
                    data = {"user_id": 9999, "nickname": "Memory sender", "card": "Memory sender"}
                elif action == "get_group_member_list":
                    data = [{"user_id": 9999, "nickname": "Memory sender", "card": "Memory sender"}]
                else:
                    raise AssertionError(f"Unexpected mock OneBot action: {action}")
                await websocket.send(json.dumps({"status": "ok", "retcode": 0, "data": data, "echo": request["echo"]}))
        finally:
            self.connections.remove(websocket)

    async def incoming(self, number):
        event = {"post_type": "message", "message_type": "group", "self_id": 12345,
            "message_id": number, "user_id": 9999, "group_id": 7788, "time": time.time(),
            "sender": {"nickname": "Memory sender", "card": "Memory sender"},
            "message": [{"type": "text", "data": {"text": f"bot memory acceptance {number}"}}]}
        for connection in self.connections:
            await connection.send(json.dumps(event))


async def wait_until(predicate, seconds=30):
    async def wait():
        while not predicate():
            await asyncio.sleep(.05)
    await asyncio.wait_for(wait(), seconds)


async def idle_samples(process, args, cycle):
    started = time.monotonic()
    print(f"cycle {cycle}: waiting {args.idle_seconds:g}s for idle recovery", flush=True)
    while time.monotonic() - started < args.idle_seconds:
        await asyncio.sleep(min(30, args.idle_seconds - (time.monotonic() - started)))
        print(f"cycle {cycle}: idle RSS {memory(process)['rss'] / 2**20:.2f} MiB", flush=True)
    samples, started = [], time.monotonic()
    while not samples or time.monotonic() - started < args.sample_seconds:
        samples.append(memory(process))
        await asyncio.sleep(min(1, args.sample_seconds))
    result = summarize(samples)
    print(f"cycle {cycle}: idle maximum {result['rss_max'] / 2**20:.2f} MiB", flush=True)
    return result


async def workload(args, work_root):
    import httpx
    import psutil
    import uvicorn
    from websockets.asyncio.server import serve
    from ai_workbench.core import web_filters
    from ai_workbench.api.main import create_app
    from ai_workbench.core.models.schema import ChatRequest
    from ai_workbench.core.schema.context_budget import ContextLimits

    async def offline_subscription(_url):
        return ""

    web_filters.download_subscription = offline_subscription
    provider, onebot = MockProvider(), MockOneBot()
    app = create_app(root=work_root, database_url=f"sqlite:///{work_root / 'app.db'}",
        frontend_dist=args.frontend_dist or args.source_root / "frontend/dist", adapter_factory=provider.factory)
    state, process = app.state.runtime_state, psutil.Process()
    state.web_tools.provider = provider
    report = {"python": platform.python_version(), "platform": sys.platform,
              "source_root": str(args.source_root), "cycles": []}
    async with serve(onebot.serve, "127.0.0.1", 0) as onebot_server:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                await wait_until(lambda: server.started or serving.done())
                if serving.done():
                    await serving
                    raise RuntimeError("Server stopped before becoming ready")
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=120,
                        limits=httpx.Limits(max_keepalive_connections=0)) as client:
                    async def call(method, path, body=None):
                        response = await client.request(method, path, **({"json": body} if body is not None else {}))
                        response.raise_for_status()
                        return response.json()

                    await call("GET", "/api/health")
                    await call("GET", "/api/settings/general")
                    external = await call("POST", "/api/models/providers", {"name": "Offline memory provider",
                        "connection": {"base_url": "http://offline-memory.invalid/v1"}})
                    model = await call("POST", "/api/models/profiles", {"name": "Memory", "alias": "memory",
                        "kind": "llm", "model_ref": "offline", "source": {"type": "provider", "provider_profile_id": external["id"]},
                        "context_window_tokens": 32768, "request_options": {"streaming": False}})
                    character = await call("POST", "/api/characters", {"kind": "normal", "name": "Memory chat",
                        "model_profile_id": model["id"], "context_policy": {"compaction": {"enabled": False}}})
                    normal = await call("POST", f"/api/characters/{character['id']}/sessions", {})
                    tool_session = await call("POST", f"/api/characters/{character['id']}/sessions", {
                        "overrides": {"harness_enabled": True, "tools_allowed": ["web_search"]}})
                    await call("PATCH", "/api/tools/web/settings", {"api_key": "offline-memory"})
                    qq_character = await call("POST", "/api/characters", {"kind": "qqbot", "name": "Memory QQ",
                        "context_policy": {"compaction": {"enabled": False}}, "model_profile_id": model["id"],
                        "bot_account": "12345", "connection_enabled": True, "keywords": ["bot"], "reply_message_limit": 1,
                        "websocket_url": f"ws://127.0.0.1:{onebot_server.sockets[0].getsockname()[1]}"})
                    qq = await call("POST", f"/api/characters/{qq_character['id']}/sessions", {"target_kind": "group", "target_id": "7788"})
                    await wait_until(lambda: qq_character["id"] in state.qq.connections and state.qq.connections[qq_character["id"]].ready)
                    await call("GET", f"/api/sessions/{normal['session_id']}/history")
                    await call("GET", f"/api/qq/sessions/{qq['session_id']}/history")
                    report["ready"] = memory(process)
                    report["startup_modules"] = [name for name in ("alembic", "mako", "PIL.Image", "tiktoken") if name in sys.modules]
                    print(f"ready: RSS {report['ready']['rss'] / 2**20:.2f} MiB; modules {report['startup_modules']}", flush=True)

                    async def count_tokens():
                        started = time.perf_counter()
                        measured = await state.model_manager.measure_chat(model["id"],
                            ChatRequest(model=model["alias"], messages=[{"role": "user", "content": "Memory acceptance. " * 100}]),
                            ContextLimits(window_tokens=32768, output_tokens=512))
                        return {"count_ms": (time.perf_counter() - started) * 1000, "input_tokens": measured.input_tokens,
                                "after_count": memory(process)}

                    for number in range(1, args.cycles + 1):
                        cycle = await count_tokens()
                        print(f"cycle {number}: token counting took {cycle['count_ms']:.0f}ms", flush=True)
                        reply = await call("POST", f"/api/sessions/{normal['session_id']}/messages",
                            {"content": f"Normal memory acceptance {number}. " * 10})
                        assert reply["success"] and reply["run"]["status"] == "DONE", reply
                        tool = await call("POST", "/api/tools/web_search/call", {"session_id": tool_session["session_id"],
                            "arguments": {"searches": [{"query": "memory acceptance test"}]}})
                        assert tool["run"]["status"] == "DONE", tool
                        sent_before = onebot.sent
                        await onebot.incoming(number)
                        await wait_until(lambda: onebot.sent > sent_before and state.active_runs.active_count() == 0, seconds=60)
                        await call("GET", f"/api/sessions/{normal['session_id']}/history")
                        await call("GET", f"/api/qq/sessions/{qq['session_id']}/history")
                        cycle["after_workload"] = memory(process)
                        print(f"cycle {number}: count {cycle['count_ms']:.0f}ms; workload RSS {cycle['after_workload']['rss'] / 2**20:.2f} MiB", flush=True)
                        cycle["idle"] = await idle_samples(process, args, number)
                        report["cycles"].append(cycle)
                    from io import BytesIO
                    from PIL import Image
                    from ai_workbench.core.models.processing import prepare_process_image
                    from ai_workbench.core.qq_media import decode_image
                    buffer = BytesIO()
                    Image.new("RGBA", (32, 24), (40, 80, 120, 128)).save(buffer, format="PNG")
                    prepared = prepare_process_image(buffer.getvalue())
                    assert (prepared.width, prepared.height) == (32, 24)
                    assert decode_image(buffer.getvalue())[2:4] == (32, 24)
                    report["after_image"] = memory(process)
                    await call("GET", "/openapi.json")
                    report["after_openapi"] = memory(process)
                    report["after_idle_recount"] = await count_tokens()
                    report["provider_calls"], report["qq_deliveries"] = provider.calls, onebot.sent
            finally:
                server.should_exit = True
                await serving
                state.sessions.engine.dispose()
    report["children_after_shutdown"] = [child.pid for child in process.children(recursive=True)]
    assert not report["children_after_shutdown"], report
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--frontend-dist", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--idle-seconds", type=float, default=90)
    parser.add_argument("--sample-seconds", type=float, default=60)
    parser.add_argument("--output", type=Path, default=ROOT / "build/idle-memory/report.json")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.runs, args.cycles, args.idle_seconds, args.sample_seconds) <= 0:
        parser.error("Runs, cycles and durations must be positive")
    args.source_root = args.source_root.resolve()
    if args.frontend_dist:
        args.frontend_dist = args.frontend_dist.resolve()
    if args.worker:
        sys.path.insert(0, str(args.source_root))
        with TemporaryDirectory(prefix="cogita-idle-memory-") as directory:
            root = Path(directory)
            previous = Path.cwd()
            os.chdir(root)
            os.environ["COGITA_ATTACHMENTS_DIR"] = str(root / "data/attachments")
            try:
                report = asyncio.run(workload(args, root))
            finally:
                os.chdir(previous)
        print(RESULT_PREFIX + json.dumps(report), flush=True)
        return
    reports = []
    for number in range(1, args.runs + 1):
        print(f"run {number}/{args.runs}: {args.source_root}", flush=True)
        command = [args.python, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--worker", "--source-root", str(args.source_root),
            "--cycles", str(args.cycles), "--idle-seconds", str(args.idle_seconds), "--sample-seconds", str(args.sample_seconds)]
        if args.frontend_dist:
            command += ["--frontend-dist", str(args.frontend_dist)]
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8") as process:
            for line in process.stdout:
                if line.startswith(RESULT_PREFIX):
                    reports.append(json.loads(line[len(RESULT_PREFIX):]))
                elif not line.startswith("INFO  [alembic."):
                    print(line.rstrip(), flush=True)
            if process.wait():
                raise SystemExit("Memory workload failed")
        if len(reports) != number:
            raise SystemExit("Memory workload produced no result")
    qualified = args.runs >= 3 and args.cycles >= 2 and args.idle_seconds >= 90 and args.sample_seconds >= 60
    observed_target_met = all(cycle["idle"]["rss_max"] < 100 * 2**20 and cycle["idle"]["child_rss_max"] == 0
        for report in reports for cycle in report["cycles"])
    target_met = qualified and observed_target_met
    result = {"qualified_acceptance": qualified, "target_mib": 100, "target_met": target_met, "runs": reports,
        "observed_target_met": observed_target_met,
        "limitation": "Offline synthetic text/QQ/tool workloads; image and OpenAPI first use are reported separately. "
                      "No real provider, QQ account, loaded model, allocator trim or forced garbage collection is used."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "qualified_acceptance": qualified, "target_met": target_met}), flush=True)


if __name__ == "__main__":
    main()
