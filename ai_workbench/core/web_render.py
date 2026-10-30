"""Bounded plain-text evidence for live tool roles and quoted history alike."""
import re


SEARCH_OUTPUT_CHARS = 5000
FETCH_OUTPUT_CHARS = 4500
WEB_DISPATCH_CHARS = 6000
OPEN = "<untrusted_web_content>"
CLOSE = "</untrusted_web_content>"


def evidence_text(value: str) -> str:
    return value.replace("<", "&lt;")


def date_label(value: dict) -> str:
    if value.get("uncertain"):
        return "Date uncertain"
    if not value.get("value"):
        return "Date unknown"
    return f"Inferred {value['value']}"


def _retrieved(data: dict) -> str:
    return "Retrieved: " + re.sub(r"\.\d+(?=Z|[+-]\d\d:\d\d$)", "", data.get("retrieved_at", "unknown"))


def _query_line(index: int, query: dict) -> str:
    status = "" if query["status"] == "success" else " [" + query.get("error_code", query["status"]) + "]"
    text = evidence_text(' '.join(query['query'].split())[:160])
    return f"Query {index} ({query.get('recency', 'any')}): {text}{status}"


def _page_block(page: dict) -> str:
    source = f"[{page['source_id']}] " if page.get("source_id") else ""
    heading = source + date_label(page.get("date", {}))
    if (size := page.get("content_chars")) is not None:
        length = f"{size / 1000:.1f}k" if size >= 1000 else str(size)
        heading += f" (≈{length} chars)"
    body = (evidence_text(page['title'])[:180] + "\n" + evidence_text(page['url']) + "\n\n"
            + evidence_text(page.get('content') or page.get('snippet') or ''))
    return f"{heading}\n{OPEN}\n{body}\n{CLOSE}"


def render_web_data(tool_name: str, data: dict) -> str:
    if tool_name == "web_search":
        pages = data["results"]
        lines = [_retrieved(data)]
        for index, query in enumerate(data.get("searches", []), 1):
            lines.append(_query_line(index, query))
        for page in pages:
            lines.append(_page_block(page))
            if page.get("content_limited"):
                lines.append("Limited content; fetching may still require login or JavaScript.")
        if not pages:
            if any(query["status"] == "success" for query in data.get("searches", [])):
                lines.append("No relevant results found. This search cannot confirm the claim; it does not establish nonexistence. No sources returned.")
            else:
                lines.append("No queries produced results. Duplicate queries are not repeated; change angle or answer from existing evidence.")
        return "\n\n".join(lines)
    lines = [_retrieved(data), _page_block(data)]
    if data.get("notice") == "no_focus_match":
        lines.append("No paragraphs match this focus. Specify different terms or omit focus to read in document order.")
    elif data.get("notice") == "no_more_content":
        lines.append("No more content at this page number.")
    elif data.get("page", 1) < data.get("total_pages", 1):
        lines.append(f"More: web_fetch with the same URL/focus and page={data['page'] + 1}.")
    return "\n\n".join(lines)


def web_model_text(tool_name: str, status: str, data: dict | None, error_code=None, error_message=None) -> tuple[str, bool]:
    if status == "success":
        text = render_web_data(tool_name, data)
    else:
        text = f"{tool_name}: {status} ({error_code or 'WEB_ERROR'}). {error_message or ''}"
        for index, query in enumerate((data or {}).get("searches", []), 1):
            text += "\n" + _query_line(index, query)
    limit = SEARCH_OUTPUT_CHARS if tool_name == "web_search" else FETCH_OUTPUT_CHARS
    if len(text) <= limit:
        return text, False
    # Enforce the accepted web-only dispatch boundary even on an unexpected projection.
    # Re-quote the prefix so truncation cannot leave a provider-controlled delimiter open.
    note = f"Web output truncated from {len(text)} characters."
    room = min(limit, WEB_DISPATCH_CHARS) - len(note) - len(OPEN) - len(CLOSE) - 4
    prefix = evidence_text(text[:room])[:room]
    return f"{note}\n{OPEN}\n{prefix}\n{CLOSE}", True
