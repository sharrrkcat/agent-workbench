"""Indexed message predicates shared by history reads and context projection."""
from sqlalchemy import and_, or_, func, literal, select, tuple_

from ai_workbench.db.models import MessageRecord


def message_key():
    return tuple_(MessageRecord.created_at, MessageRecord.message_id)


def eligible_history():
    parts = func.json_each(MessageRecord.parts_json).table_valued("value")
    errors = select(literal(1)).select_from(parts).where(func.json_extract(parts.c.value, "$.type") == "error")
    return and_(MessageRecord.role.in_(("system", "user", "assistant", "tool")), ~errors.exists(), *(
        _false_json(f"$.{key}") for key in ("event_type", "incomplete", "streaming")))


def _false_json(path):
    kind = func.json_type(MessageRecord.metadata_json, path)
    value = func.json_extract(MessageRecord.metadata_json, path)
    entries = func.json_each(MessageRecord.metadata_json, path).table_valued("value")
    return or_(kind.is_(None), kind.in_(("null", "false")),
        and_(kind.in_(("integer", "real")), value == 0), and_(kind == "text", value == ""),
        and_(kind == "array", func.json_array_length(MessageRecord.metadata_json, path) == 0),
        and_(kind == "object", ~select(literal(1)).select_from(entries).exists()))
