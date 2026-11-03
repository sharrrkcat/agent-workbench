"""Select public records from the unified timeline in focused QQ behavior tests."""
from tests.tool_fixtures import ok
from sqlmodel import Session, select


def stored_qq_rows(store, kind, session_id, limit=50):
    """Inspect persisted fixture rows without reintroducing application paging APIs."""
    with Session(store.engine) as db:
        query = select(kind).where(kind.session_id == session_id)
        if hasattr(kind, "deleted"):
            query = query.where(kind.deleted == False)
        return [row.model_dump(exclude={"deleted", "image_generation_keyword"})
            for row in db.exec(query.order_by(kind.id.desc()).limit(limit))]


def qq_transcript(client, session_id, **query):
    return ok(client.get(f"/api/qq/sessions/{session_id}/history", params=query))


def qq_incoming(client, session_id):
    return sorted((item["message"] for item in qq_transcript(client, session_id, limit=100)["items"]
        if item["kind"] == "incoming"), key=lambda row: row["id"], reverse=True)


def qq_outgoing(client, session_id):
    records = []
    for item in qq_transcript(client, session_id, limit=100)["items"]:
        if item["kind"] == "reply":
            records.extend(item["deliveries"])
        elif item["kind"] == "program":
            records.append(item["delivery"])
    return sorted(records, key=lambda row: row["id"], reverse=True)
