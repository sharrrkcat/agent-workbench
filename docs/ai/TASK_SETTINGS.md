# Task: Settings

Read [settings](../contracts/settings.md) and the domain owner:
[models](../contracts/models.md), [chat/context](../contracts/chat-context.md),
[Knowledge](../contracts/knowledge.md) or [harness/tools](../contracts/harness-tools.md).

core/settings.py owns strict AppSettings and nested Pet settings. Models,
Knowledge, Worldbook and Harness have explicit separate schemas/stores and APIs.
Unknown fields are 422; removed display fields have no compatibility path.
0009 resets only the disposable app_settings object, not model files or other
settings objects. Pet settings now contain only position. Future persistence changes require Alembic.

The frontend retains General, Models, Personas, Knowledge, Worldbook and Tools.
Domain panels under components/settings own their forms and use independent
shared fields. SettingsPage only coordinates navigation and shared feedback.
Models has five kinds and four tabs; runtime settings download dependencies,
never weights. Keep secret omission/clearing and reference guards intact.

Title selection is auxiliary-only. Sessions own all execution configuration;
Personas own prompts and bindings. Empty additions preserve Persona resources;
an empty tool list disables every tool. Pending approvals retain the
original chat and search-service snapshots. Pet position PATCH is
deep-merged through AppSettingsStore.

General show_full_processing is a strict boolean defaulting false. Saving
updates the shared Workbench settings immediately; it controls reply-history
expansion only. Recording and final-answer content do not depend on the switch.

Run affected schema/API/store tests, all backend tests and frontend tests/build.
Update both locales, the owning contract and documentation checks.
