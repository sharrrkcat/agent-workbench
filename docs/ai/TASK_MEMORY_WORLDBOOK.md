# Task: Memory and Worldbook

Read [chat/context](../contracts/chat-context.md) and
[settings](../contracts/settings.md).

## Source map

Core modules under ai_workbench/core/ include memory_context.py, worldbook.py,
worldbook_context.py, context.py, chat_service.py and settings.py. HTTP routes
and persistence are in ai_workbench/api/routes/worldbook.py and ai_workbench/db/stores.py.
The frontend uses GeneralPanel.tsx, WorldbookPanel.tsx and worldbook/ components
under frontend/src/components/settings/.

## Verification

Start with tests/test_core_memory_context.py, test_worldbook_context.py,
test_chat_configuration.py and test_resource_management.py under tests/.
Check deterministic matching, disabled/empty injection, context bounds, compact
diagnostics, binding resolution and validation before writes in both stores.
Resource frontend/browser tests cover independent drafts, enabled-save rollback,
reordering and matching diagnostics. Use temporary roots and run the
[repository gates](../../README.md#verification); UI changes update both locales.
