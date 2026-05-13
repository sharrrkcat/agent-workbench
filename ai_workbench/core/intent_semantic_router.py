from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

from ai_workbench.core.embedding import embed_texts
from ai_workbench.core.intent_router import (
    CUSTOM_EXAMPLE_FIELDS,
    INTENT_DEFINITIONS,
    _comma_values,
    _line_values,
    _normalize_text,
    _short_text,
)


BUILT_IN_EXAMPLES_VERSION = "round6a-v1"
SEMANTIC_SOURCE = "embedding_semantic_router"
SEMANTIC_PROFILE_MISSING = "semantic_router_profile_missing"
SEMANTIC_PROFILE_DISABLED = "semantic_router_profile_disabled"
SEMANTIC_EMBEDDING_UNAVAILABLE = "semantic_router_embedding_unavailable"
SEMANTIC_INDEX_BUILD_FAILED = "semantic_router_index_build_failed"
SEMANTIC_INTENT_MIN_SCORE = 0.2
SEMANTIC_INTENT_MIN_MARGIN = 0.03
SEMANTIC_KB_MIN_SCORE = 0.2
SEMANTIC_AGENT_MIN_SCORE = 0.2
SEMANTIC_COMMAND_MIN_SCORE = 0.2
SEMANTIC_INDEX_TTL_SECONDS = 60.0
MAX_TOP_CANDIDATES = 8


@dataclass(frozen=True)
class SemanticRouteCandidate:
    id: str
    kind: str
    text: str
    intent: str | None = None
    source: str | None = None
    kb_id: str | None = None
    kb_name: str | None = None
    agent_id: str | None = None
    action_id: str | None = None
    command_name: str | None = None
    capability_id: str | None = None
    field: str | None = None
    safe: bool | None = None
    weak: bool = False

    def document_text(self) -> str:
        prefix = self.intent or self.kind
        return f"{prefix}: {self.text}"

    def compact(self, score: float | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "text_preview": _short_text(self.text, 120),
        }
        for key in ("intent", "source", "kb_id", "kb_name", "agent_id", "action_id", "command_name", "capability_id", "field"):
            value = getattr(self, key)
            if value not in (None, ""):
                payload[key] = value
        if self.kb_id:
            payload["knowledge_base_id"] = self.kb_id
        if self.kb_name:
            payload["knowledge_base_name"] = self.kb_name
        if self.safe is not None:
            payload["safe"] = self.safe
        if self.weak:
            payload["weak"] = True
        if score is not None:
            payload["score"] = round(float(score), 4)
        return payload


@dataclass
class SemanticRouteIndex:
    key: str
    version: str
    profile_id: str
    candidates: list[SemanticRouteCandidate]
    vectors: list[list[float]]
    built_at: float = field(default_factory=time.monotonic)

    @property
    def summary(self) -> dict[str, int]:
        return candidate_summary(self.candidates)


@dataclass
class SemanticRouteDecision:
    source: str = SEMANTIC_SOURCE
    predicted_intent: str = "chat"
    confidence: float = 0.0
    semantic_score: float = 0.0
    semantic_margin: float = 0.0
    route_action: str = "metadata_only"
    auto_executable: bool = False
    embedding_model_profile_id: str | None = None
    semantic_index_version: str | None = None
    top_candidates: list[dict[str, Any]] = field(default_factory=list)
    kb_candidate: dict[str, Any] | None = None
    agent_candidate: dict[str, Any] | None = None
    action_candidate: dict[str, Any] | None = None
    command_candidate: dict[str, Any] | None = None
    candidate_summary: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    sub_intents: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "predicted_intent": self.predicted_intent,
            "confidence": round(self.confidence, 4),
            "semantic_score": round(self.semantic_score, 4),
            "semantic_margin": round(self.semantic_margin, 4),
            "route_action": self.route_action,
            "auto_executable": self.auto_executable,
            "embedding_model_profile_id": self.embedding_model_profile_id,
            "semantic_index_version": self.semantic_index_version,
            "top_candidates": self.top_candidates,
            "kb_candidate": self.kb_candidate,
            "agent_candidate": self.agent_candidate,
            "action_candidate": self.action_candidate,
            "command_candidate": self.command_candidate,
            "candidate_summary": self.candidate_summary,
            "warnings": self.warnings,
            "sub_intents": self.sub_intents,
        }


class SemanticRouteIndexBuilder:
    def build_candidates(
        self,
        *,
        settings: Any = None,
        agent_registry: Any = None,
        agent_config_store: Any = None,
        knowledge_store: Any = None,
        capability_registry: Any = None,
        command_registry: Any = None,
    ) -> list[SemanticRouteCandidate]:
        candidates: list[SemanticRouteCandidate] = []
        candidates.extend(_intent_candidates(settings))
        candidates.extend(_knowledge_candidates(knowledge_store))
        candidates.extend(_agent_candidates(agent_registry, agent_config_store))
        candidates.extend(_command_candidates(capability_registry, command_registry))
        return candidates

    def index_key(
        self,
        *,
        profile: Any,
        settings: Any = None,
        candidates: list[SemanticRouteCandidate],
    ) -> str:
        payload = {
            "built_in_examples_version": BUILT_IN_EXAMPLES_VERSION,
            "profile": _profile_fingerprint(profile),
            "settings_updated_at": str(getattr(settings, "updated_at", "")),
            "candidates": [candidate.compact() for candidate in candidates],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


class SemanticRouter:
    def __init__(self, *, ttl_seconds: float = SEMANTIC_INDEX_TTL_SECONDS, builder: SemanticRouteIndexBuilder | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self.builder = builder or SemanticRouteIndexBuilder()
        self._index: SemanticRouteIndex | None = None

    def candidate_summary(
        self,
        *,
        settings: Any = None,
        agent_registry: Any = None,
        agent_config_store: Any = None,
        knowledge_store: Any = None,
        capability_registry: Any = None,
        command_registry: Any = None,
    ) -> dict[str, int]:
        return candidate_summary(
            self.builder.build_candidates(
                settings=settings,
                agent_registry=agent_registry,
                agent_config_store=agent_config_store,
                knowledge_store=knowledge_store,
                capability_registry=capability_registry,
                command_registry=command_registry,
            )
        )

    def decide(
        self,
        text: str,
        *,
        settings: Any,
        knowledge_store: Any,
        model_backend: Any,
        agent_registry: Any = None,
        agent_config_store: Any = None,
        capability_registry: Any = None,
        command_registry: Any = None,
    ) -> dict[str, Any]:
        profile_id = str(getattr(settings, "intent_routing_embedding_model_profile_id", "") or "").strip()
        if not profile_id:
            return SemanticRouteDecision(
                embedding_model_profile_id=None,
                warnings=[SEMANTIC_PROFILE_MISSING],
                candidate_summary=self.candidate_summary(
                    settings=settings,
                    agent_registry=agent_registry,
                    agent_config_store=agent_config_store,
                    knowledge_store=knowledge_store,
                    capability_registry=capability_registry,
                    command_registry=command_registry,
                ),
            ).model_dump()
        try:
            profile = knowledge_store.get_embedding_profile(profile_id)
        except Exception:
            return SemanticRouteDecision(embedding_model_profile_id=profile_id, warnings=[SEMANTIC_PROFILE_MISSING]).model_dump()
        if not getattr(profile, "enabled", False):
            return SemanticRouteDecision(embedding_model_profile_id=profile.id, warnings=[SEMANTIC_PROFILE_DISABLED]).model_dump()
        try:
            index = self._get_or_build_index(
                settings=settings,
                profile=profile,
                knowledge_store=knowledge_store,
                model_backend=model_backend,
                agent_registry=agent_registry,
                agent_config_store=agent_config_store,
                capability_registry=capability_registry,
                command_registry=command_registry,
            )
            settings_obj = knowledge_store.get_settings()
            query = embed_texts(
                backend=model_backend,
                profile=profile,
                texts=[text],
                purpose="query",
                device=getattr(settings_obj, "local_model_device", "auto"),
            )["vectors"][0]
        except Exception:
            return SemanticRouteDecision(
                embedding_model_profile_id=profile.id,
                warnings=[SEMANTIC_EMBEDDING_UNAVAILABLE],
            ).model_dump()
        return _rank_decision(query, index).model_dump()

    def _get_or_build_index(
        self,
        *,
        settings: Any,
        profile: Any,
        knowledge_store: Any,
        model_backend: Any,
        agent_registry: Any,
        agent_config_store: Any,
        capability_registry: Any,
        command_registry: Any,
    ) -> SemanticRouteIndex:
        candidates = self.builder.build_candidates(
            settings=settings,
            agent_registry=agent_registry,
            agent_config_store=agent_config_store,
            knowledge_store=knowledge_store,
            capability_registry=capability_registry,
            command_registry=command_registry,
        )
        key = self.builder.index_key(profile=profile, settings=settings, candidates=candidates)
        now = time.monotonic()
        if self._index is not None and self._index.key == key and now - self._index.built_at <= self.ttl_seconds:
            return self._index
        if not candidates:
            raise RuntimeError(SEMANTIC_INDEX_BUILD_FAILED)
        settings_obj = knowledge_store.get_settings()
        result = embed_texts(
            backend=model_backend,
            profile=profile,
            texts=[candidate.document_text() for candidate in candidates],
            purpose="document",
            device=getattr(settings_obj, "local_model_device", "auto"),
        )
        version = key[:12]
        self._index = SemanticRouteIndex(
            key=key,
            version=version,
            profile_id=profile.id,
            candidates=candidates,
            vectors=result["vectors"],
        )
        return self._index


def candidate_summary(candidates: list[SemanticRouteCandidate]) -> dict[str, int]:
    return {
        "intent_examples": sum(1 for item in candidates if item.kind == "intent_example"),
        "knowledge_bases": sum(1 for item in candidates if item.kind == "knowledge_base"),
        "agents": sum(1 for item in candidates if item.kind == "agent_target"),
        "actions": sum(1 for item in candidates if item.kind == "agent_action"),
        "commands": sum(1 for item in candidates if item.kind == "command"),
        "total": len(candidates),
    }


def semantic_router_status(
    *,
    settings: Any,
    knowledge_store: Any,
    semantic_router: SemanticRouter,
    model_backend: Any = None,
    agent_registry: Any = None,
    agent_config_store: Any = None,
    capability_registry: Any = None,
    command_registry: Any = None,
) -> dict[str, Any]:
    profile_id = str(getattr(settings, "intent_routing_embedding_model_profile_id", "") or "").strip()
    status = "no_profile_selected"
    if profile_id:
        try:
            profile = knowledge_store.get_embedding_profile(profile_id)
            status = "ready" if getattr(profile, "enabled", False) else "profile_unavailable"
        except Exception:
            status = "profile_unavailable"
    if status == "ready":
        try:
            from ai_workbench.core.knowledge_models import backend_availability

            if not bool(backend_availability().get("available", False)):
                status = "embedding_backend_unavailable"
        except Exception:
            status = "embedding_backend_unavailable"
    return {
        "status": status,
        "embedding_model_profile_id": profile_id or None,
        "candidate_summary": semantic_router.candidate_summary(
            settings=settings,
            agent_registry=agent_registry,
            agent_config_store=agent_config_store,
            knowledge_store=knowledge_store,
            capability_registry=capability_registry,
            command_registry=command_registry,
        ),
        "index": {
            "version": semantic_router._index.version if semantic_router._index is not None else None,
            "stale": True,
            "will_rebuild_lazily": True,
        },
    }


def _rank_decision(query: list[float], index: SemanticRouteIndex) -> SemanticRouteDecision:
    scored = [
        (candidate, _cosine(query, vector))
        for candidate, vector in zip(index.candidates, index.vectors, strict=False)
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    intent_scores: dict[str, float] = {}
    for candidate, score in scored:
        if candidate.kind != "intent_example" or not candidate.intent:
            continue
        intent_scores[candidate.intent] = max(intent_scores.get(candidate.intent, -1.0), score)
    ordered_intents = sorted(intent_scores.items(), key=lambda item: item[1], reverse=True)
    top_intent, top_score = ordered_intents[0] if ordered_intents else ("chat", 0.0)
    second_score = ordered_intents[1][1] if len(ordered_intents) > 1 else 0.0
    margin = top_score - second_score
    warnings: list[str] = []
    if top_score < SEMANTIC_INTENT_MIN_SCORE:
        warnings.append("low_confidence")
        top_intent = "chat"
    elif margin < SEMANTIC_INTENT_MIN_MARGIN:
        warnings.append("ambiguous_intent")
    sub_intents = [intent for intent, score in ordered_intents[:3] if intent != top_intent and score >= SEMANTIC_INTENT_MIN_SCORE and top_score - score <= SEMANTIC_INTENT_MIN_MARGIN]
    if len(sub_intents) >= 1 and top_intent != "chat":
        warnings.append("compound_intent_not_auto_routed")
    kb_candidate = _best_candidate(scored, "knowledge_base", SEMANTIC_KB_MIN_SCORE)
    agent_candidate = _best_candidate(scored, "agent_target", SEMANTIC_AGENT_MIN_SCORE)
    action_candidate = _best_candidate(scored, "agent_action", SEMANTIC_AGENT_MIN_SCORE)
    command_candidate = _best_candidate(scored, "command", SEMANTIC_COMMAND_MIN_SCORE)
    if top_intent == "knowledge_query" and kb_candidate is None:
        warnings.append("no_semantic_kb_candidate")
    return SemanticRouteDecision(
        predicted_intent="compound" if "compound_intent_not_auto_routed" in warnings and margin < SEMANTIC_INTENT_MIN_MARGIN else top_intent,
        confidence=max(0.0, min(1.0, top_score)),
        semantic_score=top_score,
        semantic_margin=margin,
        embedding_model_profile_id=index.profile_id,
        semantic_index_version=index.version,
        top_candidates=[candidate.compact(score) for candidate, score in scored[:MAX_TOP_CANDIDATES]],
        kb_candidate=kb_candidate,
        agent_candidate=agent_candidate,
        action_candidate=action_candidate,
        command_candidate=command_candidate,
        candidate_summary=index.summary,
        warnings=warnings,
        sub_intents=sub_intents,
    )


def _best_candidate(scored: list[tuple[SemanticRouteCandidate, float]], kind: str, min_score: float) -> dict[str, Any] | None:
    matches = [(candidate, score) for candidate, score in scored if candidate.kind == kind and score >= min_score]
    if not matches:
        return None
    matches.sort(key=lambda item: (item[1], _field_priority(item[0].field)), reverse=True)
    candidate, score = matches[0]
    return candidate.compact(score)
    return None


def _field_priority(field: str | None) -> int:
    return {"alias": 5, "example": 4, "description": 3, "label": 3, "name": 2, "id": 1, "capability_name": 1}.get(field or "", 0)


def _intent_candidates(settings: Any) -> list[SemanticRouteCandidate]:
    candidates: list[SemanticRouteCandidate] = []
    for intent in INTENT_DEFINITIONS:
        for index, text in enumerate(intent.examples):
            candidates.append(
                SemanticRouteCandidate(
                    id=f"intent:{intent.id}:built_in:{index}",
                    kind="intent_example",
                    intent=intent.id,
                    source="built_in",
                    text=text,
                )
            )
        for index, text in enumerate(_line_values(getattr(settings, CUSTOM_EXAMPLE_FIELDS.get(intent.id, ""), ""), 100, 300)):
            candidates.append(
                SemanticRouteCandidate(
                    id=f"intent:{intent.id}:custom:{index}",
                    kind="intent_example",
                    intent=intent.id,
                    source="custom",
                    text=text,
                )
            )
    diagnostics = {
        "action_route": ["use this agent action", "run the summarize action", "call the formal action"],
        "compound": ["search the knowledge base and then make an image", "translate this and run a command"],
    }
    for intent_id, examples in diagnostics.items():
        for index, text in enumerate(examples):
            candidates.append(SemanticRouteCandidate(id=f"intent:{intent_id}:diagnostic:{index}", kind="intent_example", intent=intent_id, source="built_in", text=text))
    return candidates


def _knowledge_candidates(knowledge_store: Any) -> list[SemanticRouteCandidate]:
    if knowledge_store is None:
        return []
    try:
        bases = knowledge_store.list_knowledge_bases()
    except Exception:
        return []
    candidates: list[SemanticRouteCandidate] = []
    for kb in bases:
        if not getattr(kb, "enabled", False):
            continue
        fields = [("name", getattr(kb, "name", "") or kb.id), ("description", getattr(kb, "description", "") or "")]
        fields.extend(("alias", alias) for alias in _comma_values(getattr(kb, "aliases_text", ""), 50, 120))
        for field, text in fields:
            if not str(text).strip():
                continue
            candidates.append(SemanticRouteCandidate(id=f"kb:{kb.id}:{field}:{len(candidates)}", kind="knowledge_base", kb_id=kb.id, kb_name=getattr(kb, "name", "") or kb.id, field=field, text=str(text)))
    return candidates


def _agent_candidates(agent_registry: Any, agent_config_store: Any) -> list[SemanticRouteCandidate]:
    if agent_registry is None:
        return []
    try:
        agents = agent_registry.list()
    except Exception:
        return []
    candidates: list[SemanticRouteCandidate] = []
    for agent in agents:
        config = agent_config_store.get_config(agent.id) if agent_config_store is not None else {}
        runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
        for field, text in [
            ("id", agent.id),
            ("name", getattr(agent, "name", "") or agent.id),
            ("description", getattr(agent, "description", "") or ""),
        ]:
            if str(text).strip():
                candidates.append(SemanticRouteCandidate(id=f"agent:{agent.id}:{field}", kind="agent_target", agent_id=agent.id, field=field, text=str(text)))
        for index, alias in enumerate(_comma_values(runtime.get("intent_routing_aliases_text", ""), 50, 120)):
            candidates.append(SemanticRouteCandidate(id=f"agent:{agent.id}:alias:{index}", kind="agent_target", agent_id=agent.id, field="alias", text=alias))
        for index, example in enumerate(_line_values(runtime.get("intent_routing_examples_text", ""), 100, 300)):
            candidates.append(SemanticRouteCandidate(id=f"agent:{agent.id}:example:{index}", kind="agent_target", agent_id=agent.id, field="example", text=example))
        for action in getattr(agent, "actions", []) or []:
            for field, text in [("id", action.id), ("label", action.label or ""), ("description", action.description or "")]:
                if str(text).strip():
                    candidates.append(SemanticRouteCandidate(id=f"action:{agent.id}:{action.id}:{field}", kind="agent_action", agent_id=agent.id, action_id=action.id, field=field, text=str(text), weak=True))
    return candidates


def _command_candidates(capability_registry: Any, command_registry: Any) -> list[SemanticRouteCandidate]:
    if command_registry is None:
        return []
    try:
        commands = command_registry.list()
    except Exception:
        return []
    candidates: list[SemanticRouteCandidate] = []
    for command in commands:
        capability_name = command.capability_id
        if capability_registry is not None:
            try:
                capability = capability_registry.get(command.capability_id)
                capability_name = getattr(capability, "name", "") or command.capability_id
            except Exception:
                capability_name = command.capability_id
        for field, text in [
            ("name", command.name),
            ("description", command.description or ""),
            ("capability_name", capability_name),
        ]:
            if str(text).strip():
                candidates.append(
                    SemanticRouteCandidate(
                        id=f"command:{command.name}:{field}",
                        kind="command",
                        capability_id=command.capability_id,
                        command_name=command.name,
                        field=field,
                        text=str(text),
                        safe=bool(command.safe),
                        weak=True,
                    )
                )
    return candidates


def _profile_fingerprint(profile: Any) -> dict[str, Any]:
    return {
        "id": getattr(profile, "id", ""),
        "model_path": getattr(profile, "model_path", ""),
        "normalize": getattr(profile, "normalize", True),
        "document_instruction": getattr(profile, "document_instruction", ""),
        "query_instruction": getattr(profile, "query_instruction", ""),
        "dimension": getattr(profile, "dimension", None),
        "updated_at": str(getattr(profile, "updated_at", "")),
    }


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
