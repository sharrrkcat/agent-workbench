"""uBlacklist URL semantics, early exclusion and durable subscription updates."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.web_filter_defaults import DEFAULT_CUSTOM_RULES, DEFAULT_SUBSCRIPTIONS, MAX_FILTER_BYTES
from ai_workbench.core.web_filter_rules import FilterRuleError, FilterRuleset, FilterSnapshot
from ai_workbench.core.web_filter_store import WebFilterStore
from ai_workbench.core.web_filters import WebFilterService, download_subscription
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.db import migrations
from tests.test_web_tools import web_env, configure, call, results, response
from tests.tool_fixtures import ok


@pytest.mark.parametrize("rule,url,blocked", [
    ("*://*.example.com/*", "https://example.com", True),
    ("*://*.example.com/*", "http://a.b.example.com:8080/a", True),
    ("*://*.example.com/*", "https://notexample.com/", False),
    ("*://*.example.com/*", "https://example.com.other.test/", False),
    ("*://example.com/*", "https://a.example.com/", False),
    ("HTTPS://EXAMPLE.COM/Case/*", "https://EXAMPLE.COM/Case/a", True),
    ("https://example.com/Case/*", "https://example.com/case/a", False),
    ("https://example.com/*", "http://example.com/", False),
    ("http://example.com/*", "https://example.com/", False),
    ("*://*/*", "https://different.example/path", True),
    ("<all_urls>", "https://different.example/", True),
    ("<all_urls>", "ftp://example.com/", False),
    ("*://example.com/a?tag=*", "https://example.com/a?tag=foo#ignored", True),
    ("*://example.com/a", "https://example.com/a#ignored", True),
    ("*://example.com/a", "https://example.com/a?tag=foo", False),
    ("*://example.com/a%23b", "https://example.com/a%23b", True),
    ("*://example.com/[ab]?x=1", "https://example.com/[ab]?x=1", True),
    ("*://example.com/[ab]?x=1", "https://example.com/a?x=1", False),
    ("*://example.com/ab*bc", "https://example.com/abc", False),
    ("*://example.com/ab*bc", "https://example.com/abbc", True),
    ("*://example.com/a*b*c", "https://example.com/aBBbCCc", True),
    ("*://xn--bcher-kva.example/*", "https://bücher.example/", True),
])
def test_match_pattern_semantics(rule, url, blocked):
    assert FilterSnapshot(rule, []).blocked(url) is blocked


def test_radix_splits_preserve_short_long_exact_and_wildcard_paths():
    paths = ["/alphabet*tail", "/alpha/*", "/alpine", "/beta*x*y", "/"]
    for ordered in (paths, list(reversed(paths))):
        rules = FilterSnapshot("\n".join("*://example.com" + p for p in ordered), [])
        for path, blocked in [("/", True), ("/alpine", True), ("/alpine/more", False),
            ("/alpha/a", True), ("/alpha", False), ("/alphabet-tail", True),
            ("/alphabet-other", False), ("/beta123x456y", True), ("/beta123y456x", False)]:
            assert rules.blocked("https://example.com" + path) is blocked


def test_comments_header_duplicates_and_action_priority():
    text = "\ufeff---\nname: A\ndescription: YAML metadata only\n---\n# Heading\n*://*.example.com/* # Block\n@*://safe.example.com/*\n*://*.example.com/*"
    assert FilterRuleset([text]).rule_count == 2
    assert FilterSnapshot(text, []).blocked("https://bad.example.com/a")
    assert not FilterSnapshot(text, ["*://safe.example.com/*"]).blocked("https://safe.example.com/")
    assert FilterSnapshot("*://safe.example.com/*", ["@*://safe.example.com/*"]).blocked("https://safe.example.com/")
    assert not FilterSnapshot("", ["*://*.example.com/*", "@*://safe.example.com/*"]).blocked("https://safe.example.com/")
    assert FilterSnapshot("", ["# empty\n", "---\nname: empty\n---"]).subscriptions.rule_count == 0


@pytest.mark.parametrize("text,line", [("# Comment\n/example/", 2), ("title*=\"spam\"", 1),
    ("*://*.example.*/", 1), ("@1*://example.com/*", 1), ("*://example.com/* @if(true)", 1),
    ("ftp://example.com/*", 1), ("example.com", 1), ("*://example.com/%ZZ", 1), ("*://K.example/*", 1),
    ("---\nname: unclosed", 1), ("*://example.com/*\n<html>error</html>", 2)])
def test_invalid_rules_report_source_line(text, line):
    with pytest.raises(FilterRuleError) as error:
        FilterRuleset([text])
    assert error.value.line == line


def test_filter_runs_before_cleaning_candidates_cache_and_sources_but_not_fetch(web_env, monkeypatch):
    client, _, network = web_env
    session = configure(client)
    blocked = "https://deep.youtube.com/article"
    network.reply = response({"results": [
        {"url": blocked, "title": "release notes", "content": "FORBIDDEN_BODY release notes"},
        {"url": "https://notyoutube.com/article", "title": "release notes", "content": "release notes useful evidence"}]})
    from ai_workbench.core import web_tools
    original, cleaned = web_tools.clean_content, []
    def capture(raw, *args):
        cleaned.append(raw)
        return original(raw, *args)
    monkeypatch.setattr(web_tools, "clean_content", capture)
    payload = call(client, session)
    data = results(payload)[0]["data"]
    assert data["stats"]["blocked"] == data["stats"]["candidates"] == 1
    assert [row["source_id"] for row in data["results"]] == ["W1"]
    assert all("FORBIDDEN_BODY" not in raw for raw in cleaned)
    assert client.app.state.runtime_state.web_tools.cache.get(blocked) is None
    network.reply = response({"results": [{"url": blocked, "title": "release notes"}]})
    assert results(call(client, session))[0]["data"]["results"] == []
    network.reply = None
    fetched = results(call(client, session, "web_fetch", {"url": blocked}))[0]
    assert fetched["status"] == "success" and fetched["data"]["url"] == blocked
    ok(client.patch("/api/tools/web/filters", json={"custom_rules": "@*://*.youtube.com/*"}))
    network.reply = response({"results": [{"url": blocked, "title": "release notes", "content": "release notes evidence"}]})
    assert results(call(client, session))[0]["data"]["results"][0]["url"] == blocked


def test_filter_api_is_strict_and_keeps_failed_edits(web_env):
    client, _, _ = web_env
    initial = ok(client.get("/api/tools/web/filters"))
    assert initial["custom_rules"] == DEFAULT_CUSTOM_RULES
    assert [s["url"] for s in initial["subscriptions"]] == [row[2] for row in DEFAULT_SUBSCRIPTIONS]
    assert all(s["enabled"] and "rules_text" not in s for s in initial["subscriptions"])
    for body in ({}, {"custom_rules": None}, {"custom_rules": 1}, {"custom_rules": "", "enabled": True}):
        assert client.patch("/api/tools/web/filters", json=body).status_code == 422
    invalid = client.patch("/api/tools/web/filters", json={"custom_rules": "# hi\n/example/"})
    assert invalid.status_code == 422 and invalid.json()["error"]["details"]["line"] == 2
    assert ok(client.get("/api/tools/web/filters"))["custom_rules"] == DEFAULT_CUSTOM_RULES
    for url in ("file:///etc/passwd", "http://127.0.0.1/a", "https://user:pass@example.com/a"):
        assert client.post("/api/tools/web/subscriptions", json={"name": "invalid", "url": url}).status_code == 422
    created = client.post("/api/tools/web/subscriptions", json={"name": "Test", "url": "https://filters.example/test.txt"})
    assert created.status_code == 201
    row = created.json()
    assert row["last_success_at"] and row["error"] is None
    assert client.post("/api/tools/web/subscriptions", json={"name": "Duplicate", "url": row["url"]}).status_code == 409
    path = "/api/tools/web/subscriptions/" + row["id"]
    for value in ("false", 0, None):
        assert client.patch(path, json={"enabled": value}).status_code == 422
    assert ok(client.patch(path, json={"enabled": False}))["enabled"] is False
    assert client.delete(path).status_code == 204
    assert client.post(path + "/refresh").status_code == 404
    assert client.delete(path).status_code == 404


def test_update_failures_keep_last_success_and_disabled_updates_stay_inactive():
    async def scenario():
        service = WebFilterService(WebFilterStore())
        content = ["*://blocked.example/*"]
        async def download(_url):
            if isinstance(content[0], Exception):
                raise content[0]
            return content[0]
        service.download = download
        row = await service.add("Test", "https://filters.example/test.txt")
        assert service.snapshot.blocked("https://blocked.example/")
        original = service.subscriptions[row.id].model_copy()
        content[0] = "# invalid\n/regex/"
        failed = await service.refresh(row.id)
        assert failed.error.line == 2
        assert service.subscriptions[row.id].rules_text == original.rules_text
        assert service.subscriptions[row.id].last_success_at == original.last_success_at
        content[0] = ToolExecutionError("NETWORK_HTTP_ERROR", "Network request returned HTTP 503.")
        assert (await service.refresh(row.id)).error.code == "NETWORK_HTTP_ERROR"
        first_failure = await service.add("Unavailable", "https://filters.example/offline.txt")
        assert first_failure.rule_count == 0 and first_failure.last_success_at is None and first_failure.error
        old_snapshot = service.snapshot
        await service.set_enabled(row.id, False)
        assert old_snapshot.blocked("https://blocked.example/") and not service.snapshot.blocked("https://blocked.example/")
        content[0] = "*://other.example/*"
        assert (await service.refresh(row.id)).rule_count == 1
        assert not service.snapshot.blocked("https://other.example/")
        await service.set_enabled(row.id, True)
        assert service.snapshot.blocked("https://other.example/")
    asyncio.run(scenario())


def test_weekly_updates_include_disabled_and_manual_refresh_does_not_postpone(monkeypatch):
    from ai_workbench.core import web_filters
    now = [datetime(2026, 10, 30, tzinfo=timezone.utc)]
    monkeypatch.setattr(web_filters, "utc_now", lambda: now[0])
    async def scenario():
        store = WebFilterStore()
        service = WebFilterService(store)
        calls = []
        async def download(url):
            calls.append(url)
            return "# no rules"
        service.download = download
        await service.set_enabled("default-1", False)
        assert await service.refresh_due()
        due = service.settings.next_update_at
        assert len(calls) == 4 and due == now[0] + timedelta(days=7)
        assert not await service.refresh_due()
        now[0] += timedelta(days=1)
        await service.refresh("default-1")
        assert service.settings.next_update_at == due and len(calls) == 5
        now[0] += timedelta(days=20)
        reopened = WebFilterService(store)
        reopened.download = download
        reopened.start()
        for _ in range(100):
            if reopened.settings.next_update_at > now[0]:
                break
            await asyncio.sleep(.01)
        await reopened.close()
        assert len(calls) == 9 and reopened.settings.next_update_at == now[0] + timedelta(days=7)
    asyncio.run(scenario())


def test_duplicate_refreshes_join_and_delete_discards_late_download():
    async def scenario():
        service = WebFilterService(WebFilterStore())
        entered, release, calls = asyncio.Event(), asyncio.Event(), []
        async def download(url):
            calls.append(url)
            entered.set()
            await release.wait()
            return "*://late.example/*"
        service.download = download
        first = asyncio.create_task(service.refresh("default-1"))
        await entered.wait()
        second = asyncio.create_task(service.refresh("default-1"))
        await asyncio.sleep(0)
        await service.delete("default-1")
        release.set()
        assert await first is None and await second is None
        assert len(calls) == 1 and "default-1" not in service.subscriptions
        assert not service.snapshot.blocked("https://late.example/")
        # A completed refresh does not prevent the next explicit update.
        await service.refresh("default-2")
        await service.refresh("default-2")
        assert len(calls) == 3
    asyncio.run(scenario())


def test_sql_migration_and_reopen_never_restore_deleted_defaults(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'filters.db'}")
    init_db(engine)
    async def scenario():
        service = WebFilterService(WebFilterStore(engine))
        assert len(service.subscriptions) == 4
        await service.set_custom("")
        for identity in list(service.subscriptions):
            await service.delete(identity)
        migrations.upgrade(engine)
        reopened = WebFilterService(WebFilterStore(engine))
        assert reopened.settings.custom_rules == "" and reopened.subscriptions == {}
    asyncio.run(scenario())
    engine.dispose()


def test_download_uses_bounded_direct_network_and_utf8(monkeypatch):
    from ai_workbench.core import web_filters
    received = []
    body = [b"\xef\xbb\xbf*://*.example.com/*"]
    async def download(url, policy, **options):
        received.append((url, policy, options))
        return body[0], url, "text/plain"
    monkeypatch.setattr(web_filters, "fetch_bytes", download)
    assert asyncio.run(download_subscription("https://filters.example/list.txt")) == "*://*.example.com/*"
    assert received[0][1].max_redirects == 3
    assert received[0][1].max_response_bytes == received[0][2]["max_bytes"] == MAX_FILTER_BYTES
    body[0] = b"\xff"
    with pytest.raises(ToolExecutionError, match="UTF-8"):
        asyncio.run(download_subscription("https://filters.example/list.txt"))


def test_sql_reopen_retains_downloaded_rules_errors_and_enabled_state(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'downloaded.db'}")
    init_db(engine)
    async def scenario():
        service = WebFilterService(WebFilterStore(engine))
        async def good(_url):
            return "*://blocked.example/*"
        service.download = good
        row = await service.add("Saved", "https://filters.example/saved.txt")
        await service.set_custom("@*://safe.example/*")
        await service.set_enabled(row.id, False)
        async def failed(_url):
            raise ToolExecutionError("NETWORK_REQUEST_FAILED", "Download failed.")
        service.download = failed
        await service.refresh(row.id)
        reopened = WebFilterService(WebFilterStore(engine))
        saved = next(value for value in reopened.public().subscriptions if value.id == row.id)
        assert saved.rule_count == 1 and not saved.enabled
        assert saved.last_success_at == row.last_success_at and saved.error.code == "NETWORK_REQUEST_FAILED"
        assert reopened.settings.custom_rules == "@*://safe.example/*"
        assert not reopened.snapshot.blocked("https://blocked.example/")
        await reopened.set_enabled(row.id, True)
        assert reopened.snapshot.blocked("https://blocked.example/")
    asyncio.run(scenario())
    engine.dispose()


def test_search_keeps_one_filter_snapshot_while_download_is_pending():
    from ai_workbench.core.web_schemas import WebPage
    from tests.test_web_research import service, context, search
    async def scenario():
        web, provider = service()
        entered, release = asyncio.Event(), asyncio.Event()
        provider.pages["release"] = [WebPage(url="https://youtube.com/a", title="release", content="release evidence")]
        original = provider.search
        async def pending(*args):
            entered.set()
            await release.wait()
            return await original(*args)
        provider.search = pending
        request = asyncio.create_task(web.search(search("release"), context()))
        await entered.wait()
        await web.filters.set_custom("")
        release.set()
        assert (await request)["results"] == []
        assert (await web.search(search("release"), context()))["results"][0]["url"] == "https://youtube.com/a"
    asyncio.run(scenario())

