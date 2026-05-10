# Frontend i18n

- `en` is the default language. Keep every key present in both `en` and `zh-CN`.
- Add ordinary UI copy to the resource JSON files, then read it with `t("namespace:key")`.
- Do not translate user content, model output, raw renderer payloads, manifest data, slash commands, prompts, templates, schema names, API fields, IDs, status enums, or error codes.
- For statuses and errors, keep raw values unchanged and map display labels through `frontend/src/i18n/formatters.ts`.
- Run `npm run check:i18n` after changing resource files.
