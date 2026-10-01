"""Seed the fixed model table used by revisions 0014 through 0024."""
import json

from sqlalchemy import text


def insert_pre_request_options_model(engine, profile):
    data = profile.model_dump(exclude={"source", "request_options", "parameters"})
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
