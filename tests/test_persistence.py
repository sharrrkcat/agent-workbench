from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from ai_workbench.api.main import LazyApp, create_app
from ai_workbench.db.database import get_engine, init_db
from ai_workbench.db.models import (
    AgentConfigRecord,
    AppMetadataRecord,
    CapabilityConfigRecord,
    MessageRecord,
    RunEventRecord,
    RunRecord,
    SessionRecord,
)
from ai_workbench.db.stores import (
    SqlAgentConfigStore,
    SqlCapabilityConfigStore,
    SqlMessageStore,
    SqlRunEventStore,
    SqlRunStore,
    SqlSessionStore,
)
from ai_workbench.core.schema.run import RunStatus
from tests.test_prompt_agent_execution import FakeLLMRuntime


def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'agent_workbench_test.db'}"


def make_engine(tmp_path: Path):
    engine = get_engine(sqlite_url(tmp_path))
    init_db(engine)
    return engine


def test_sqlite_database_initialization_creates_tables(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)

    tables = set(inspect(engine).get_table_names())

    assert SessionRecord.__tablename__ in tables
    assert MessageRecord.__tablename__ in tables
    assert RunRecord.__tablename__ in tables
    assert RunEventRecord.__tablename__ in tables
    assert AgentConfigRecord.__tablename__ in tables
    assert CapabilityConfigRecord.__tablename__ in tables
    assert AppMetadataRecord.__tablename__ in tables
    assert "llm_provider_profiles" in tables


def test_legacy_llm_profiles_migrate_to_provider_profiles_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    engine = get_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE llm_profiles (
                    id VARCHAR PRIMARY KEY,
                    alias VARCHAR,
                    name VARCHAR,
                    provider VARCHAR,
                    base_url VARCHAR,
                    api_key VARCHAR,
                    model_id VARCHAR,
                    enabled BOOLEAN,
                    temperature FLOAT,
                    top_p FLOAT,
                    top_k INTEGER,
                    max_tokens INTEGER,
                    timeout INTEGER,
                    supports_vision BOOLEAN,
                    supports_tools BOOLEAN,
                    supports_reasoning BOOLEAN,
                    supports_streaming BOOLEAN,
                    supports_json_mode BOOLEAN,
                    notes VARCHAR,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        for profile_id, alias, model_id in (("p1", "one", "model-one"), ("p2", "two", "model-two")):
            connection.execute(
                text(
                    """
                    INSERT INTO llm_profiles (
                        id, alias, name, provider, base_url, api_key, model_id, enabled,
                        timeout, supports_vision, supports_tools, supports_reasoning, supports_streaming,
                        supports_json_mode, created_at, updated_at
                    ) VALUES (
                        :id, :alias, :name, 'lm_studio', 'http://localhost:1234/v1', 'secret',
                        :model_id, 1, 60, 1, 0, 0, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"id": profile_id, "alias": alias, "name": alias, "model_id": model_id},
            )

    init_db(engine)
    init_db(engine)

    with engine.connect() as connection:
        providers = connection.execute(text("SELECT id, api_key FROM llm_provider_profiles")).fetchall()
        profiles = connection.execute(text("SELECT provider_profile_id, supports_vision, supports_streaming FROM llm_profiles")).fetchall()

    assert len(providers) == 1
    assert providers[0].api_key == "secret"
    assert {row.provider_profile_id for row in profiles} == {providers[0].id}
    assert all(row.supports_vision == 1 for row in profiles)
    assert all(row.supports_streaming == 1 for row in profiles)


def test_sql_session_store_create_get_list_update(tmp_path: Path) -> None:
    store = SqlSessionStore(make_engine(tmp_path))

    session = store.create_session(default_agent_id="chat", title="One")
    store.set_default_agent(session.session_id, "translate")
    updated = store.set_title(session.session_id, "Renamed")

    assert store.get_session(session.session_id).default_agent_id == "translate"
    assert updated.title == "Renamed"
    assert [item.session_id for item in store.list_sessions()] == [session.session_id]


def test_sql_message_store_add_list_get(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    sessions = SqlSessionStore(engine)
    messages = SqlMessageStore(engine)
    session = sessions.create_session()

    message = messages.add_message(
        session_id=session.session_id,
        role="assistant",
        content={"text": "hello"},
        agent_id="chat",
        available_actions=[{"action_id": "retry"}],
        metadata={"ok": True},
    )

    loaded = messages.get_message(message.message_id)
    listed = messages.list_messages(session.session_id)

    assert loaded.parts[0]["text"] == "{'text': 'hello'}"
    assert loaded.available_actions == [{"action_id": "retry"}]
    assert loaded.metadata == {"ok": True}
    assert [item.message_id for item in listed] == [message.message_id]
    assert sessions.get_session(session.session_id).updated_at >= message.created_at


def test_sql_session_store_lists_recently_updated_first(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    sessions = SqlSessionStore(engine)
    messages = SqlMessageStore(engine)
    first = sessions.create_session(title="First")
    second = sessions.create_session(title="Second")

    messages.add_message(session_id=first.session_id, role="user", content="recent activity")

    assert [item.session_id for item in sessions.list_sessions()] == [first.session_id, second.session_id]


def test_sql_run_store_create_update_list_get(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    sessions = SqlSessionStore(engine)
    runs = SqlRunStore(engine)
    session = sessions.create_session()

    run = runs.create_run(kind="command", target_id="/encode", session_id=session.session_id)
    done = runs.update_status(run.run_id, RunStatus.DONE, current_step="done")

    assert done.status == RunStatus.DONE
    assert runs.get_run(run.run_id).current_step == "done"
    assert [item.run_id for item in runs.list_runs(session.session_id)] == [run.run_id]


def test_sql_run_event_store_add_list(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    sessions = SqlSessionStore(engine)
    runs = SqlRunStore(engine)
    events = SqlRunEventStore(engine)
    session = sessions.create_session()
    run = runs.create_run(kind="command", target_id="/encode", session_id=session.session_id)

    event = events.add_event(run.run_id, session.session_id, "run_started", "Run started.", {"ok": True})

    listed = events.list_events(run.run_id)
    assert listed == [event]
    assert listed[0].payload == {"ok": True}


def test_sql_config_stores_save_and_read(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    agents = SqlAgentConfigStore(engine)
    capabilities = SqlCapabilityConfigStore(engine)

    agents.set_config("chat", enabled=False, user_config={"temperature": 0.2})
    capabilities.set_config("codec", enabled=True, user_config={"max_text_input_chars": 100})

    agent_config = agents.get_config("chat")
    capability_config = capabilities.get_config("codec")

    assert agent_config["agent_id"] == "chat"
    assert agent_config["enabled"] is False
    assert agent_config["user_config"] == {"temperature": 0.2}
    assert agent_config["created_at"] <= agent_config["updated_at"]
    assert capability_config["capability_id"] == "codec"
    assert capability_config["enabled"] is True
    assert capability_config["user_config"] == {"max_text_input_chars": 100}
    assert capability_config["created_at"] <= capability_config["updated_at"]


def test_schema_version_is_written_to_metadata_table(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)

    from sqlmodel import Session

    with Session(engine) as session:
        record = session.get(AppMetadataRecord, "schema_version")

    assert record is not None
    assert record.value == "1"


def test_create_app_with_sqlite_database_starts(tmp_path: Path) -> None:
    app = create_app(database_url=sqlite_url(tmp_path), llm_runtime=FakeLLMRuntime())

    assert app.title == "Agent Workbench"


def test_module_level_asgi_app_is_lazy() -> None:
    app = LazyApp()

    assert app._app is None


def test_sessions_persist_across_app_instances(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path)
    first = TestClient(create_app(database_url=url, llm_runtime=FakeLLMRuntime()))
    created = first.post("/api/sessions", json={"title": "Persistent", "default_agent_id": "chat"}).json()

    second = TestClient(create_app(database_url=url, llm_runtime=FakeLLMRuntime()))
    response = second.get("/api/sessions")

    assert response.status_code == 200
    assert created["session_id"] in {session["session_id"] for session in response.json()}


def test_configs_persist_across_app_instances(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path)
    first = TestClient(create_app(database_url=url, llm_runtime=FakeLLMRuntime()))

    first.patch("/api/agent-configs/chat", json={"enabled": False, "user_config": {"temperature": 0.1}})
    first.patch("/api/capability-configs/codec", json={"enabled": False, "user_config": {"max_text_input_chars": 100}})

    second = TestClient(create_app(database_url=url, llm_runtime=FakeLLMRuntime()))
    agent_config = second.get("/api/agent-configs/chat").json()
    capability_config = second.get("/api/capability-configs/codec").json()

    assert agent_config["enabled"] is False
    assert agent_config["user_config"] == {"temperature": 0.1}
    assert capability_config["enabled"] is False
    assert capability_config["user_config"] == {"max_text_input_chars": 100}


def test_command_messages_persist_across_app_instances(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path)
    first = TestClient(create_app(database_url=url, llm_runtime=FakeLLMRuntime()))
    session = first.post("/api/sessions", json={"title": "Commands", "default_agent_id": "chat"}).json()

    response = first.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/encode base64 hello"})
    assert response.status_code == 200

    second = TestClient(create_app(database_url=url, llm_runtime=FakeLLMRuntime()))
    messages = second.get(f"/api/sessions/{session['session_id']}/messages").json()
    runs = second.get(f"/api/sessions/{session['session_id']}/runs").json()

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["parts"][0]["content"] == "aGVsbG8="
    assert messages[-1]["metadata"]["kind"] == "command_result"
    assert messages[-1]["metadata"]["producer"] == "capability"
    assert runs[-1]["target_id"] == "/encode"
    assert runs[-1]["status"] == "DONE"


def test_deleted_session_stays_deleted_across_app_instances(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path)
    first = TestClient(create_app(database_url=url, llm_runtime=FakeLLMRuntime()))
    session = first.post("/api/sessions", json={"title": "Delete me", "default_agent_id": "chat"}).json()
    response = first.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "/encode base64 hello"})
    assert response.status_code == 200

    delete_response = first.delete(f"/api/sessions/{session['session_id']}")
    assert delete_response.status_code == 200

    second = TestClient(create_app(database_url=url, llm_runtime=FakeLLMRuntime()))
    sessions = second.get("/api/sessions").json()

    assert session["session_id"] not in {item["session_id"] for item in sessions}
    assert second.get(f"/api/sessions/{session['session_id']}").status_code == 404
    assert second.get(f"/api/sessions/{session['session_id']}/messages").status_code == 404
    assert second.get(f"/api/sessions/{session['session_id']}/runs").status_code == 404


def test_recovery_interrupts_running_runs(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path)
    engine = make_engine(tmp_path)
    sessions = SqlSessionStore(engine)
    runs = SqlRunStore(engine)
    session = sessions.create_session()
    run = runs.create_run(kind="agent", target_id="chat", session_id=session.session_id)
    runs.update_status(run.run_id, RunStatus.RUNNING, current_step="running")

    create_app(database_url=url, llm_runtime=FakeLLMRuntime())
    recovered = SqlRunStore(get_engine(url)).get_run(run.run_id)

    assert recovered.status == RunStatus.INTERRUPTED
    assert recovered.error == "Server restarted before this run completed."


def test_recovery_interrupts_waiting_runs_and_clears_session_waiting_run(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path)
    engine = make_engine(tmp_path)
    sessions = SqlSessionStore(engine)
    runs = SqlRunStore(engine)
    session = sessions.create_session()
    run = runs.create_run(kind="agent", target_id="script_lifecycle_lab", session_id=session.session_id)
    runs.update_status(run.run_id, RunStatus.WAITING_FOR_USER, current_step="waiting_for_user")
    sessions.set_waiting_run(session.session_id, run.run_id)

    create_app(database_url=url, llm_runtime=FakeLLMRuntime())
    recovered_run = SqlRunStore(get_engine(url)).get_run(run.run_id)
    recovered_session = SqlSessionStore(get_engine(url)).get_session(session.session_id)

    assert recovered_run.status == RunStatus.INTERRUPTED
    assert recovered_session.waiting_run_id is None
