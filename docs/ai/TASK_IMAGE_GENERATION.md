# Task: Image Generation

## Read first

Read only the entries needed for the specific change.

- `../contracts/image-generation.md` for internal image generation profiles,
  model inventory, runtime behavior, Capability ownership, Agent workflow, and
  attachment output rules, and Settings workflow.
- `../contracts/settings-general.md` when image generation profile management is
  added to Settings -> Models.
- `../contracts/runtime-run-lifecycle.md` when adding generation Runs,
  progress, queue/cancel behavior, or run metadata.
- `../contracts/attachments-vision.md` when generated images become local
  attachments or media groups.
- `../contracts/message-parts.md` when changing generated image response parts
  or form output.
- `../contracts/provider-status.md` when exposing runtime status, unload, or
  memory release behavior.
- `../contracts/stateless-inference.md` only when explicitly adding external
  `/v1` or `/api/inference` image generation routes.
- `../EXTENSION_API.md#script-context-api` when adding Script Agent ctx helpers.
- `../EXTENSION_API.md#output-payloads` when output payload shapes change.

## Likely source

- `ai_workbench/core/image_generation/`
- `ai_workbench/api/routes/image_generation.py`
- `ai_workbench/core/stores.py`
- `ai_workbench/db/models.py`
- `ai_workbench/db/stores.py`
- `ai_workbench/db/database.py`
- `ai_workbench/api/deps.py`
- `capabilities/image_generation/`
- `agents/image_generator/`
- `frontend/src/components/settings/ImageGenerationSettingsPanel.tsx`
- `frontend/src/components/settings/SettingsConsole.tsx`
- `frontend/src/components/settings/SettingsObjectList.tsx`
- `frontend/src/components/settings/SettingsDetailPanel.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/types.ts`
- `frontend/src/i18n/resources`

## Tests

- `uv run pytest tests/test_image_generation_profiles.py`
- `uv run pytest tests/test_image_generation_capability.py`
- `uv run pytest tests/test_image_generator_agent.py`
- `uv run pytest tests/test_prompt_agent_execution.py tests/test_script_agent.py`
  when adding Capability, Agent, or run cancellation behavior.
- `uv run pytest tests/test_file_http_attachments.py` when saving generated
  images as attachments.
- `uv run pytest tests/test_runtime_memory.py tests/test_provider_status.py`
  when adding runtime unload/status.
- `uv run pytest tests/test_frontend_chat_contracts.py tests/test_settings_data.py`
  when adding Settings UI for image generation profiles.
- `cd frontend && npm run build` when frontend changes.
- `cd frontend && node scripts/check-i18n.mjs` for user-visible frontend text.

## Avoid

- Do not expose ComfyUI node graphs or workflow editing through this domain.
- Do not call or require a running ComfyUI service for project-native image
  generation.
- Do not add slash commands for user-facing image generation forms.
- Do not add external `/v1` image generation routes unless the stateless
  inference contract is updated in the same change.
- Do not store absolute model paths, raw prompts, generated image bytes, or LoRA
  paths in public API fields.
- Do not delete model files when deleting profiles.
- Do not add heavy ML dependencies to the default install.

## Docs and i18n

- Profile schema, model refs, runtime metadata, task types, Capability methods,
  Agent workflow, Settings workflow, or generated output changes update
  `../contracts/image-generation.md`.
- User-visible frontend text changes require every supported locale.
- Agent or Capability manifest changes must regenerate generated registry docs.
