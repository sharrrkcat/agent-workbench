"""Short SQLite transactions for reusable web evidence; no network work here."""
from datetime import timedelta
import hashlib
import json

from sqlalchemy import case
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import Session, delete, select, update

from ai_workbench.core.time import ensure_utc, utc_now
from ai_workbench.core.web_content import normalize_url
from ai_workbench.core.web_schemas import WebLink
from ai_workbench.db.web_models import WebPageRecord, WebSessionPageRecord


def cached_page(url: str, title: str, snippet: str, content: str, links: list[WebLink], source: str, now) -> WebPageRecord:
    link_data = json.dumps([link.model_dump() for link in links], ensure_ascii=False)
    return WebPageRecord(url_key=normalize_url(url), raw_url=url, title=title, snippet=snippet,
        content=content, links_json=link_data, content_hash=hashlib.sha256((content + "\n" + link_data).encode()).hexdigest(),
        content_src=source, fetched_at=now, first_seen_at=now, last_accessed_at=now)


def delete_session_web_pages(db: Session, session_id: str) -> None:
    db.exec(delete(WebSessionPageRecord).where(WebSessionPageRecord.session_id == session_id))
    db.exec(delete(WebPageRecord).where(~select(WebSessionPageRecord.url_key).where(
        WebSessionPageRecord.url_key == WebPageRecord.url_key).exists()))


class WebPageStore:
    def __init__(self, engine=None):
        self.engine = engine
        self.pages: dict[str, WebPageRecord] = {}
        self.associations: dict[tuple[str, str, str], object] = {}
        self.last_cleanup = None

    def get(self, url: str) -> WebPageRecord | None:
        key = normalize_url(url)
        if self.engine is None:
            page = self.pages.get(key)
            return page.model_copy(deep=True) if page else None
        with Session(self.engine) as db:
            return db.get(WebPageRecord, key)

    def write(self, pages: list[tuple[WebPageRecord, list[str]]], session_id: str | None) -> None:
        if session_id is None:
            return
        if self.engine is None:
            for page, queries in pages:
                old = self.pages.get(page.url_key)
                if old:
                    page = page.model_copy(update={"first_seen_at": old.first_seen_at})
                    if old.content_src == "extract" and page.content_src == "search":
                        page = page.model_copy(update={key: getattr(old, key) for key in (
                            "content", "links_json", "content_hash", "content_src", "fetched_at")})
                self.pages[page.url_key] = page.model_copy(deep=True)
                for query in queries:
                    self.associations[session_id, page.url_key, query] = page.last_accessed_at
            return
        with Session(self.engine) as db:
            for page, queries in pages:
                statement = insert(WebPageRecord).values(**page.model_dump())
                keep_extract = (WebPageRecord.content_src == "extract") & (statement.excluded.content_src == "search")
                updates = {key: getattr(statement.excluded, key) for key in (
                    "raw_url", "title", "snippet", "last_accessed_at")}
                updates.update({key: case((keep_extract, getattr(WebPageRecord, key)),
                    else_=getattr(statement.excluded, key)) for key in (
                    "content", "links_json", "content_hash", "content_src", "fetched_at")})
                db.execute(statement.on_conflict_do_update(index_elements=["url_key"], set_=updates))
                for query in queries:
                    association = insert(WebSessionPageRecord).values(session_id=session_id, url_key=page.url_key,
                        query=query, accessed_at=page.last_accessed_at)
                    db.execute(association.on_conflict_do_update(index_elements=["session_id", "url_key", "query"],
                        set_={"accessed_at": page.last_accessed_at}))
            db.commit()

    def touch(self, page: WebPageRecord, session_id: str | None, now) -> None:
        if session_id is None:
            return
        if self.engine is None:
            self.pages[page.url_key].last_accessed_at = now
            self.associations[session_id, page.url_key, ""] = now
            return
        with Session(self.engine) as db:
            db.exec(update(WebPageRecord).where(WebPageRecord.url_key == page.url_key).values(last_accessed_at=now))
            association = insert(WebSessionPageRecord).values(session_id=session_id, url_key=page.url_key,
                query="", accessed_at=now)
            db.execute(association.on_conflict_do_update(index_elements=["session_id", "url_key", "query"],
                set_={"accessed_at": now}))
            db.commit()

    def delete_session(self, session_id: str) -> None:
        if self.engine is None:
            self.associations = {key: value for key, value in self.associations.items() if key[0] != session_id}
            referenced = {key[1] for key in self.associations}
            self.pages = {key: value for key, value in self.pages.items() if key in referenced}
        else:
            with Session(self.engine) as db:
                delete_session_web_pages(db, session_id)
                db.commit()

    def prune(self, retention_days: int, now=None) -> None:
        now = now or utc_now()
        if self.last_cleanup is not None and now - self.last_cleanup < timedelta(days=1):
            return
        cutoff = now - timedelta(days=retention_days)
        if self.engine is None:
            expired = {key for key, page in self.pages.items() if ensure_utc(page.last_accessed_at) < cutoff}
            self.associations = {key: value for key, value in self.associations.items() if key[1] not in expired}
            for key in expired:
                del self.pages[key]
        else:
            with Session(self.engine) as db:
                expired = select(WebPageRecord.url_key).where(WebPageRecord.last_accessed_at < cutoff)
                db.exec(delete(WebSessionPageRecord).where(WebSessionPageRecord.url_key.in_(expired)))
                db.exec(delete(WebPageRecord).where(WebPageRecord.last_accessed_at < cutoff))
                db.commit()
        self.last_cleanup = now
