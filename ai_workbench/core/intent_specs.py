from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ExecutionMode = Literal["semantic_only", "utility_required", "diagnostic_only"]


@dataclass(frozen=True)
class SlotField:
    name: str
    type: str = "string"
    required: bool = False
    enum_values: tuple[str, ...] = ()
    max_chars: int | None = 200
    description: str = ""

    def compact_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "description": self.description,
        }
        if self.enum_values:
            payload["enum"] = list(self.enum_values)
        if self.max_chars is not None:
            payload["max_chars"] = self.max_chars
        return payload


@dataclass(frozen=True)
class SlotSchema:
    schema_id: str
    fields: tuple[SlotField, ...] = ()

    @property
    def required_fields(self) -> list[str]:
        return [field.name for field in self.fields if field.required]

    @property
    def allowed_values(self) -> dict[str, list[str]]:
        return {field.name: list(field.enum_values) for field in self.fields if field.enum_values}

    def compact_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "required": self.required_fields,
            "fields": [field.compact_dict() for field in self.fields],
        }


@dataclass(frozen=True)
class RouteSpec:
    id: str
    intent: str
    label: str
    description: str
    examples: tuple[str, ...] = ()
    execution_mode: ExecutionMode = "diagnostic_only"
    auto_executable: bool = False
    utility_required: bool = False
    validator_id: str | None = None
    executor_id: str | None = None
    slot_schema: SlotSchema | None = None
    safety_notes: tuple[str, ...] = ()
    metadata_kind: str | None = None

    def compact_dict(self, *, include_examples_preview: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "intent": self.intent,
            "label": self.label,
            "description": self.description,
            "execution_mode": self.execution_mode,
            "auto_executable": self.auto_executable,
            "utility_required": self.utility_required,
            "validator_id": self.validator_id,
            "executor_id": self.executor_id,
            "slot_schema_id": self.slot_schema.schema_id if self.slot_schema else None,
            "safety_notes": list(self.safety_notes[:4]),
            "metadata_kind": self.metadata_kind,
        }
        if include_examples_preview:
            payload["examples_preview"] = list(self.examples[:3])
        if self.slot_schema is not None:
            payload["slot_schema"] = self.slot_schema.compact_dict()
        return {key: value for key, value in payload.items() if value not in (None, [], {})}


@dataclass(frozen=True)
class ActionSpec:
    id: str
    parent_intent: str
    action: str
    label: str
    description: str
    examples: tuple[str, ...] = ()
    execution_mode: ExecutionMode = "diagnostic_only"
    auto_executable: bool = False
    utility_required: bool = True
    required_slots: tuple[str, ...] = ()
    optional_slots: tuple[str, ...] = ()
    validator_id: str | None = None
    executor_id: str | None = None
    safety_notes: tuple[str, ...] = ()

    def compact_dict(self, *, include_examples_preview: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "parent_intent": self.parent_intent,
            "action": self.action,
            "label": self.label,
            "description": self.description,
            "execution_mode": self.execution_mode,
            "auto_executable": self.auto_executable,
            "utility_required": self.utility_required,
            "required_slots": list(self.required_slots),
            "optional_slots": list(self.optional_slots),
            "validator_id": self.validator_id,
            "executor_id": self.executor_id,
            "safety_notes": list(self.safety_notes[:4]),
        }
        if include_examples_preview:
            payload["examples_preview"] = list(self.examples[:3])
        return {key: value for key, value in payload.items() if value not in (None, [], {})}


@dataclass(frozen=True)
class ExecutorPlan:
    route_action: str
    auto_executable: bool = False
    would_execute: bool = False
    target_agent_id: str | None = None
    target_action_id: str | None = None
    target_command: str | None = None
    generated_command: str | None = None
    temporary_knowledge_base_ids: list[str] = field(default_factory=list)
    knowledge_query_override: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def compact_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value not in (None, [], {})}


@dataclass(frozen=True)
class ValidatorResult:
    ok: bool
    not_executed_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    normalized_slots: dict[str, Any] = field(default_factory=dict)
    executor_plan: ExecutorPlan | None = None

    def compact_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "not_executed_reason": self.not_executed_reason,
            "warnings": self.warnings,
            "normalized_slots": self.normalized_slots,
            "executor_plan": self.executor_plan.compact_dict() if self.executor_plan else None,
        }
        return {key: value for key, value in payload.items() if value not in (None, [], {})}


KNOWLEDGE_QUERY_SLOT_SCHEMA = SlotSchema(
    schema_id="knowledge_query_slots",
    fields=(
        SlotField("intent", required=True, enum_values=("knowledge_query", "unknown"), description="Predicted intent id."),
        SlotField("query", required=True, max_chars=240, description="Short knowledge search query override."),
        SlotField("kb_hint", required=False, max_chars=120, description="Optional Knowledge Base name or alias."),
        SlotField("use_original_query", type="boolean", required=False, max_chars=None, description="Use the original user text when query is empty."),
        SlotField("kb_id", required=False, max_chars=120, description="Optional Knowledge Base id from candidates only."),
    ),
)

PET_COMMAND_SLOT_SCHEMA = SlotSchema(
    schema_id="pet_command_slots",
    fields=(
        SlotField("intent", required=True, enum_values=("pet_command", "unknown"), description="Predicted intent id."),
        SlotField("domain", required=True, enum_values=("workbench_pet", "real_pet", "fictional_character", "unclear"), description="Workbench desktop pet domain only."),
        SlotField("action", required=True, enum_values=("status", "wake", "tuck", "select", "reload", "unknown"), description="Allowlisted pet action."),
        SlotField("target_pet_hint", required=False, max_chars=120, description="Optional target pet name/id hint."),
        SlotField("source_pet_hint", required=False, max_chars=120, description="Optional current/source pet hint."),
    ),
)


def get_builtin_route_specs() -> tuple[RouteSpec, ...]:
    return (
        RouteSpec(
            id="chat",
            intent="chat",
            label="Chat",
            description="General conversation, writing, translation, and follow-up help.",
            examples=("继续", "解释一下", "还有什么方法", "translate this", "help me write"),
            execution_mode="semantic_only",
            auto_executable=True,
            utility_required=False,
            validator_id="chat_basic",
            executor_id="current_prompt_agent",
            metadata_kind="chat",
        ),
        RouteSpec(
            id="knowledge_query",
            intent="knowledge_query",
            label="Knowledge query",
            description="Questions that ask for project, document, or knowledge base grounded answers.",
            examples=("知识库里说了什么", "根据项目文档回答", "星球大战知识库里的内容", "what does the documentation say"),
            execution_mode="utility_required",
            auto_executable=True,
            utility_required=True,
            validator_id="knowledge_query",
            executor_id="knowledge_override",
            slot_schema=KNOWLEDGE_QUERY_SLOT_SCHEMA,
            safety_notes=("Temporary Knowledge override only.", "Do not persist session Knowledge bindings."),
            metadata_kind="knowledge_query",
        ),
        RouteSpec(
            id="pet_command",
            intent="pet_command",
            label="Pet command",
            description="Narrow Workbench Pet status, wake, tuck, select, and reload commands.",
            examples=("看看宠物状态", "唤醒宠物", "隐藏宠物", "切换宠物", "reload pet", "wake the pet"),
            execution_mode="utility_required",
            auto_executable=True,
            utility_required=True,
            validator_id="pet_command",
            executor_id="pet_command",
            slot_schema=PET_COMMAND_SLOT_SCHEMA,
            safety_notes=("Workbench desktop pet only.", "Real pet, fictional character, or unclear domain must not execute."),
            metadata_kind="pet_command",
        ),
        RouteSpec(
            id="image_generation",
            intent="image_generation",
            label="Image generation",
            description="Requests to create or draw an image.",
            examples=("帮我生成一张图片", "画一张图", "make an image", "generate a picture", "生成角色立绘"),
            execution_mode="diagnostic_only",
            auto_executable=False,
            utility_required=False,
            validator_id="diagnostic_only",
            executor_id=None,
            safety_notes=("Diagnostic-only until action routing is designed.",),
            metadata_kind="image_generation",
        ),
        RouteSpec(
            id="command_like",
            intent="command_like",
            label="Command-like",
            description="Requests that resemble operational commands or cleanup actions.",
            examples=("释放显存", "清理内存", "删除这个", "运行命令", "free memory"),
            execution_mode="diagnostic_only",
            auto_executable=False,
            utility_required=False,
            validator_id="diagnostic_only",
            metadata_kind="command_like",
        ),
        RouteSpec(
            id="agent_route",
            intent="agent_route",
            label="Agent route",
            description="Requests that appear to ask for another agent or specialized route.",
            examples=("找翻译 agent", "交给图片助手", "route this to the image agent"),
            execution_mode="diagnostic_only",
            auto_executable=False,
            utility_required=False,
            validator_id="diagnostic_only",
            metadata_kind="agent_route",
        ),
        RouteSpec(
            id="action_route",
            intent="action_route",
            label="Action route",
            description="Requests that appear to ask for an Agent action.",
            examples=("use this agent action", "run the summarize action", "call the formal action"),
            execution_mode="diagnostic_only",
            auto_executable=False,
            utility_required=False,
            validator_id="diagnostic_only",
            metadata_kind="action_route",
        ),
        RouteSpec(
            id="compound",
            intent="compound",
            label="Compound",
            description="Requests that appear to contain multiple route intents.",
            examples=("search the knowledge base and then make an image", "translate this and run a command"),
            execution_mode="diagnostic_only",
            auto_executable=False,
            utility_required=False,
            validator_id="diagnostic_only",
            metadata_kind="compound",
        ),
    )


def get_builtin_action_specs() -> tuple[ActionSpec, ...]:
    base = {
        "parent_intent": "pet_command",
        "execution_mode": "utility_required",
        "auto_executable": True,
        "utility_required": True,
        "validator_id": "pet_command",
        "executor_id": "pet_command",
        "required_slots": ("domain", "action"),
        "optional_slots": ("target_pet_hint", "source_pet_hint"),
        "safety_notes": ("Workbench desktop pet only.",),
    }
    return (
        ActionSpec(id="pet.status", action="status", label="Pet status", description="Show Workbench Pet status.", examples=("看看宠物状态", "宠物现在怎么样", "pet status"), **base),
        ActionSpec(id="pet.wake", action="wake", label="Wake pet", description="Wake or summon the current Workbench Pet.", examples=("唤醒宠物", "召唤宠物", "把宠物叫出来", "summon the pet"), **base),
        ActionSpec(id="pet.tuck", action="tuck", label="Tuck pet", description="Hide or tuck away the current Workbench Pet.", examples=("隐藏宠物", "把宠物藏起来", "tuck the pet away"), **base),
        ActionSpec(id="pet.select", action="select", label="Select pet", description="Switch the active Workbench Pet.", examples=("把宠物换成 BD-1", "切换到另一个宠物", "select pet"), required_slots=("domain", "action", "target_pet_hint"), **{k: v for k, v in base.items() if k != "required_slots"}),
        ActionSpec(id="pet.reload", action="reload", label="Reload pet", description="Reload or refresh the current Workbench Pet.", examples=("重新加载宠物", "刷新宠物", "reload pet"), **base),
    )


def get_route_spec(intent_or_id: str | None) -> RouteSpec | None:
    key = str(intent_or_id or "").strip()
    return next((spec for spec in get_builtin_route_specs() if spec.id == key or spec.intent == key), None)


def get_action_spec(action_id: str | None) -> ActionSpec | None:
    key = str(action_id or "").strip()
    return next((spec for spec in get_builtin_action_specs() if spec.id == key), None)


def get_action_spec_for_intent_action(parent_intent: str | None, action: str | None) -> ActionSpec | None:
    return next((spec for spec in get_builtin_action_specs() if spec.parent_intent == parent_intent and spec.action == action), None)


def build_semantic_candidate_specs(
    *,
    settings: Any = None,
    agents: Any = None,
    capabilities: Any = None,
    knowledge_bases: Any = None,
) -> list[dict[str, Any]]:
    del agents, capabilities, knowledge_bases
    candidates: list[dict[str, Any]] = []
    custom_fields = {
        "chat": "intent_routing_chat_examples",
        "image_generation": "intent_routing_image_generation_examples",
        "knowledge_query": "intent_routing_knowledge_query_examples",
        "agent_route": "intent_routing_agent_route_examples",
        "command_like": "intent_routing_command_like_examples",
    }
    for spec in get_builtin_route_specs():
        for index, text in enumerate(spec.examples):
            candidates.append(_candidate_payload(spec=spec, text=text, index=index, source="built_in", field="example"))
        custom_field = custom_fields.get(spec.intent)
        for index, text in enumerate(_line_values(getattr(settings, custom_field or "", ""), 100, 300)):
            candidates.append(_candidate_payload(spec=spec, text=text, index=index, source="custom", field="example"))
    for action_spec in get_builtin_action_specs():
        for index, text in enumerate(action_spec.examples):
            candidates.append(_candidate_payload(action_spec=action_spec, text=text, index=index, source="built_in", field="example"))
    return candidates


def compact_specs_for_utility(prediction: dict[str, Any] | None = None) -> dict[str, Any]:
    prediction = prediction or {}
    route_spec = get_route_spec(str(prediction.get("predicted_intent") or ""))
    action_candidate = prediction.get("action_candidate")
    action_spec = None
    if isinstance(action_candidate, dict):
        action_spec = get_action_spec(action_candidate.get("action_spec_id"))
    if action_spec is None:
        slots = prediction.get("slots") if isinstance(prediction.get("slots"), dict) else {}
        action_spec = get_action_spec_for_intent_action(route_spec.intent if route_spec else None, slots.get("action"))
    routes = [route_spec.compact_dict() if route_spec else None]
    return {
        "top_route_specs": [item for item in routes if item],
        "top_action_specs": [action_spec.compact_dict() for action_spec in ([action_spec] if action_spec else [])],
    }


def _candidate_payload(
    *,
    text: str,
    index: int,
    source: str,
    field: str,
    spec: RouteSpec | None = None,
    action_spec: ActionSpec | None = None,
) -> dict[str, Any]:
    if spec is not None:
        return {
            "candidate_id": f"intent:{spec.id}:{source}:{index}",
            "spec_id": spec.id,
            "kind": "intent_example",
            "intent": spec.intent,
            "source": source,
            "field": field,
            "text": text,
            "text_preview": text[:120],
            "weak": spec.execution_mode == "diagnostic_only",
            "diagnostic": spec.execution_mode == "diagnostic_only",
        }
    assert action_spec is not None
    return {
        "candidate_id": f"action_spec:{action_spec.id}:{source}:{index}",
        "spec_id": action_spec.id,
        "kind": "action_spec",
        "intent": action_spec.parent_intent,
        "action_id": action_spec.id,
        "action": action_spec.action,
        "source": source,
        "field": field,
        "text": text,
        "text_preview": text[:120],
        "weak": False,
        "diagnostic": False,
    }


def _line_values(value: Any, max_items: int, max_chars: int) -> list[str]:
    items: list[str] = []
    for line in str(value or "").splitlines():
        text = line.strip()
        if not text:
            continue
        items.append(text[:max_chars])
        if len(items) >= max_items:
            break
    return items
