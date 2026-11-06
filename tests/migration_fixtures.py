"""Seed the fixed model table used by revisions 0014 through 0024."""
import json
from datetime import datetime, timezone

from sqlalchemy import text


def insert_historical_row(db, table, **values):
    """Seed a pinned schema directly, independently of current ORM identities."""
    defaults = {
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
        "title": "", "configuration_json": "{}", "title_generation_state": "pending",
        "title_generation_metadata_json": "{}", "config_snapshot_json": "{}",
        "harness_state_json": "{}", "current_step": "", "stage": "", "progress_message": "",
        "cancel_requested": False, "metadata_json": "{}", "parts_json": "[]", "content_version": 2,
        "paused": False, "pause_reason": "", "references_json": "[]", "sort_order": 0,
    }
    columns = {row[1]: row for row in db.execute(text(f'PRAGMA table_info("{table}")')).all()}
    row = {key: value for key, value in defaults.items() if key in columns}
    row.update(values)
    db.execute(text(f'INSERT INTO "{table}" ({",".join(row)}) VALUES ({",".join(":" + key for key in row)})'), row)


def historical_row(db, table, key, value):
    return db.execute(text(f'SELECT * FROM "{table}" WHERE "{key}"=:value'), {"value": value}).mappings().one()


def insert_pre_request_options_model(engine, profile):
    data = profile.model_dump(exclude={"source", "request_options", "parameters", "context_window_tokens"})
    source = profile.source
    local = source is not None and source.type == "local"
    data.update(source_type=source.type if source else None,
        provider_profile_id=source.provider_profile_id if source and not local else None,
        parameters_json=json.dumps(profile.parameters), capabilities_json="{}",
        execution_options_json=json.dumps(source.execution_options) if local else None,
        lifecycle_json=source.lifecycle.model_dump_json() if local else None)
    with engine.begin() as db:
        db.execute(text(f"INSERT INTO model_profiles ({','.join(data)}) VALUES ({','.join(':' + key for key in data)})"), data)
    return profile


def model_row(engine, identifier):
    with engine.connect() as db:
        return dict(db.execute(text("SELECT * FROM model_profiles WHERE id=:id"), {"id": identifier}).mappings().one())
