# AI Context

This is the lightweight Codex entry point. Its job is task routing, not the
full project contract.

## Fixed Entry Rules

1. Identify the task type before reading or searching broadly.
2. Read the matching `docs/ai/TASK_*.md` card first.
3. From the task card, read only the listed contract docs and likely source
   entry points needed for the change.
4. Do not default to whole-repository search. Use targeted source search only
   after the task card and contracts are insufficient.
5. Interface, protocol, settings, metadata, or user workflow changes must update
   the relevant contract docs in the same change.
6. User-visible frontend text changes must update every supported locale under
   `frontend/src/i18n/resources`.
7. Agent or Capability manifest changes must regenerate the generated registry
   with `uv run python scripts/generate_registry_docs.py`.
8. Keep detailed rules in task cards or contract docs, not in this file.

## Task Map

- [Agent tasks](ai/TASK_AGENT.md): create or modify Prompt Agents, Script Agents,
  Agent actions, Script ctx usage, or Agent manifests.
- [Capability tasks](ai/TASK_CAPABILITY.md): create or modify Capabilities,
  slash commands, Capability manifests, and command output contracts.
- [Settings tasks](ai/TASK_SETTINGS.md): change General settings, AgentConfig,
  CapabilityConfig, Model Profiles, title settings, or settings UI contracts.
- [Runtime tasks](ai/TASK_RUNTIME.md): change routing, run lifecycle, streaming,
  attachments, provider status, model unload, or runtime metadata.
- [Knowledge tasks](ai/TASK_KNOWLEDGE.md): change Knowledge/RAG settings,
  indexing, retrieval, session KB bindings, or Knowledge context injection.
- [Memory and Worldbook tasks](ai/TASK_MEMORY_WORLDBOOK.md): change Core Memory,
  Worldbook settings, APIs, matching, bindings, or runtime context injection.
- [Intent Routing tasks](ai/TASK_INTENT_ROUTING.md): change semantic routing,
  Utility LLM slot extraction, Route Test, safe auto-route behavior, or route
  metadata.
- [Frontend UI tasks](ai/TASK_FRONTEND_UI.md): change reusable UI primitives,
  chat rendering, settings panels, i18n, or frontend contract wiring.
- [ComfyUI tasks](ai/TASK_COMFYUI.md): change ComfyUI Capability, ComfyUI Agent,
  workflow/preset library behavior, or preset YAML.
- [Docs maintenance](ai/DOCS_MAINTENANCE.md): maintain document ownership,
  line-count limits, and report requirements.
- [Docs refactor plan](ai/DOCS_REFACTOR_PLAN.md): current duplication audit and
  staged contract split plan.

## Global Boundaries

- Do not put historical rules, full protocols, or long avoid lists back into
  this file.
- Put long topic contracts under `docs/contracts/<topic>.md` once those contracts
  exist; keep task cards as routing summaries.
- Keep `docs/AI_CONTEXT.md` under 150 lines.
- Keep each `docs/ai/TASK_*.md` under 120 lines.
- If only UI style changes and no behavior, schema, metadata, or workflow changes
  occur, contract docs usually do not need updates.
