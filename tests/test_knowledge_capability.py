import asyncio
from pathlib import Path

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.capability_runtime import CapabilityRuntimeRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.core.events import EventBus
from ai_workbench.core.router import Router
from ai_workbench.core.runner import CommandRunner
from ai_workbench.core.runtime import WorkbenchRuntime
from ai_workbench.core.schema.capability import CapabilitySchema
from ai_workbench.core.schema.run import RunStatus
from ai_workbench.core.stores import MessageStore, RunStore, SessionStore
from ai_workbench.core.knowledge_store import KnowledgeBase, KnowledgeSource, SessionKnowledgeBinding
from capabilities.knowledge import CapabilityRuntime


ROOT = Path(__file__).resolve().parents[1]


class FakeKnowledgeStore:
    engine = object()

    def __init__(self) -> None:
        self.kb = KnowledgeBase(id="kb_docs", name="Docs", embedding_model_profile_id="profile_1", index_status="ready")
        self.disabled_kb = KnowledgeBase(
            id="kb_disabled",
            name="Disabled",
            embedding_model_profile_id="profile_1",
            enabled=False,
        )
        self.sources = [
            KnowledgeSource(
                id="src_1",
                knowledge_base_id="kb_docs",
                source_type="pasted_text",
                title="One",
                content_hash="hash_1",
                status="indexed",
                chunks=2,
                embedding_model_profile_id="profile_1",
                embedding_dimension=3,
            ),
            KnowledgeSource(
                id="src_2",
                knowledge_base_id="kb_docs",
                source_type="pasted_text",
                title="Two",
                content_hash="hash_2",
                status="failed",
                error="boom",
                chunks=0,
            ),
        ]
        self.bindings: list[SessionKnowledgeBinding] = [
            SessionKnowledgeBinding(session_id="session_1", knowledge_base_id="kb_docs", enabled=True, knowledge_base=self.kb)
        ]

    def list_session_bindings(self, session_id: str) -> list[SessionKnowledgeBinding]:
        return [binding for binding in self.bindings if binding.session_id == session_id]

    def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        if knowledge_base_id == self.kb.id:
            return self.kb
        if knowledge_base_id == self.disabled_kb.id:
            return self.disabled_kb
        raise KeyError(f"unknown knowledge base: {knowledge_base_id}")

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        return [self.disabled_kb, self.kb]

    def list_sources(self, knowledge_base_id: str) -> list[KnowledgeSource]:
        self.get_knowledge_base(knowledge_base_id)
        return [source for source in self.sources if source.knowledge_base_id == knowledge_base_id]


class RecordingSearchService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "query": kwargs["query"],
            "results": [
                {
                    "rank": 1,
                    "chunk_id": "chunk_1",
                    "knowledge_base_id": "kb_docs",
                    "source_id": "src_1",
                    "title": "One",
                    "heading_path": "",
                    "content": "short snippet",
                    "truncated": False,
                }
            ],
            "debug": {"warnings": []},
        }


def run(coro):
    return asyncio.run(coro)


def knowledge_manifest() -> CapabilitySchema:
    capabilities = CapabilityRegistry()
    capabilities.load_from_directory(ROOT / "capabilities")
    return capabilities.get("knowledge")


def runtime_fixture(runtime: CapabilityRuntime) -> tuple[WorkbenchRuntime, SessionStore, MessageStore, RunStore]:
    capabilities = CapabilityRegistry()
    capabilities.register(knowledge_manifest())
    commands = CommandRegistry.from_capability_registry(capabilities)
    runtimes = CapabilityRuntimeRegistry()
    runtimes.register("knowledge", runtime)
    sessions = SessionStore()
    messages = MessageStore(session_store=sessions)
    runs = RunStore()
    command_runner = CommandRunner(
        command_registry=commands,
        runtime_registry=runtimes,
        run_store=runs,
        message_store=messages,
        event_bus=EventBus(),
        capability_registry=capabilities,
    )
    router = Router(agent_registry=AgentRegistry(), command_registry=commands)
    return WorkbenchRuntime(router=router, command_runner=command_runner), sessions, messages, runs


def test_manifest_methods_match_runtime_callables() -> None:
    manifest = knowledge_manifest()
    runtime = CapabilityRuntime()

    assert {method.id for method in manifest.methods} == {"search", "list_bases", "stats"}
    for method in manifest.methods:
        assert callable(getattr(runtime, method.id))
    assert manifest.commands[0].name == "/kb-search"
    assert manifest.commands[0].method == "search"


def test_search_method_calls_core_retrieval_service() -> None:
    service = RecordingSearchService()
    runtime = CapabilityRuntime(knowledge_store=FakeKnowledgeStore(), model_backend=object(), search_service=service)

    result = runtime.search("alpha", knowledge_base_ids=["kb_docs"], top_k=3, max_context_chars=500, debug=True)

    assert result["query"] == "alpha"
    assert service.calls[0]["knowledge_base_ids"] == ["kb_docs"]
    assert service.calls[0]["session_id"] is None
    assert service.calls[0]["top_k"] == 3
    assert service.calls[0]["max_context_chars"] == 500
    assert service.calls[0]["include_debug"] is True


def test_search_uses_context_session_for_active_kbs() -> None:
    service = RecordingSearchService()
    runtime = CapabilityRuntime(knowledge_store=FakeKnowledgeStore(), model_backend=object(), search_service=service)

    result = runtime.search("beta", context={"session_id": "session_1"})

    assert result["results"][0]["knowledge_base_id"] == "kb_docs"
    assert service.calls[0]["knowledge_base_ids"] is None
    assert service.calls[0]["session_id"] == "session_1"


def test_search_without_active_session_kbs_returns_clear_empty_result() -> None:
    service = RecordingSearchService()
    runtime = CapabilityRuntime(knowledge_store=FakeKnowledgeStore(), model_backend=object(), search_service=service)

    result = runtime.search("beta", context={"session_id": "empty_session"})

    assert result == {
        "query": "beta",
        "results": [],
        "debug": {"warnings": ["No active knowledge bases for this session."]},
    }
    assert service.calls == []


def test_kb_search_command_passes_args_as_query() -> None:
    service = RecordingSearchService()
    store = FakeKnowledgeStore()
    workbench, sessions, messages, runs = runtime_fixture(
        CapabilityRuntime(knowledge_store=store, model_backend=object(), search_service=service)
    )
    session = sessions.create_session()
    store.bindings = [
        SessionKnowledgeBinding(session_id=session.session_id, knowledge_base_id="kb_docs", enabled=True, knowledge_base=store.kb)
    ]

    result = run(workbench.handle_input(session, "/kb-search alpha beta"))

    assert result.success is True
    assert result.output_type == "json"
    assert result.data["query"] == "alpha beta"
    assert service.calls[0]["query"] == "alpha beta"
    assert service.calls[0]["session_id"] == session.session_id
    assert runs.get_run(result.run_id).kind == "command"
    assert runs.get_run(result.run_id).status == RunStatus.DONE
    assert messages.list_messages(session.session_id)[-1].command_name == "/kb-search"


def test_kb_search_without_query_fails_clearly() -> None:
    workbench, sessions, messages, runs = runtime_fixture(
        CapabilityRuntime(knowledge_store=FakeKnowledgeStore(), model_backend=object(), search_service=RecordingSearchService())
    )
    session = sessions.create_session()

    result = run(workbench.handle_input(session, "/kb-search"))

    assert result.success is False
    assert result.error == "Query is required for /kb-search."
    assert runs.get_run(result.run_id).status == RunStatus.FAILED
    assert messages.list_messages(session.session_id)[-1].content == {"code": "COMMAND_FAILED", "message": "Query is required for /kb-search."}


def test_list_bases_returns_compact_kb_list() -> None:
    runtime = CapabilityRuntime(knowledge_store=FakeKnowledgeStore(), model_backend=object())

    result = runtime.list_bases(enabled_only=True)

    assert result == {
        "knowledge_bases": [
            {
                "id": "kb_docs",
                "name": "Docs",
                "enabled": True,
                "index_status": "ready",
                "source_count": 2,
                "chunk_count": 2,
            }
        ]
    }


def test_stats_returns_compact_counts_without_source_text_or_vectors() -> None:
    runtime = CapabilityRuntime(knowledge_store=FakeKnowledgeStore(), model_backend=object())

    result = runtime.stats("kb_docs")

    assert result["knowledge_base_id"] == "kb_docs"
    assert result["sources"] == 2
    assert result["chunks"] == 2
    assert result["embeddings"] == 2
    assert result["source_status_counts"] == {"failed": 1, "indexed": 1}
    assert "content" not in str(result)
    assert "vector" not in str(result).lower()


def test_global_stats_returns_totals() -> None:
    runtime = CapabilityRuntime(knowledge_store=FakeKnowledgeStore(), model_backend=object())

    result = runtime.stats()

    assert result["knowledge_bases"] == 2
    assert result["sources"] == 2
    assert result["chunks"] == 2
    assert result["embeddings"] == 2
