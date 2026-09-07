# Task: Settings

Read [settings](../contracts/settings.md) and the domain owner:
[models](../contracts/models.md), [chat/context](../contracts/chat-context.md),
[Knowledge](../contracts/knowledge.md) or [harness/tools](../contracts/harness-tools.md).

core/settings.py owns strict AppSettings and nested Pet settings. Models,
Knowledge, Worldbook and Harness have explicit separate schemas/stores and APIs.
Unknown fields are 422; removed display fields have no compatibility path.
0007 resets only the disposable app_settings object, not model files or other
settings objects. Future persistence changes require Alembic.

The frontend retains General, Models, Personas, Knowledge, Worldbook, Tools and
Pet. Domain panels under components/settings own their forms and use independent
shared fields. SettingsPage only coordinates navigation and shared feedback.
Models has five kinds and four tabs; runtime settings download dependencies,
never weights. Keep secret omission/clearing and reference guards intact.

Title selection is auxiliary-only. Persona/session null overrides inherit and
explicit empty binding/tool lists mean empty. Pending approvals retain the
original Persona and search-service snapshots. Pet position/bubble PATCH is
deep-merged through AppSettingsStore.

Run affected schema/API/store tests, all backend tests and frontend tests/build.
Update both locales, the owning contract and documentation checks.
