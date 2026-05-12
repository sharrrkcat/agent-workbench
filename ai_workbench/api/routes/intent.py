from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.intent_router import RuleBasedIntentClassifier, _decision_metadata, _maybe_apply_utility_extractor, build_intent_routing_metadata, compact_utility_context
from ai_workbench.core.schema.route import RouteKind, RouteTarget


router = APIRouter(prefix="/api/intent", tags=["intent"])


class UtilityTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class RouteTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    session_id: str | None = None
    default_agent_id: str | None = None
    include_utility: bool = True


@router.get("/utility-llm/status")
def utility_llm_status(state: RuntimeState = Depends(get_state)) -> dict:
    return state.utility_llm.status(state.app_settings.get())


@router.post("/utility-llm/test-title")
async def test_utility_title(payload: UtilityTestRequest, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        result = await state.utility_llm.generate_title(payload.text, state.app_settings.get())
    except Exception as exc:
        raise_error(400, getattr(exc, "code", "UTILITY_LLM_TEST_FAILED"), str(exc) or "Utility LLM title test failed.")
    return {"ok": True, "title": result["title"], "backend": "utility_llm", "warnings": []}


@router.post("/utility-llm/test-json")
async def test_utility_json(payload: UtilityTestRequest, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        try:
            extracted = await state.utility_llm.extract_intent_json(
                payload.text,
                state.app_settings.get(),
                context=compact_utility_context(
                    settings=state.app_settings.get(),
                    agent_registry=state.agents,
                    agent_config_store=state.agent_configs,
                    knowledge_store=state.knowledge,
                ),
            )
        except TypeError:
            extracted = await state.utility_llm.extract_intent_json(payload.text, state.app_settings.get())
    except Exception as exc:
        raise_error(400, getattr(exc, "code", "UTILITY_LLM_TEST_FAILED"), str(exc) or "Utility LLM JSON extraction test failed.")
    return {
        "ok": True,
        "result": {
            "intent": extracted["intent"],
            "confidence": extracted["confidence"],
            "slots": {
                key: value
                for key, value in {
                    "target_agent_hint": extracted.get("target_agent_hint"),
                    "kb_hint": extracted.get("kb_hint"),
                    "query": extracted.get("query"),
                    "command_hint": extracted.get("command_hint"),
                }.items()
                if value
            },
        },
        "warnings": [],
    }


@router.post("/utility-llm/unload")
def unload_utility_llm(state: RuntimeState = Depends(get_state)) -> dict:
    return state.utility_llm.unload()


@router.post("/test-route")
async def test_route(payload: RouteTestRequest, state: RuntimeState = Depends(get_state)) -> dict:
    text = payload.text.strip()
    if not text:
        raise_error(422, "INTENT_ROUTE_TEST_EMPTY_INPUT", "Text must not be empty.")
    session = None
    if payload.session_id:
        try:
            session = state.sessions.get_session(payload.session_id)
        except KeyError:
            raise_error(404, "SESSION_NOT_FOUND", f"Session not found: {payload.session_id}")
    if session is None:
        default_agent_id = payload.default_agent_id or "chat"
        session = SimpleNamespace(session_id="", default_agent_id=default_agent_id, context_mode="single_assistant", waiting_run_id=None)
    if payload.default_agent_id:
        session = SimpleNamespace(
            session_id=getattr(session, "session_id", ""),
            default_agent_id=payload.default_agent_id,
            context_mode=getattr(session, "context_mode", "single_assistant"),
            waiting_run_id=getattr(session, "waiting_run_id", None),
        )
    route = RouteTarget(
        kind=RouteKind.AGENT,
        target_id=getattr(session, "default_agent_id", "chat"),
        action_id="default",
        args=text,
        raw_input=text,
        session_id=getattr(session, "session_id", ""),
    )
    if not getattr(session, "session_id", ""):
        classifier = RuleBasedIntentClassifier()
        settings = state.app_settings.get()
        prediction = classifier.classify(
            text,
            settings=settings,
            agent_registry=state.agents,
            agent_config_store=state.agent_configs,
            knowledge_store=state.knowledge,
        )
        prediction = await _maybe_apply_utility_extractor(
            text=text,
            prediction=prediction,
            settings=settings,
            utility_llm_service=state.utility_llm if payload.include_utility else None,
            agent_registry=state.agents,
            agent_config_store=state.agent_configs,
            knowledge_store=state.knowledge,
        )
        try:
            agent = state.agents.get(route.target_id or "")
        except KeyError:
            agent = SimpleNamespace(id=route.target_id or "", type="prompt")
        decision = _decision_metadata(
            session=session,
            route=route,
            prediction=prediction,
            mode=getattr(settings, "intent_routing_mode", "shadow"),
            settings=settings,
            agent=agent,
            agent_registry=state.agents,
            agent_config_store=state.agent_configs,
            knowledge_store=state.knowledge,
        )
        return {
            "ok": True,
            "decision": {
                "enabled": bool(getattr(settings, "intent_routing_enabled", False)),
                "mode": getattr(settings, "intent_routing_mode", "shadow"),
                "eligible": True,
                "eligibility_scope": "no_session",
                "bypassed": False,
                **decision,
            },
        }
    decision = await build_intent_routing_metadata(
        session=session,
        route=route,
        agent_registry=state.agents,
        agent_config_store=state.agent_configs,
        app_settings_store=state.app_settings,
        knowledge_store=state.knowledge,
        classifier=RuleBasedIntentClassifier(),
        utility_llm_service=state.utility_llm if payload.include_utility else None,
    )
    return {"ok": True, "decision": decision or {"eligible": False, "bypassed": True, "bypass_reason": "unavailable"}}
