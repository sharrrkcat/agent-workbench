# Task: Memory and Worldbook

Read [chat/context](../contracts/chat-context.md) and
[settings](../contracts/settings.md).

Likely sources are core/memory_context.py, worldbook.py, worldbook_context.py,
context.py, chat_service.py, settings.py, API worldbook routes and SQLite stores.
Keep matching deterministic and bounded. Resolve Persona defaults/session
overrides before invoking context services; empty override means no resources.
Match-test is read-only. Metadata stores compact diagnostics, not source bodies.

General owns Core Memory. Phase 5 resets that disposable setting along with
the rest of app_settings; Worldbook records/settings are unaffected.
Use temporary roots and test matching, disabled/empty injection, context limits,
binding resolution and memory/SQL behavior. Update both locales for UI copy.
