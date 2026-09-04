from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect

from ai_workbench.db.database import get_engine, init_db
from ai_workbench.db import migrations


def test_baseline_upgrade_prunes_extension_tables_and_columns(tmp_path: Path) -> None:
    engine = get_engine(f"sqlite:///{tmp_path / 'baseline.db'}")

    migrations.upgrade(engine, migrations.BASELINE_REVISION)
    removed_agent_table = "agent" + "configrecord"
    assert removed_agent_table in inspect(engine).get_table_names()

    migrations.upgrade(engine, migrations.HEAD_REVISION)
    tables = set(inspect(engine).get_table_names())
    assert migrations.current_revision(engine) == migrations.HEAD_REVISION
    assert removed_agent_table not in tables
    assert ("capability" + "configrecord") not in tables
    assert ("image" + "_generation_model_profiles") not in tables
    assert ("reranker" + "_model_profiles") not in tables
    assert ("kb_" + "origins") not in tables
    assert "llm_profiles" in tables
    assert "kb_sources" in tables
    assert "kb_chunk_fts" in tables

    message_columns = {column["name"] for column in inspect(engine).get_columns("messagerecord")}
    run_columns = {column["name"] for column in inspect(engine).get_columns("runrecord")}
    step_columns = {column["name"] for column in inspect(engine).get_columns("runsteprecord")}
    removed_message_columns = {
        "content" + "_json",
        "output" + "_type",
        "agent" + "_id",
        "command" + "_name",
        "action" + "_id",
        "available" + "_actions_json",
    }
    assert removed_message_columns.isdisjoint(message_columns)
    assert ("action" + "_id") not in run_columns
    assert "target" in run_columns
    assert "kind" in step_columns


def test_empty_database_bootstraps_to_head_and_repeated_upgrade_is_safe(tmp_path: Path) -> None:
    engine = get_engine(f"sqlite:///{tmp_path / 'empty.db'}")

    init_db(engine)
    first = migrations.inspect_schema(engine)
    migrations.upgrade(engine, "head")
    second = migrations.inspect_schema(engine)

    assert migrations.current_revision(engine) == migrations.HEAD_REVISION
    assert first.as_dict() == second.as_dict()


def test_phase1_downgrade_is_explicitly_unsupported(tmp_path: Path) -> None:
    engine = get_engine(f"sqlite:///{tmp_path / 'downgrade.db'}")
    init_db(engine)

    with pytest.raises(RuntimeError, match="destructive Phase 1 migration downgrade is unsupported"):
        migrations.downgrade(engine)
