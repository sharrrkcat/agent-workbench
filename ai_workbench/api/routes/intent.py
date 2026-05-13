from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.intent_router import _decision_metadata, _maybe_apply_utility_slots, _semantic_prediction, build_intent_routing_metadata, compact_utility_context
from ai_workbench.core.intent_semantic_router import semantic_router_status
from ai_workbench.core.schema.route import RouteKind, RouteTarget
from ai_workbench.core.utility_llm import scan_utility_models


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


@router.get("/semantic-router/status")
def get_semantic_router_status(state: RuntimeState = Depends(get_state)) -> dict:
    return semantic_router_status(
        settings=state.app_settings.get(),
        knowledge_store=state.knowledge,
        semantic_router=state.semantic_router,
        model_backend=state.knowledge_model_backend,
        agent_registry=state.agents,
        agent_config_store=state.agent_configs,
        capability_registry=state.capabilities,
        command_registry=state.commands,
    )


@router.get("/utility-llm/models/scan")
def scan_utility_llm_models(state: RuntimeState = Depends(get_state)) -> dict:
    return scan_utility_models(getattr(state.utility_llm, "root", None))


@router.post("/utility-llm/test-title")
async def test_utility_title(payload: UtilityTestRequest, state: RuntimeState = Depends(get_state)) -> dict:
    try:
        result = await state.utility_llm.generate_title(payload.text, state.app_settings.get())
    except Exception as exc:
        code = getattr(exc, "code", "UTILITY_LLM_TEST_FAILED")
        return {"ok": False, "reason": code, "error": {"code": code, "message": str(exc) or "Utility LLM title test failed."}, "warnings": []}
    return {
        "ok": True,
        "title": result["title"],
        "backend": result.get("backend") or "utility_llm",
        "model_profile_id": result.get("model_profile_id"),
        "model_profile_name": result.get("model_profile_name"),
        "provider_profile_id": result.get("provider_profile_id"),
        "provider_label": result.get("provider_label"),
        "requested_model_id": result.get("requested_model_id"),
        "warnings": [],
    }


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
        code = getattr(exc, "code", "UTILITY_LLM_TEST_FAILED")
        return {"ok": False, "reason": code, "error": {"code": code, "message": str(exc) or "Utility LLM JSON extraction test failed."}, "warnings": []}
    return {
        "ok": True,
        "backend": extracted.get("_utility_backend") or "utility_llm",
        "model_profile_id": extracted.get("_model_profile_id"),
        "model_profile_name": extracted.get("_model_profile_name"),
        "provider_label": extracted.get("_provider_label"),
        "requested_model_id": extracted.get("_requested_model_id"),
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
    try:
        return state.utility_llm.unload(state.app_settings.get())
    except TypeError:
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
        settings = state.app_settings.get()
        prediction = _semantic_prediction(
            text=text,
            settings=settings,
            agent_registry=state.agents,
            agent_config_store=state.agent_configs,
            knowledge_store=state.knowledge,
            knowledge_model_backend=state.knowledge_model_backend,
            capability_registry=state.capabilities,
            command_registry=state.commands,
            semantic_router=state.semantic_router,
        )
        prediction = await _maybe_apply_utility_slots(
            text=text,
            prediction=prediction,
            settings=settings,
            utility_llm_service=state.utility_llm if payload.include_utility else None,
            agent_registry=state.agents,
            agent_config_store=state.agent_configs,
            knowledge_store=state.knowledge,
            runtime_registry=state.runtimes,
            capability_config_store=state.capability_configs,
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
            capability_config_store=state.capability_configs,
            runtime_registry=state.runtimes,
        )
        return {
            "ok": True,
            "decision": _route_test_decision({
                "enabled": bool(getattr(settings, "intent_routing_enabled", False)),
                "mode": getattr(settings, "intent_routing_mode", "shadow"),
                "evaluated": True,
                "eligible": True,
                "eligibility_scope": "no_session",
                "bypassed": False,
                **decision,
            }),
        }
    decision = await build_intent_routing_metadata(
        session=session,
        route=route,
        agent_registry=state.agents,
        agent_config_store=state.agent_configs,
        app_settings_store=state.app_settings,
        knowledge_store=state.knowledge,
        knowledge_model_backend=state.knowledge_model_backend,
        capability_registry=state.capabilities,
        capability_config_store=state.capability_configs,
        runtime_registry=state.runtimes,
        command_registry=state.commands,
        semantic_router=state.semantic_router,
        utility_llm_service=state.utility_llm if payload.include_utility else None,
    )
    return {"ok": True, "decision": _route_test_decision(decision or {"eligible": False, "bypassed": True, "bypass_reason": "unavailable"})}


def _route_test_decision(decision: dict) -> dict:
    payload = dict(decision)
    if payload.get("auto_executable"):
        payload["would_execute"] = True
    payload["executed"] = False
    payload["semantic_candidate"] = {
        "spec_id": payload.get("route_spec_id"),
        "intent": payload.get("predicted_intent"),
        "action": payload.get("pet_action"),
        "score": payload.get("semantic_score"),
    }
    payload["utility"] = {
        "required": bool(payload.get("utility_required")),
        "available": bool(payload.get("utility_available")),
        "used": bool(payload.get("utility_used")),
        "ok": bool(payload.get("utility_ok")),
        "error_code": payload.get("utility_error_code"),
    }
    payload["validation"] = {
        "ok": bool(payload.get("validation_ok")),
        "validator_id": payload.get("validator_id"),
        "not_executed_reason": payload.get("not_executed_reason"),
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
    }
    return payload
