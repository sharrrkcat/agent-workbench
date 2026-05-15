# Docs Refactor Plan

## Current Responsibility Audit

- `README.md`: install/startup and broad user-facing feature overview. It also
  carries long details for Intent Routing, Utility LLM, Knowledge, settings,
  runtime memory, ComfyUI, and attachments that should become summaries.
- `docs/AI_CONTEXT.md`: previously mixed Codex task routing with full task rules.
  It is now intended to be a lightweight entry point that routes to task cards.
- `docs/RUNTIME_PROTOCOLS.md`: now acts as a runtime topic index and short
  summary layer. Long runtime/settings contracts live under `docs/contracts/`.
- `docs/EXTENSION_API.md`: owns Agent, Capability, ctx, config, and output
  contracts. Runtime, settings, Knowledge, Intent Routing, Utility LLM, memory,
  provider, and attachment details link to topic contracts.
- `docs/EXTENSION_ARCHITECTURE.md`: owns architecture and configuration ownership
  principles. Product/runtime details link to topic contracts.
- `docs/AGENT_DEVELOPMENT.md`: practical Agent templates and CLI workflow. It
  includes detailed ComfyUI Agent behavior that may later link to a contract.
- `docs/CAPABILITY_DEVELOPMENT.md`: practical Capability templates and command
  workflow. It includes detailed ComfyUI and Knowledge Capability behavior that
  should stay short or link outward.
- `docs/FRONTEND_UI_COMPONENTS.md`: concise UI primitive guidance. It is already
  close to its intended role.
- `docs/COMFYUI_PRESET_SCHEMA.md`: focused ComfyUI preset YAML contract. It should
  remain the canonical preset schema doc.

## Duplicate And Long Areas

- Intent Routing: repeated across AI_CONTEXT, README, RUNTIME_PROTOCOLS,
  EXTENSION_API, and EXTENSION_ARCHITECTURE.
- Utility LLM: repeated in Intent Routing, title generation, settings, and
  configuration ownership sections.
- Knowledge / RAG: repeated in README, RUNTIME_PROTOCOLS, EXTENSION_API,
  EXTENSION_ARCHITECTURE, and Capability docs.
- Core Memory / Worldbook: moved to `docs/contracts/memory-worldbook.md`.
- Settings schema: General settings moved to
  `docs/contracts/settings-general.md`; Agent/Capability config remains in
  `docs/EXTENSION_API.md`.
- LLM Provider / Model Profiles: moved to
  `docs/contracts/runtime-llm-resolution.md`.
- Runtime memory / provider status: moved to `docs/contracts/provider-status.md`.
- ComfyUI workflow / preset behavior: repeated in README, Agent development,
  Capability development, architecture, runtime protocols, and preset schema.

## Suggested Contract Split

- `docs/contracts/intent-routing.md`
- `docs/contracts/knowledge.md`
- `docs/contracts/utility-llm.md`
- `docs/contracts/memory-worldbook.md`
- `docs/contracts/runtime-streaming.md`
- `docs/contracts/runtime-run-lifecycle.md`
- `docs/contracts/runtime-llm-resolution.md`
- `docs/contracts/settings-general.md`
- `docs/contracts/provider-status.md`
- `docs/contracts/attachments-vision.md`

## Round Plan

- Round 1: lighten `docs/AI_CONTEXT.md`, add `docs/ai` task cards, add this audit,
  and define docs maintenance rules.
- Round 2: split Intent Routing, Knowledge, and Utility LLM into topic contracts.
  Replace repeated long sections with summaries and links. Completed in this
  round with `docs/contracts/intent-routing.md`,
  `docs/contracts/knowledge.md`, and `docs/contracts/utility-llm.md`.
- Round 3: split the remaining high-frequency runtime/settings contracts and
  slim `docs/EXTENSION_API.md`, `docs/EXTENSION_ARCHITECTURE.md`, and
  `docs/RUNTIME_PROTOCOLS.md` into summaries and links. Completed with
  `docs/contracts/runtime-streaming.md`,
  `docs/contracts/runtime-run-lifecycle.md`,
  `docs/contracts/runtime-llm-resolution.md`,
  `docs/contracts/provider-status.md`,
  `docs/contracts/attachments-vision.md`,
  `docs/contracts/settings-general.md`, and
  `docs/contracts/memory-worldbook.md`.
- Round 4: add document size checks and maintenance workflow so future changes do
  not refill entry docs or duplicate long contracts. Also review README and
  practical development guides for any remaining long sections that can now link
  to the Round 3 contracts. Completed with `scripts/check_docs_size.py`, focused
  contract fixes, and README/development-guide duplication review.

## Round 1 Notes

- This round is docs-only and preserves existing rule semantics by moving routing
  detail from AI_CONTEXT into task cards and leaving existing contract documents
  intact.
- Contract documents remain intentionally verbose until later rounds create
  canonical `docs/contracts` targets.
