from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error


router = APIRouter(prefix="/api/intent", tags=["intent"])


class UtilityTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


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
