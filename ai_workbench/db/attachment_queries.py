"""Extract attachment references inside SQLite without hydrating message bodies."""
from sqlalchemy import bindparam, text


def message_references(where="1 = 1"):
    values = "json_each(json_array(json_extract(p.value, '$.attachment_id'), json_extract(p.value, '$.uri'), json_extract(p.value, '$.url'))) v"
    return f"""
        SELECT v.value FROM messagerecord m, json_each(m.parts_json) p, {values} WHERE {where}
        UNION ALL
        SELECT v.value FROM messagerecord m, json_each(m.parts_json) g, json_each(g.value, '$.items') p, {values}
          WHERE {where} AND json_extract(g.value, '$.type') = 'media_group'
        UNION ALL
        SELECT v.value FROM messagerecord m, json_each(m.metadata_json, '$.attachments') a,
          json_each(json_array(json_extract(a.value, '$.id'), json_extract(a.value, '$.uri'))) v WHERE {where}
    """


def referenced_messages(engine, names):
    if not names:
        return set()
    values = [prefix + name for name in names for prefix in ("", "local://attachments/", "/api/attachments/")]
    limit = " LIMIT 1" if len(names) == 1 else ""
    statement = text(f"SELECT value FROM ({message_references()}) WHERE value IN :values{limit}").bindparams(bindparam("values", expanding=True))
    with engine.connect() as connection:
        return {value.removeprefix("local://attachments/").removeprefix("/api/attachments/")
                for value in connection.execute(statement, {"values": values}).scalars()}


def selected_message_attachments(engine, *, session_id=None, message_ids=None, run_ids=None):
    from ai_workbench.core.attachments import attachment_filename
    conditions, params = [], {}
    if session_id is not None:
        conditions.append("m.session_id = :session_id")
        params["session_id"] = session_id
    if message_ids is not None or run_ids is not None:
        conditions.append("(m.message_id IN :message_ids OR m.run_id IN :run_ids)")
        params.update(message_ids=list(message_ids or []), run_ids=list(run_ids or []))
    statement = text(message_references(" AND ".join(conditions) or "1 = 1"))
    if "message_ids" in params:
        statement = statement.bindparams(bindparam("message_ids", expanding=True), bindparam("run_ids", expanding=True))
    with engine.connect() as connection:
        for batch in connection.execute(statement, params).scalars().partitions(128):
            for value in batch:
                name = attachment_filename(value)
                if name:
                    yield name
