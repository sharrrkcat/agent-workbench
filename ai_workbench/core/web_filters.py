"""Application-owned subscriptions, weekly updates and immutable search indexes."""
import asyncio
from datetime import timedelta
from uuid import uuid4

from ai_workbench.core.harness.network import fetch_bytes
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.network_policy import NetworkPolicy
from ai_workbench.core.time import ensure_utc, utc_now
from ai_workbench.core.web_filter_defaults import MAX_FILTER_BYTES
from ai_workbench.core.web_filter_rules import FilterRuleError, FilterRuleset, FilterSnapshot
from ai_workbench.core.web_filter_schemas import WebFilterIssue, WebFilterSettingsResponse, WebSubscriptionInfo
from ai_workbench.core.web_filter_store import WebFilterStore
from ai_workbench.db.web_filter_models import WebSubscriptionRecord


UPDATE_INTERVAL = timedelta(days=7)


async def download_subscription(url: str) -> str:
    try:
        content, _, _ = await asyncio.wait_for(fetch_bytes(url,
            NetworkPolicy(max_response_bytes=MAX_FILTER_BYTES), max_bytes=MAX_FILTER_BYTES), 30)
    except asyncio.TimeoutError as exc:
        raise ToolExecutionError("WEB_FILTER_UPDATE_TIMEOUT", "Subscription download timed out.") from exc
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ToolExecutionError("WEB_FILTER_ENCODING_INVALID", "Subscription must contain UTF-8 text.") from exc


def subscription_info(row: WebSubscriptionRecord) -> WebSubscriptionInfo:
    return WebSubscriptionInfo(id=row.id, name=row.name, url=row.url, enabled=row.enabled, rule_count=row.rule_count,
        last_attempt_at=ensure_utc(row.last_attempt_at) if row.last_attempt_at else None,
        last_success_at=ensure_utc(row.last_success_at) if row.last_success_at else None,
        error=WebFilterIssue(code=row.error_code, message=row.error_message, line=row.error_line) if row.error_code else None)


class WebFilterService:
    def __init__(self, store: WebFilterStore):
        self.store = store
        self.settings, self.subscriptions = store.load()
        self.snapshot = self._compile(self.settings, self.subscriptions)
        self.download = download_subscription
        self._commit = asyncio.Lock()
        self._downloads = asyncio.Semaphore(4)
        self._refreshes: dict[str, asyncio.Task] = {}
        self._scheduler: asyncio.Task | None = None

    @staticmethod
    def _compile(settings, subscriptions):
        return FilterSnapshot(settings.custom_rules, (row.rules_text for row in subscriptions.values() if row.enabled))

    def public(self) -> WebFilterSettingsResponse:
        return WebFilterSettingsResponse(custom_rules=self.settings.custom_rules,
            next_update_at=ensure_utc(self.settings.next_update_at) if self.settings.next_update_at else None,
            subscriptions=[subscription_info(row) for row in self.subscriptions.values()])

    async def set_custom(self, text: str) -> WebFilterSettingsResponse:
        async with self._commit:
            settings = self.settings.model_copy(update={"custom_rules": text})
            snapshot = await asyncio.to_thread(self._compile, settings, self.subscriptions)
            self.store.write(settings=settings)
            self.settings, self.snapshot = settings, snapshot
            return self.public()

    async def add(self, name: str, url: str) -> WebSubscriptionInfo:
        async with self._commit:
            if any(row.url == url for row in self.subscriptions.values()):
                raise ToolExecutionError("WEB_SUBSCRIPTION_EXISTS", "This subscription URL is already configured.")
            row = WebSubscriptionRecord(id=str(uuid4()), name=name, url=url)
            self.store.write(subscription=row)
            self.subscriptions = {**self.subscriptions, row.id: row}
        result = await self.refresh(row.id)
        if result is None:
            raise KeyError(row.id)
        return result

    async def set_enabled(self, identity: str, enabled: bool) -> WebSubscriptionInfo:
        async with self._commit:
            row = self.subscriptions[identity].model_copy(update={"enabled": enabled})
            records = {**self.subscriptions, identity: row}
            snapshot = await asyncio.to_thread(self._compile, self.settings, records)
            self.store.write(subscription=row)
            self.subscriptions, self.snapshot = records, snapshot
            return subscription_info(row)

    async def delete(self, identity: str):
        async with self._commit:
            records = dict(self.subscriptions)
            del records[identity]
            snapshot = await asyncio.to_thread(self._compile, self.settings, records)
            self.store.write(deleted_id=identity)
            self.subscriptions, self.snapshot = records, snapshot

    async def refresh(self, identity: str) -> WebSubscriptionInfo | None:
        task = self._refreshes.get(identity)
        if task is None:
            task = asyncio.create_task(self._download_and_apply(identity))
            self._refreshes[identity] = task
            task.add_done_callback(lambda done: self._forget_refresh(identity, done))
        return await asyncio.shield(task)

    def _forget_refresh(self, identity, task):
        if self._refreshes.get(identity) is task:
            self._refreshes.pop(identity)

    async def _download_and_apply(self, identity):
        row = self.subscriptions.get(identity)
        if row is None:
            return None
        attempted, issue = utc_now(), None
        try:
            async with self._downloads:
                text = await self.download(row.url)
            compiled = await asyncio.to_thread(FilterRuleset, [text])
        except FilterRuleError as exc:
            issue = WebFilterIssue(code="WEB_FILTER_RULE_INVALID", message=str(exc), line=exc.line)
        except ToolExecutionError as exc:
            issue = WebFilterIssue(code=exc.code, message=exc.message)
        async with self._commit:
            current = self.subscriptions.get(identity)
            if current is None:
                return None
            changes = {"last_attempt_at": attempted, "error_code": issue.code if issue else None,
                       "error_message": issue.message if issue else None, "error_line": issue.line if issue else None}
            if issue is None:
                changes.update(rules_text=text, rule_count=compiled.rule_count, last_success_at=utc_now())
            row = current.model_copy(update=changes)
            records = {**self.subscriptions, identity: row}
            snapshot = self.snapshot
            if issue is None and current.enabled and current.rules_text != text:
                snapshot = await asyncio.to_thread(self._compile, self.settings, records)
            self.store.write(subscription=row)
            self.subscriptions, self.snapshot = records, snapshot
            return subscription_info(row)

    async def refresh_due(self) -> bool:
        if self.settings.next_update_at and ensure_utc(self.settings.next_update_at) > utc_now():
            return False
        await asyncio.gather(*(self.refresh(identity) for identity in list(self.subscriptions)))
        async with self._commit:
            settings = self.settings.model_copy(update={"next_update_at": utc_now() + UPDATE_INTERVAL})
            self.store.write(settings=settings)
            self.settings = settings
        return True

    def start(self):
        self._scheduler = asyncio.create_task(self._update_loop())

    async def _update_loop(self):
        while True:
            await self.refresh_due()
            await asyncio.sleep(max(0, (ensure_utc(self.settings.next_update_at) - utc_now()).total_seconds()))

    async def close(self):
        tasks = [*self._refreshes.values(), *([self._scheduler] if self._scheduler else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._scheduler = None

