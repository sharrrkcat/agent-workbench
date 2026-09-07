# Frontend i18n

- `en` is the default language. Keep every key present in both `en` and `zh-CN`.
- Add ordinary UI copy to the resource JSON files, then read it with `t("namespace:key")`.
- Do not translate user content, model output, tool/package payloads, slash commands, prompts, templates, schema names, API fields, IDs or error codes.
- Keep wire statuses unchanged and render their display labels through the owning namespace, including runs.stepKinds, runs.toolStatus and llm.states.
- Run `npm run check:i18n` after changing resource files.
