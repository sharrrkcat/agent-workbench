# General Settings Contract

This contract owns General settings schema boundaries, General settings APIs,
file/context limits, and settings documentation ownership.

## API

General settings are read and updated through:

- `GET /api/settings/general`
- `PATCH /api/settings/general`

Unknown fields are rejected. Settings APIs must not accept undeclared schema keys
as silent no-ops.

Secrets are masked in API/UI responses where fields are marked secret. In this
alpha, stored local SQLite JSON may still contain plaintext secrets, so secrets
must not be copied into manifests, run metadata, logs, markdown replies, or
generated files.

## Categories

Settings -> General owns local app settings for:

- Files
- Appearance
- LLM & Prompts
- Memory
- Utility LLM
- Intent Routing

It does not own AgentConfig, CapabilityConfig, Provider Profiles, Model Profiles,
Knowledge settings, Agent manifests, or Capability manifests.

## Files

General file settings control chat attachment uploads and Prompt Agent file
context, including:

- maximum image upload size.
- maximum file upload size.
- maximum attachments per message.
- whether uploaded text files enter LLM context.
- per-file LLM file context limit.
- per-message LLM file context limit.

These settings apply to composer upload, drag-and-drop, paste, attachment
serving, Prompt Agent file context, vision input, `file_content`, and attachment
test helpers. Active File and HTTP Capability commands use their own
CapabilityConfig settings.

Attachment and vision behavior is owned by
[attachments-vision.md](attachments-vision.md).

## Appearance

Settings -> Appearance -> Fonts stores three General settings font groups:

- `appearance_font_ui_family`
- `appearance_font_message_family`
- `appearance_font_code_family`
- `appearance_font_ui_custom_id`
- `appearance_font_message_custom_id`
- `appearance_font_code_custom_id`

The `*_family` fields are plain CSS `font-family` strings for user-entered
system font names or font stacks. The `*_custom_id` fields are nullable local
font asset ids. Empty family strings are rejected, unknown General settings
fields are rejected, and custom ids do not expose filesystem paths.

Local custom font assets live under `data/assets/fonts`. The app ensures this
directory exists and scans only `.woff2`, `.woff`, `.ttf`, and `.otf` files.
Users copy files there manually and use the Settings UI rescan action; the app
does not download remote fonts, upload fonts, package fonts, or parse complex
font metadata.

Font asset APIs:

- `GET /api/assets/fonts` returns scanned local font assets with `id`,
  `filename`, `display_name`, `extension`, `size_bytes`, `mtime`, `css_family`,
  and `url`.
- `GET /api/assets/fonts/{id}` serves one scanned font file by generated id.

Font ids are generated from local filenames, not accepted paths. Serving a font
must resolve the selected file under `data/assets/fonts` and reject missing ids,
absolute paths, `..` traversal, unsupported extensions, and symlink/path escapes
outside that directory.

The frontend applies saved font settings by writing CSS variables on
`document.documentElement`:

- `--aw-font-ui`
- `--aw-font-message`
- `--aw-font-code`

The root UI uses `--aw-font-ui`, message bodies explicitly use
`--aw-font-message`, and code/json/file-content/manifest/Knowledge monospace
surfaces use `--aw-font-code`. When a custom font is selected, the frontend
injects `@font-face` rules using the backend-provided `css_family` and safe
asset URL.

## LLM And Prompts

General LLM & Prompts owns automatic session title settings:

- title enablement.
- title backend selection.
- optional specific title Model Profile.
- title prompt.
- title input limit.
- best-effort title model release.

Full title and Utility LLM behavior is owned by
[utility-llm.md](utility-llm.md#session-title-interaction).

Context Rendering overrides for group transcript and command-result context
instructions affect only future context builds. They do not rewrite historical
messages and do not dynamically update a run whose context is already built.

## Memory

General Memory owns Core Memory fields, including whether Core Memory is enabled
for eligible Prompt Agent calls and the text used for Core Memory injection.
Worldbook defaults, Worldbooks, entries, bindings, match-test, and runtime
matching/injection behavior are owned by
[memory-worldbook.md](memory-worldbook.md). General settings may link that
contract but do not own Worldbook storage or APIs.

## Utility LLM

General Utility LLM owns backend, local model path or Model Profile reference,
device, runtime options, llama.cpp options, scan/status/test controls, and unload
controls.

Utility LLM is a core internal service, not an Agent, Capability, Provider
Profile, Model Profile, AgentConfig, or CapabilityConfig. Full contract:
[utility-llm.md](utility-llm.md).

## Intent Routing

General Intent Routing owns master enablement, global mode, safe-auto toggle,
semantic thresholds, custom examples, Route Test controls, semantic router
Embedding Model Profile reference, and compact Utility LLM status display.

Prompt Agent overrides and target hints live in AgentConfig runtime fields. Full
contract: [intent-routing.md](intent-routing.md).

## Documentation And I18n

Settings changes must update the owning contract:

- General settings fields: this file.
- AgentConfig/CapabilityConfig schema: [../EXTENSION_API.md](../EXTENSION_API.md).
- Provider/Model Profiles and runtime LLM behavior:
  [runtime-llm-resolution.md](runtime-llm-resolution.md).
- Knowledge settings: [knowledge.md](knowledge.md).
- Core Memory/Worldbook settings: [memory-worldbook.md](memory-worldbook.md).

User-visible frontend text changes must update every supported locale under
`frontend/src/i18n/resources`.
