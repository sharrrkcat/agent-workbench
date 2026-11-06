# Task: Characters, Personas and Worldbook

Read [chat/context](../contracts/chat-context.md) and [settings](../contracts/settings.md).

## Source map

- core/schema/character.py, core/characters.py and core/character_service.py own AI identities.
- core/schema/persona.py and core/personas.py own independent user identities.
- core/schema/chat_config.py, core/session.py and core/chat_service.py own two-level defaults/overrides.
- core/user_persona_context.py and core/context.py project identities into model requests.
- api/routes/characters.py, personas.py and sessions.py own strict HTTP boundaries.
- core/worldbook.py and api/routes/worldbook.py own independent matching and resources.
- db/models.py, db/stores.py and Alembic own persistence and destructive test-state revisions.
- Frontend components/characters/, settings/PersonasPanel.tsx and components/personas/ own editors,
  navigation, uploads and Session settings; useCharactersStore/usePersonasStore own live identity reads.

## Verification

Start with tests/test_characters.py and test_characters_migration.py. Cover protected defaults,
required immutable ownership, model selection once, sparse overrides/reset, resource non-injection,
original Persona retry/edit, deletion protection, avatar lifetime and fixed running snapshots in both stores.
Historical schema tests use pinned revisions and raw rows, independently of current ORM identities.
Keep Worldbook matching and Knowledge indexing/search coverage in their own suites.
Browser tests cover both languages and desktop/touch, including creation, identity display,
unsaved edits, per-Character selection, scoped deletion and delayed responses. Use temporary roots;
run the [repository gates](../../README.md#verification) and update both locales.
