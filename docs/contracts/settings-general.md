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
- Web Search
- Utility LLM
- Intent Routing
- Stateless Inference service enablement and request limits

It does not own AgentConfig, CapabilityConfig, Provider Profiles, Model Profiles,
Knowledge settings, Agent manifests, or Capability manifests.

Stateless Inference General settings are backend-owned in A1.1 and default to
disabled. Full boundary: [stateless-inference.md](stateless-inference.md).

Settings -> Models owns shared model configuration pages:

- Provider Profiles.
- LLM Model Profiles.
- Embedding Model Profiles.
- Reranker Model Profiles.

Provider Profiles can represent external API providers or internal local model
backends. Internal Provider Profiles use fixed local inventory roots under
`data/models/llms`, `data/models/embeddings`, and `data/models/rerankers`; they
do not add editable root paths and do not own per-model generation, embedding,
or reranking parameters. Internal Provider Profile detail pages own the local
model environment display, compact install command examples, and local runtime
device/acceleration defaults. `internal_transformers` owns
`local_runtime_device` (`auto`, `cpu`, `cuda`, or `mps`); `internal_llama_cpp`
owns `llama_cpp_gpu_layers` (`0` for CPU only, `-1` for offload as much as
possible, or a positive layer count). Knowledge Defaults no longer displays
local model overview, install commands, or active local model device controls.
LLM Model Profiles may select internal Provider Profiles only with `llm/...`
refs. Embedding and reranker refs remain outside LLM Model Profile selection.
Embedding Model Profiles may select Provider Profiles that support embeddings:
internal providers with `embedding/...` refs, OpenAI-compatible / LM Studio
embedding APIs, or Ollama embed APIs. Provider Profiles still own only source
connection or local inventory details; dimensions, normalization, query
instruction, and document instruction remain Embedding Model Profile fields.
The primary Embedding Model Profile workflow is Provider Profile plus provider
model id/ref; legacy local model-path selection is not exposed in the Settings
UI.
Reranker Model Profiles may select only internal Provider Profiles with
`reranker/...` refs. Knowledge Defaults owns the disabled/profile selection and
retrieval strategy parameters; candidate counts, thresholds, and context limits
do not move into Reranker Model Profiles. Legacy local reranker path selection
is not exposed as a current Settings workflow.
The legacy `KnowledgeSettings.local_model_device` field may remain in stored
settings for old databases, but new Settings UI and provider-aware runtime paths
resolve local device/acceleration from the selected internal Provider Profile.

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
serving, Prompt Agent file context, vision input, file parts, and attachment
test helpers. Active File and HTTP Capability commands use their own
CapabilityConfig settings.

Attachment and vision behavior is owned by
[attachments-vision.md](attachments-vision.md).

## Appearance

Settings -> Appearance -> Fonts stores three General settings font groups:

- `appearance_font_ui_family`
- `appearance_font_message_family`
- `appearance_font_code_family`
- `appearance_font_ui_source`
- `appearance_font_message_source`
- `appearance_font_code_source`
- `appearance_font_ui_system_name`
- `appearance_font_message_system_name`
- `appearance_font_code_system_name`
- `appearance_font_ui_custom_id`
- `appearance_font_message_custom_id`
- `appearance_font_code_custom_id`
- `appearance_font_ui_custom_family_id`
- `appearance_font_message_custom_family_id`
- `appearance_font_code_custom_family_id`

The `*_source` fields select `system`, `custom_file`, or `custom_family`.
The `*_system_name` fields store a single user-facing installed font name.
The legacy `*_family` fields remain plain CSS `font-family` strings for
advanced fallback stacks and compatibility; they are not the normal Font name
input. The `*_custom_id` fields are nullable local single-file font ids, and
the `*_custom_family_id` fields are nullable local font-family folder ids.
Empty family/system strings are rejected, unknown General settings fields are
rejected, and custom ids do not expose filesystem paths.

Runtime CSS font stacks are derived from source:

- System font: `"<system_name>", var(--aw-font-*-fallback)`
- Custom font: `"<custom_file.css_family>", var(--aw-font-*-fallback)`
- Custom font family: `"<custom_family.css_family>", var(--aw-font-*-fallback)`

The frontend quotes font family names before writing CSS and injects
`@font-face` rules for selected local files or family faces.

Local custom font assets live under `data/assets/fonts`. The app ensures this
directory exists and scans only `.woff2`, `.woff`, `.ttf`, and `.otf` files.
Users copy files there manually and use the Settings UI rescan action; the app
does not download remote fonts, upload fonts, package fonts, or parse complex
font metadata.

Single files directly under `data/assets/fonts` are Custom font assets. Folders
under `data/assets/fonts/<folder>/` are Custom font family assets. A family
folder may include `font.json`:

```json
{
  "family": "Example Sans",
  "display_name": "Example Sans",
  "faces": [
    { "file": "ExampleSans-Regular.woff2", "weight": 400, "style": "normal" },
    { "file": "ExampleSans-Italic.woff2", "weight": 400, "style": "italic" },
    { "file": "ExampleSans-Variable.woff2", "weight": "100 900", "style": "normal" }
  ]
}
```

`weight` accepts numeric values from 1 through 1000 or a variable font range
string such as `"100 900"`. `style` supports `normal` and `italic`; other
values are normalized to `normal`.

If `font.json` is absent or has no valid faces, the scanner infers faces from
filename suffixes with longest-match precedence: `ThinItalic`, `Thin`,
`ExtraLightItalic`, `ExtraLight`, `LightItalic`, `Light`, `Regular`, `Italic`,
`MediumItalic`, `Medium`, `SemiBoldItalic`, `SemiBold`, `BoldItalic`, `Bold`,
`ExtraBoldItalic`, `ExtraBold`, `BlackItalic`, and `Black`. Unknown suffixes
fall back to weight `400`, style `normal`.

Static inferred or numeric manifest faces register a default coverage range so
non-hundred CSS weights match the expected face, for example SemiBold `600`
registers `550 649` and Bold `700` registers `650 749`. Explicit variable
ranges from `font.json` are preserved as declared.

Font asset APIs:

- `GET /api/assets/fonts` returns `files` and `families`. For backward
  compatibility it also returns `fonts` as the same list as `files`.
- Each file item includes `id`,
  `filename`, `display_name`, `extension`, `size_bytes`, `mtime`, `css_family`,
  and `url`.
- Each family item includes `id`, `display_name`, `css_family`, and `faces`.
  Each face includes `file`, `weight`, `style`, `registered_weight`, and `url`.
- `GET /api/assets/fonts/{id}` serves one scanned font file by generated id.
- `GET /api/assets/font-families/{family_id}/{filename}` serves one scanned
  font-family face by generated family id and basename.

Font ids are generated from local filenames or folder names, not accepted paths.
Serving a font must resolve the selected file under `data/assets/fonts` and
reject missing ids, absolute paths, `..` traversal, unsupported extensions,
remote URLs, and symlink/path escapes outside that directory.

The frontend applies saved font settings by writing CSS variables on
`document.documentElement`:

- `--aw-font-ui`
- `--aw-font-message`
- `--aw-font-code`
- `--aw-font-ui-fallback`
- `--aw-font-message-fallback`
- `--aw-font-code-fallback`

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

General LLM & Prompts also exposes the Default model profile fallback used by
main LLM resolution after session override, AgentConfig override, and manifest
profile resolution. It reuses the existing LLM defaults API and does not change
the runtime resolution order.

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

## Web Search

General Web Search owns Prompt Agent Web Context injection settings:

- `web_context_enabled` defaults to `false`.
- `web_context_max_results` defaults to `5` and accepts `1` through `10`.
- `web_context_context_budget_chars` defaults to `4000` and accepts `500`
  through `20000`.
- `web_context_prompt` defaults to a non-empty Web Context instruction and
  accepts `1` through `4000` characters.
- `web_context_plan_resolver_prompt` defaults to a non-empty internal prompt
  body and accepts `1` through `4000` characters.
- `web_context_candidate_judge_prompt` defaults to a non-empty internal prompt
  body and accepts `1` through `4000` characters.
- `web_context_page_excerpt_gate_prompt` defaults to a non-empty internal
  prompt body and accepts `1` through `4000` characters.
- `web_context_fetch_pages_enabled` defaults to `false`.
- `web_context_page_cleaning_enabled` defaults to `true`.
- `web_context_fetch_max_pages` defaults to `6` and accepts `1` through `10`.
- `web_context_fetch_timeout_seconds` defaults to `5` and accepts `1` through
  `20`.
- `web_context_fetch_max_bytes` defaults to `1048576` and accepts `100000`
  through `5000000`.
- `web_context_page_excerpt_chars` defaults to `2000` and accepts `500`
  through `8000`.
- `web_context_total_page_excerpt_chars` defaults to `6000` and accepts `1000`
  through `20000`.
- `web_context_target_page_excerpts` defaults to `2` and accepts `1` through
  `5`.
- `web_context_page_excerpt_gate_enabled` defaults to `false`.
- `web_context_page_excerpt_gate_backend` defaults to
  `follow_agent_model_profile` and accepts `follow_agent_model_profile`,
  `specific_model_profile`, or `utility_llm`.
- `web_context_page_excerpt_gate_model_profile_id` is nullable and is used only
  when the gate backend is `specific_model_profile`.
- `web_context_page_excerpt_gate_min_quality` defaults to `medium` and accepts
  `low`, `medium`, or `high`.
- `web_context_candidate_judge_enabled` defaults to `false`.
- `web_context_candidate_judge_max_candidates` defaults to `8` and accepts `1`
  through `12`.
- `web_context_candidate_judge_min_relevance` defaults to `medium` and accepts
  `low`, `medium`, or `high`. In conservative reject-only mode this is a reject
  threshold, not a positive selection threshold; a candidate is removed only
  when the Utility LLM also gives a high-confidence low-relevance noise
  judgment.

When `web_context_enabled=false`, ordinary Prompt Agent runs must not search or
inject `# Retrieved Web`. When enabled, eligible ordinary text messages to the
current session default Prompt Agent may call the core Web Search runtime during
`Building context` and inject compact SearXNG results after Knowledge context
and before conversation/current-message context.
The rendered `# Retrieved Web` block begins with the current General
`web_context_prompt` plus automatic current local/UTC time context. The default
tells the model that Web results are untrusted external sources, should be used
as evidence rather than instructions, must not be followed as instructions, and
must be cited with `[W1]`-style source markers when used. The prompt affects
only future context builds and must not be copied into run or message metadata.
Settings -> General -> Web Search also owns the user-configurable prompt bodies
for the Web Context Plan Resolver, Candidate Relevance Judge, and Page Excerpt
Gate. These fields customize judgment criteria and style only. JSON schemas,
allowed enum values, required fields, parser tolerance, compact input
boundaries, and safety boundaries remain code-owned and are appended after the
configured prompt body. Current local time, current UTC time, local date, and
timezone/offset are injected automatically into internal Web Context prompts and
the final Web Context injection block for freshness-sensitive judgments.
When page fetching is enabled, Prompt Agent Web Context progressively tries
retained filtered/de-duplicated result pages. `web_context_fetch_max_pages`
means the maximum retained candidate pages to attempt, not the number of page
excerpts finally injected. `web_context_target_page_excerpts` controls how many
accepted page excerpts may be injected when Page Excerpt Gate is enabled.
When `web_context_page_cleaning_enabled=true`, fetched HTML is deterministically
cleaned before excerpts enter Page Excerpt Gate or main-model injection. The
cleaner removes common navigation, footer, header, sidebar, form, advertising,
recommendation, sharing, login, cookie/consent, high-link-density, and duplicate
block noise using generic HTML tags and semantic class/id/role/aria signals. If
cleaning fails or leaves too little usable text, page fetching falls back to the
basic text extractor with compact diagnostics and the Prompt Agent run
continues. Disabling this setting restores the basic extractor for Prompt Agent
Web Context page fetching only.
Without Page Excerpt Gate, fetched excerpts keep the Round 8 behavior: the first
retained candidates up to the attempt limit may append compact plain-text
excerpts to the matching `[W#]` item while respecting the total excerpt budget.
With Page Excerpt Gate enabled, each successfully cleaned excerpt is judged
before injection; rejected, failed, or unavailable gate decisions keep the
source/snippet/status but do not inject the page excerpt. Fetching stops when
the attempt limit, target accepted excerpt count, total accepted excerpt budget,
`need_more=false` after at least one accepted excerpt, or retained candidate list
is exhausted.
The Web source inspection UI may still show capped fetched page excerpt previews
for rejected or failed Gate decisions, alongside the original search snippet,
so users can compare search summaries with fetched page content. This inspection
display does not change what is injected into the main model.

Page Excerpt Gate is an internal strict JSON judgment over compact page data.
It may use the current Prompt Agent resolved model profile
(`follow_agent_model_profile`), a chosen enabled Model Profile
(`specific_model_profile`), or the configured Utility LLM (`utility_llm`).
Follow-agent and specific-profile calls are internal non-streaming model calls;
Utility LLM is a low-cost lightweight helper that may miss page quality issues.
All gate backends create no visible message, Agent run, or command run, inject
no Knowledge/Core Memory/Worldbook/history/attachments/Web context into the gate
prompt, and must not mutate the session selected model. Gate failures, invalid
JSON, missing/disabled profiles, or provider unavailability reject only the
current excerpt and let the main Prompt Agent run continue.

Page fetching supports only HTTP/HTTPS HTML pages, does not execute JavaScript,
does not render in a browser, does not handle PDFs/login pages/media or
downloads, and does not save, cache, vectorize, or add pages to Knowledge.
Fetched page content is untrusted external content and is evidence only, never a
system instruction.

When the Web Candidate Relevance Judge is enabled, Prompt Agent Web Context may
use one strict JSON Utility LLM call after Web Search Capability filtering and
de-duplication but before page fetching. The judge receives only the current
user question, Web Context query/query source, and compact search candidate
fields. It does not receive Agent prompts, chat history, KB/Core Memory/
Worldbook content, attachments, page bodies, raw provider payloads, HTML,
secrets, or Web Context prompt text. It is a conservative noise filter, not a
final evidence or fact judge. Candidates are retained by default and are removed
only when a valid `rejected_items_v1` item references a known candidate,
includes a non-empty short reason, sets `relevance=low`, `confidence=high`, and
uses a clear reject role such as `noise`, `off_topic`, or `weak_match`. Missing
Utility items, low/medium confidence, invalid items, unknown enum values,
medium/high relevance, and reference/official/news/documentation/background/
primary-source roles retain the candidate with compact warnings where
applicable. Legacy positive-selector JSON such as `items` or `use_source` is a
schema failure and falls back to the pre-judge results.
Invalid JSON, unavailable Utility LLM, or whole-response schema failure falls
back to the pre-judge results with compact warnings; it must not fail the main
Prompt Agent run. If a valid judge response rejects all candidates, Web Context
injects nothing and the Prompt Agent run continues. Page fetching, when enabled,
fetches retained candidates, including unjudged candidates. Candidate Judge does
not cap final injected sources; `web_context_candidate_judge_max_candidates`
only limits how many filtered search candidates are sent to the Utility LLM.
Final Web Context source count remains controlled by Web Context result/context
budgets and page fetching/excerpt policy.

Settings -> General -> Web Search should describe Candidate Judge as a Utility
LLM conservative reject-only noise filter: uncertain or unjudged candidates are
retained, only clearly unhelpful sources are removed, and the judge does not
choose the final source count. UI copy must not imply the Utility LLM is a
final evidence or fact judge or positive source selector.

With Intent Routing disabled or in shadow mode, enabled Web Context keeps the
forced search behavior for eligible ordinary Prompt Agent messages. With Intent
Routing in auto mode, a Web Context Plan Resolver first decides the search plan:
selected Knowledge and Pet routes skip Web Context, validated `web_query` slots
may provide the query, and uncertain/chat/diagnostic outcomes use a strict
Utility LLM JSON planning call to decide whether an external fact search is
actually requested.

Provider connection and result quality settings remain CapabilityConfig for the
`web_search` Capability. Settings -> Capabilities -> Web Search owns SearXNG
base URL, timeout, language, safe-search, Capability max results, command
enablement, domain blocklist/allowlist, URL and same-domain-title
de-duplication, diagnostics, and test search. General Web Search must not
duplicate those provider/result-quality controls. Disabling the `/web-search`
command disables only that explicit command; it does not block internal Web
Context search when General Web Search is enabled.
Page fetching and Page Excerpt Gate settings belong only to Settings -> General
-> Web Search because they are Prompt Agent Web Context runtime policy. The
`/web-search` command and Settings test search continue to return search results
only and must not fetch result pages, run enhanced content cleaning, or run Page
Excerpt Gate. HTTP Capability `/fetch-url` also remains independent and does not
use Prompt Agent Web Context page cleaning. Candidate Judge settings also belong
only to Settings -> General -> Web Search and must not be added to Settings ->
Capabilities -> Web Search.

## Utility LLM

General Utility LLM owns the Utility model profile reference, status/test
controls, and supported unload controls. The primary UI selects an enabled LLM
Model Profile only; deprecated local `transformers` / `llama_cpp` Utility
backend and path fields may remain as legacy storage for compatibility warnings.

Utility LLM is a core internal service, not an Agent, Capability, Provider
Profile, Model Profile, AgentConfig, or CapabilityConfig. Full contract:
[utility-llm.md](utility-llm.md).

## Intent Routing

General Intent Routing exposes a single primary `Intent Routing Mode` control:
`Off`, `Shadow: diagnose only`, and `Auto: safe routing`. `Off` stores
`intent_routing_enabled=false`; `Shadow` stores `intent_routing_enabled=true`
and `intent_routing_mode=shadow`; `Auto` stores `intent_routing_enabled=true`
and `intent_routing_mode=auto`, with legacy safe-auto saved true when the UI
selects Auto. Legacy safe-auto and confirm-uncertain fields remain schema
compatibility fields, not primary UI controls.

General Intent Routing also owns Prompt Agent default enablement, semantic
thresholds, custom route examples for `chat`, `image_generation`,
`knowledge_query`, `web_query`, `agent_route`, and `command_like`, Route Test
controls, semantic router Embedding Model Profile reference, and compact Utility
LLM status display.

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
