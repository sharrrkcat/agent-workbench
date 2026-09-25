# Task: Personas and Worldbook

Read [chat/context](../contracts/chat-context.md) and
[settings](../contracts/settings.md).

## Source map

Core modules under ai_workbench/core/ include schema/persona.py, personas.py,
user_persona_context.py, worldbook.py, context.py and chat_service.py.
HTTP routes live in ai_workbench/api/routes/personas.py and worldbook.py;
persistence lives in ai_workbench/db/stores.py and core/personas.py.
The frontend uses PersonasPanel.tsx, WorldbookPanel.tsx and worldbook/ components
under frontend/src/components/settings/, plus components/personas/ session controls.

## Verification

Start with tests/test_persona_collections.py, test_user_persona_context.py,
test_worldbook_matching.py, test_phase3_personas.py, test_chat_configuration.py
and test_resource_management.py. Check collection isolation, protected identities,
resource permissions, snapshot stability, current user identity, ordered Knowledge
resolution and deterministic explicit Worldbook matching in both stores.
Frontend/browser tests cover shared editors, live identity/avatars, independent
resource drafts, enabled-save rollback, ordering and matching diagnostics.
Use temporary roots and run the [repository gates](../../README.md#verification);
UI changes update both locales.
