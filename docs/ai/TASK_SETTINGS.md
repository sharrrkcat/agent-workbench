# Task: Settings

Read [settings](../contracts/settings.md) and the domain owner:
[models](../contracts/models.md), [chat/context](../contracts/chat-context.md),
[Knowledge](../contracts/knowledge.md) or [harness/tools](../contracts/harness-tools.md).

## Source map

Backend paths under ai_workbench include core/settings.py for AppSettings,
core/models/, core/harness/, core/knowledge_settings.py and core/worldbook.py
for domain settings. API schemas live in api/schemas/; routes own request parsing.
Under frontend/src/, components/SettingsPage.tsx composes components/settings/
panels and domain API/type modules. Persona/session controls are in components/personas/.
Storage and revision effects belong to [data layout](../DATA_LAYOUT.md).

## Verification

Start with tests/test_chat_configuration.py, test_pet_foundation.py,
test_resource_management.py and test_openapi_contracts.py under tests/ plus
the affected model/runtime/tool tests. Frontend scripts cover session settings,
Pet foundations, runtime maintenance, resources and reply presentation.
Check omission/null/empty semantics, secret clearing, reference guards, draft
persistence and approval snapshots. Run all backend tests, frontend tests/build
and documentation gates in the [README](../../README.md#verification).
UI copy follows the [i18n guide](../../frontend/src/i18n/README.md).
