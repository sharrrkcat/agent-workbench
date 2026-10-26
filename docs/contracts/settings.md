# Settings contract

Settings have explicit domain owners and strict Pydantic inputs with extra=forbid; unknown/removed fields return HTTP 422.
The six `/settings?tab=` values are general, models, personas, knowledge, worldbook and tools. Default/unknown tab selects General, including pet.

SettingsPage owns navigation and composition; domain panels own forms, and shared controls are independent of the page.
Types and API clients use domain modules with one HTTP/error implementation. UI labels, states and feedback have matching English/Chinese resources.
User content, prompts, ids, API fields and error codes retain their original values. Both locales display Cogita.
Language uses browser key `cogita.locale`, defaulting to English when absent or invalid.

## Frontend styling foundation

Tailwind CSS 4 uses its Vite plugin; shadcn/ui uses Base UI and the Mira preset
`b1D0dv72` (`base-mira`, Neutral, Lucide, default menus and subtle accents).
`frontend/src/styles.css` is the sole CSS entry for preset tokens, base rules and scoped layout/Markdown/media styles; shared controls own their component styles.
Both preset palettes remain, but the HTML root always uses dark colors and color-scheme. Theme selection and system-theme tracking are unavailable.
Inter Variable is bundled; headings inherit the body font except the Farkle score display, Bust notice and result summary, and Chinese uses system fallbacks. Fonts have no external CDN or backend settings.

Shared controls in `frontend/src/components/ui/` use shadcn CLI 4.21.0; callers compose them directly while domain components retain filtering and resource bindings.
Vite, TypeScript and the test module loader resolve `@/` to `frontend/src/`; `cn` combines component styles.

Field labels/titles use explicit 12px medium text; descriptions, field errors and shared save/error Feedback use 12px regular text. Section legends stay 14px; touch inputs retain 16px text. Desktop controls retain Mira density. Coarse-pointer buttons, options and form
actions have at least 44px targets, except the compact [chat tick rail](chat-context.md#messages-and-attachments); Checkbox/Switch keep compact marks with
expanded targets and associated labels. Field labels/descriptions are connected to controls. Forms retain native required/range validation and existing blank,
null and zero semantics. Hidden file inputs remain behind visible Buttons.
Controlled Select preserves groups, disabled options, empty choices and missing
selected records. Model references use editable Comboboxes for local directories or provider IDs;
their text is the field value, including values outside the suggestions. Detected file paths are read-only.

Detail/editor Tabs use arrow keys for focus and Enter/Space for activation. Model
and resource subpages retain mounted drafts; hidden panels and their overlays
leave the focus order and accessibility tree. Other editors retain parent-owned drafts.
Advanced Collapsible fields stay mounted; invalid submissions expand their
section and focus the field. CUDA mode uses a single-selection ToggleGroup.

Base UI owns modal focus, Escape, backdrops and scroll locking. Dialogs use Mira's
default width; large editors use `max-w-3xl`. Side margins and scrollable bodies
bound them to the viewport; settings editor actions stay in a fixed footer.
Nested Select/Combobox and confirmation popups return
focus to their trigger, and busy editors retain their close restrictions.
Close, Clear, confirmation and Tooltip labels have both locales.

`useConfirmDialog` returns a local `Promise<boolean>` action and an AlertDialog
node rendered by its owner. One request may be pending per owner; overlapping
requests, cancellation, Escape, hidden owners and unmount resolve false. Accepting continues
the existing action. Cache clearing uses this same confirmation workflow.
`SettingsLeaveContext` and `onLeaveGuardChange` accept async guards with the target route.
App commits routes only after acceptance. For guarded browser back/forward,
it restores the current history entry before asking and replays the target once
on acceptance; cancellation preserves the page, drafts and history order.

Home and Settings share one SidebarProvider/SidebarInset shell bounded to dynamic viewport height.
The 16rem desktop sidebar starts expanded and can be hidden, removing controls from focus order.
Visibility is shared across routes without persistence. Below 768px an initially closed Sheet
is at most 18rem wide with viewport margins; Close/backdrop/Escape return focus to its toggle.
Drawers are titled Sessions or Settings. Accepted navigation/creation closes the drawer;
rejected navigation keeps it open.

The sidebar fixes its brand, New session/New Workspace/New Timeline/New QQBot actions, Playground entry and Settings footer.
The scrolling tree contains Projects and ordinary sessions. Sessions has a header creation icon; Project names toggle expansion. Workspace/QQBot rows place creation before settings/delete actions,
without a separate arrow or internal creation row.
Creation icons respond to their header-row hover or keyboard-visible focus; session actions respond only to their own row or open menu.
Mouse focus does not retain hover feedback. Touch actions stay visible with 44px targets.
Project sessions retain left indentation and share the Project's right action column; selections keep their own highlight.
Opening a Workspace draft expands its row. Timeline expands an unavailable-chat notice.
Project settings use `/projects/{id}`; `?session={id}` opens a belonging Workspace/QQBot session. `/new` and `/projects/{id}/new` open drafts, replaced with conversation locations on first send.
Routes survive refresh/history, reject mismatched membership and retain unsaved-navigation guards.
Playground follows New QQBot and stays selected at `/playground`. Its shared shell replaces the conversation with icon/name cards: enabled Farkle (dice), then disabled Whisper (audio waveform).
The grid uses two columns at a content width of 640px, otherwise one. Farkle opens `/playground/farkle`; Whisper transcription UI is unimplemented. Direct startup selects no session or draft.
Entering Playground discards ordinary composer text/attachments and unsaved chat drafts; session epochs prevent late responses from reopening chats. Saved sessions, queued messages and queue edits remain; dispatch stops until returning and reconciling. Submitted runs continue.
Both routes support direct loading and guarded history. Repeated selection adds no history entry; accepted mobile navigation closes the drawer.
Farkle uses SidebarProvider with New Game, My Dice and Shop; the footer is Back to Playground when idle or Exit Game when playing. Exit clears both sides and cancels animations and opponent operations. The camera follows turns automatically; manual view switching is unavailable. The header keeps its title/toggle and the actual Merchant Dice balance; balance and Shop open the same placeholder. My Dice shows all 22 types with material previews, fixed Normal quantity, special quantities out of six and Merchant quantity. My Dice is at most 1200px wide. Choose dice uses maximum widths of 480px for 1-6 owned types, 800px for 7-12 and 1200px for more; selected copy counts do not affect its width. Both keep at least 16px viewport margins. Their scrolling lists use one column below 720px available width, two from 720px and three from 1080px; titles, selected totals and footer controls stay outside the scroller. Both lists sort by the full English display name in either UI language, including Normal and Merchant. Long names wrap. Purchases are unimplemented. My Dice and Choose dice share shadcn Hover Cards triggered only by the die name through mouse hover, focus or touch activation. Each card shows one row of six percentages in face 1–6 order, derived from gameplay weights and rounded to one decimal percent; accessible descriptions identify faces including the Devil head. Previews, quantities and quantity controls do not trigger cards.
New Game selects Beggars (1500, default), Wagoners (2000), Masters (3000) or Courtiers (4000), then Choose dice opens a separate dialog step listing owned types with inventory quantities immediately after their names and right-aligned minus/count/plus controls. Selection cannot exceed inventory or six total; Start game requires exactly six, saves the selection, resets both sides and immediately rolls B's chosen dice. Back retains the draft while returning to difficulty; closing discards unconfirmed changes. A's six dice are sampled under the opponent rules below. Neither selection nor sampling consumes inventory. Types stay fixed through every reroll and handoff. The bottom-left transparent, borderless three-column score display uses local serif text, inner separators, Player/Goal/Opponent headings and Round/Selected rows. Player always means B and Opponent A; totals are banked scores and Selected updates with selection. Bottom-right Hold die (E), Score and continue (F) and Pass (Q) use content-width buttons aligned on their right edges, with separate shadcn Kbd hints beside them; coarse-pointer layouts hide Hold and the hints. The sidebar has no separate Roll action.
Natural single ones score 100 and fives 50. Three equal faces score 1000 for ones or face times 100 otherwise; each additional equal die through six doubles that score. Straights 1-5, 2-6 and 1-6 score 500, 750 and 1500. Only the Devil's head die's head (physical face 1) is wild: it substitutes within three-or-more equal faces or a straight, never a scoring single one/five. Other types have no special scoring rules. Each selection uses the highest-scoring partition covering every selected die without reuse; invalid selections show zero and block F/Q. No three-pair bonus or badge rules apply. Combinations cannot span stored batches or rolls.
Dice retain face values and idle/selected/scored state, with independent hover. The player can operate B only; reducer inputs identify human or AI ownership and reject AI operations from an older roll. Settled B rolls choose one random non-scored hover for fine pointers. WASD chooses the nearest eligible die in the requested screen direction (fixed index breaks ties; no candidate retains the target). Mouse movement transfers B's hover; E, Hold or direct activation toggles selection in place. Hover draws a gold ring and face icon (the shared engraved head for a wild), with the localized type name beside the icon for every non-Normal die; selection overlays a blue lower half-ring for B or deep orange for A. Both rings have thicker bands with black outlines, including the half-ring ends. Touch directly toggles B's selection without hover or its icon; Hold is hidden on coarse-pointer layouts. A's automatic hover and selection remain visible on desktop and touch, while dice, HUD actions and game hotkeys cannot operate A or alter its hover. Scored dice cannot be retrieved. Animations, dialogs, mobile drawers and text entry block game input; E/F/Q ignore key repeat.
F requires a valid nonempty selection: the batch moves together over 280ms, becomes scored, adds its score to Round and clears Selected, then the remaining dice roll. Each batch occupies one right-aligned row, sorted left-to-right by physical face then fixed index; rows remain separate. Scoring all six preserves Round, clears that side's batches and rolls all six. Q accepts a valid selection or no selection (including Round zero): selected dice first complete the same storage animation, then Round plus Selected is banked into Total and both temporary scores clear.
After every settled roll, only that roll's idle dice are checked for any scoring subset. None means Bust: Round becomes zero without changing Total, inputs lock, and the table center shows Bust! / 本轮作废！ for 1.2 seconds in the score-heading font, gold color and shadow, with an independent responsive 32–64px size. Nonwinning Q and Bust automatically hand off over a 500ms camera transition, clear the incoming side's batches and roll all six of its dice. A retains its view and turn notice for an additional 500ms after banking or after the Bust notice ends, with inputs locked, before handing off to B; B has no added pause. Banking updates totals before this pause, and winning never hands off. B is manually operated and A uses the frontend opponent algorithm. Each B turn displays localized Your turn! at the table's top center, fading in for 200ms, holding for 1200ms and fading out for 400ms. The same position continuously shows localized Opponent's turn during A turns. Both reuse score-heading typography without intercepting input. A turn identifier changes only at match start and handoff; rerolls, selection and dialogs do not repeat the notice. Results, exit and departure clear notices/timers; reduced motion omits the fade.
Only Q banking can win, at or above the target; an unbanked Round above the target can still Bust. Winning retains the winner's view, disables dice, game hotkeys and HUD buttons, and opens a result dialog titled You win! / You lost! (localized in both UI languages), centered in score-heading typography and gold/red. Its centered Score line always shows B's banked total in the score-total typography and Round text color, smaller than the win/loss title at every viewport; separate winner and opponent-score rows are absent. Play again opens Choose dice at the same level with the last confirmed selection; New Game opens difficulty preselected to that level. Closing a dialog leaves the finished board frozen. Clicking anywhere on the idle, exited or finished table opens New Game, with a keyboard-activatable full-table entry disabled while another dialog or mobile drawer is open. Dismissal does not click through; New Game and Exit remain available. Restart/exit/departure cancel animations, pending Bust handoffs, opponent timers and worker results. Match state is page-local and resets on refresh/departure. Only inventory, per-level first wins and the confirmed dice selection persist in the browser; badges, saved matches and game APIs are unimplemented.
Opponent difficulty is clamp(target / 10000, 0, 1). Special counts are sampled uniformly from 0–1 for [0,0.2], 1–2 for (0.2,0.4], 2–3 for (0.4,0.6], 3–4 for (0.6,0.8] and 3–5 for (0.8,1]. A never takes Merchant dice, allows at most one Weighted and three of each other special type, and fills the remaining slots with Normal dice. These restrictions apply to A only. Every draw chooses uniformly among the twenty special types that have not reached their per-match cap, initially 1/20 each. Reaching a cap removes that type; remaining copy counts and difficulty do not weight type selection. Alternative opponent loadout methods are unimplemented.
All opponent levels enumerate complete scoring subsets and share exact full-turn expected values, computed in a match-local Web Worker with cached roll outcomes and 50-point dynamic-programming steps; zero-probability faces are omitted from enumeration. Values use the actual remaining dice types, accumulated Round, the remaining target and six-die renewal, with final rewards capped at the remaining target. Banking always takes the highest available score, immediate wins always bank, and continuing cannot omit another independently scoring batch when taking both releases all six dice. Choices that retain different die types remain distinct. Values assume optimal subsequent play; actual lower-level moves continue only when the best continuation exceeds the best banked value by 15% × (1-d). Ties bank; equally valued continuation choices prefer the higher immediate score, then stable die order. Personality traits, random decision errors and whole-match win-probability modeling are absent.
After each settled A roll, calculation overlaps a 1500ms thinking pause; action waits for both. A then hovers each chosen die for 550ms before selecting it, in physical-face/index order, and holds the completed selection for 900ms before using the ordinary store/pass animation and reducer flow. Dialogs, mobile drawers and document invisibility pause the operation clock, preserving the remaining delay; closing/resuming continues the same move. In-flight roll/storage/camera animations and the end-of-turn pause retain their completion behavior. Calculation failures show localized feedback and offer retry of the same position, preserving already selected dice; no random or simplified strategy is substituted.
Normal dice are always six by a frontend rule and are never serialized. `cogita.farkle.inventory` in localStorage holds twenty special counts (each initially zero, maximum six), an initially zero Merchant count with no gameplay cap, and first-win level IDs. No database or backend owns these values. Storage parsing requires every special count and validates counts and level IDs, ignores injected Normal counts and does not overwrite unreadable data; localized errors allow retry. `cogita.farkle.loadout` separately stores all 22 type counts, including selected Normal copies, only when Start game is confirmed. Missing or invalid selections default to six Normal dice without writing; parsing requires exactly six owned copies. Read failures offer retry; save failures retain the draft and block starting until explicit retry succeeds. There is no cross-device sync or coordination of simultaneous games in multiple tabs.
The [typed dice catalog](../../frontend/src/components/playground/farkle/dice.ts) owns all 22 integer face distributions, shared by rolling, probability cards and AI. Favourable never rolls two; Pie never rolls five or six. All sixteen additional types retain ordinary numeric scoring. Random results are supplied to the reducer; deterministic face drawing does not consume gameplay randomness. Only Monk has a fine border with slight green edge patina. Normal uses tan wood and large recessed rings; Even dark yellow metal, Odd and Pie copper, Favourable silver metal, Devil orange amber, and Monk rusted copper use large recessed circles. Devil engraves a head on one. Lucky is pale blue-white, Strip pale blue-purple and Shrinking faded dark blue, all nonmetal with large recessed circles. Unlucky is emerald green and Grimy green, both with large yellow recessed circles; Unbalanced is worn stone with large dark recessed circles. Weighted uses rough earth-brown plaster, Misfortune light brown earth and Aranka a lighter Weighted finish, all with small black dots. Painted is blue with large white painted circles; Lu/Ci/Fer are identical blue with large pale blue-white painted circles. Heavenly is warm white with large black painted circles and a broad-ended Maltese cross styled like ✠ on six. Painted circles have no recessed relief. Merchant is matte graphite ceramic with teal outlined diamond pips.
Beggars/Wagoners victories grant 2 special + 1 Merchant, with 1 extra Merchant on the first win; Masters/Courtiers grant 3 special + 2 Merchant, with 2 extra Merchant on the first win. Every defeat grants 1 special. Rewards settle once when Q banking produces a winner: B means victory and A defeat. Exit, refresh and mid-game restart grant nothing. Special rewards choose uniformly among types still below six, updating candidates after each award. When all twenty types are full, remaining special awards convert together to ceil(remaining / 2) Merchant dice, added to the base and first-win amounts.
First wins are tracked independently by level; defeats do not claim them. A Courtiers victory with only two special copies missing grants those two plus three Merchant dice, or five Merchant dice on the first win. The result lists regular rewards, first-win Merchant dice and converted Merchant dice in that order, with separators only between nonempty groups. Regular Merchant quantity excludes first-win and converted amounts. Bonus rows prefix their +N with localized First win or Converted, with no secondary explanations. Rewards scroll on short screens while the summary and replay controls remain visible. One fixed settlement writes inventory and first wins together. Dialog changes and renders cannot award again. Failed saves retain the same pending reward for explicit retry, update the in-page balance and block another match or Exit until saved; a full page reload loses an unsaved settlement.
One continuous warm-brown wooden table with fine low-contrast grain, subtle relief and soft reflections fills the content below the header without visible edges, zone borders or slot outlines. Deterministic repeating color/bump textures use fixed world scale and anchoring, so table-cover resizing does not stretch or slide the grain. The perspective camera stays at 85 degrees; settled views exclude the A/B divider and opposite dice. Widths of 768px and above frame the throw and right-hand storage, with mirrored row anchors near the center-line edge; rows extend left without changing dice scale or camera distance. Narrower views enlarge and center the throw and put every storage row beyond the right edge. Resizing/sidebar changes reframe the scene, including airborne dice; projected hit targets follow the dice, and offscreen dice leave focus/accessibility navigation. Desktop score width/type use a compact scale; narrow and touch layouts retain their existing score sizes. HUD spacing/type compress on narrow or short screens; touch actions retain 44px targets.
The lazy Three.js scene reuses baked trajectories, standard rounded geometry, face correction and height-based shadows. Heavenly uses a dedicated sphere cut by six planes to form circular faces, with the same unit bounds, face normals and material ordering; its curved connecting surface shares one body material. The six-face texture and circular preview share the broad-ended ✠ cross for six; the hover hint uses the ordinary six-pip icon, and accessible labels and scoring retain numeric six. Lu, Ci and Fer have separate inventory identities but identical blue appearances and ordinary numeric scoring. Geometry and materials are shared and cached by shape/type; rendering occurs only when invalidated/animating, and departure disposes resources including color and bump textures. The original circular collision envelope remains; no rebaking, live physics, audio or production binary trajectory pipeline is included. Renderer failure displays localized feedback and leaves Back available.
QQBot creation and Project settings share Connection (initial), Replies and Images tabs with one save action. Tab selection is local and resets on opening; dialog tabs and actions stay outside its scrolling body. All sections stay expanded; disabled icebreaker/generation options remain conditional. Panels stay mounted while hidden and leave focus/accessibility navigation; submission reveals the first invalid field before native validation feedback. Conversation creation binds a group/friend immediately.
The QQ Project settings header contains only its name and sidebar toggle; conversation creation stays in the sidebar. The QQ editor is at most 48rem wide: container widths of 32rem use two columns, and 40rem use three for timing/image parameters. Prompt/keyword inputs keep four/three rows with internal scrolling. Token clearing is inline; hints cover only input syntax and essential semantics. Creation, inheritance and deletion follow [chat/context](chat-context.md#personas-and-sessions).

The fixed chat header stays on one row, including narrow screens, with the sidebar toggle, title and session settings; Agent Persona selection lives in the session dialog. The composer owns the concrete model menu with Harness and Reasoning on/off controls. Reasoning selects generation mode with session defaults and automatic-adjustment feedback owned by [chat/context](chat-context.md#personas-and-sessions).
The message column is at most 48rem wide, with an independent scroller and aligned fixed composer/status area.
Assistant bodies align with both composer edges; user messages align with its right edge. Avatars sit outside
the body column. Below 61rem of chat width, avatars and names share a row above each body, left-aligned
for assistants and right-aligned for users, without narrowing the body or composer.
The composer uses InputGroup and a horizontally scrolling AttachmentGroup; its textarea grows to 12rem, less in short viewports.
MessageScroller uses pinned @shadcn/react 0.3.1; [runs/streaming](runs-streaming.md#run-lifecycle) owns transcript behavior.

Settings fixes its title in the shared sidebar brand position and a Back to chat footer; the middle navigation
scrolls independently. SidebarGroup reflects responsibility: Application preferences
contains General; Models and execution contains Models, Providers & Runtime and Tools; Daily Chat & Workspace
contains Personas (Cogita Persona, Agent Personas) and Knowledge; Roleplay & Timeline
contains Personas (User Personas, Character Personas) and Worldbook. The two Personas
menus have distinct ids and accessible group context. Each menu uses SidebarMenu;
parents only toggle their nested pages and have no selected state. Menus start collapsed
and closed pages leave keyboard navigation. Active pages use aria-current.
| Menu | Pages / `view` values |
| --- | --- |
| General, Tools | Single page; no `view` |
| Personas | Cogita Persona `user`, Agent Personas `agent`, User Personas `roleplay_user`, Character Personas `character` |
| Models | Dashboard `dashboard`; LLM `llm`, Text Embedding `embedding`, Reranker `reranker`, Image Embedding `image_embedding`, Vision `vision`, Text to Speech `tts`, Speech to Text `asr`, Processor `processor`, Image Generation `image_generation` |
| Providers & Runtime | Model Providers `providers`, Local Runtime `localRuntime` (both remain under `tab=models`) |
| Knowledge, Worldbook | Resources `list`, Global settings `settings` |

Missing/unknown views select user for Personas, dashboard for Models or list for resources. Page changes push browser history;
reselecting the effective current page adds no entry. Back to chat restores the previous ordinary/Project/Playground route.
Refresh restores the domain/subpage; resource selection and detail Tabs are local.
The fixed location header shares Home's primary-row height and toggle position. Content scrolls independently
within 64rem; ordinary forms use 48rem. FieldSet/FieldGroup and separators organize forms, resource rows wrap,
and code, logs and tables contain their own overflow.

Home, Project, settings and Runtime show background-free loading text after 200ms, without skeletons; completion/unmount cancels it, new conversations restart it, and errors/retry appear immediately.
Session navigation immediately updates selection and route/title, keeping the header/composer mounted; only history loads before showing messages or confirmed empty content. Uncached targets use a neutral loading title until details arrive.
Failed loads keep the shell and show local retry; sending, attachments and configuration stay disabled until ready. Repeated target selection preserves input and does not reload or restart feedback. Project refreshes retain listed sessions; empty text waits for completion.

## General

GET/PATCH `/api/settings/general` owns attachment size/count and text-context
limits, title behavior, streaming-delta persistence, show_full_processing and nested
PetSettings. The derived title default is read-only; General submissions contain only
fields shown in that form. Other attachment limits/title prompts remain available through
the API. The form groups conversation display and titles with one explicit save action.
Core Memory fields and group transcript instructions are removed and rejected by PATCH.

show_full_processing is a strict boolean, default false, labeled Show full processing history in General.
It controls initial active-reply expansion and immediately updates Cogita state when saved; recording and final
answers are unchanged. Terminal replies start collapsed. PATCH null/non-booleans return 422.

appearance_font_* and resource_status_* are omitted from reads and rejected by PATCH; font routes/scanning are removed.
`GET /api/runtime/resources` remains a cached diagnostic API, independent of
display preferences. Existing font files remain untouched.

[Data layout](../DATA_LAYOUT.md#database-revisions) owns disposable settings resets and protected data boundaries.

## Model settings

GET/PATCH `/api/models/settings` owns default_model_profile_id, utility_model_profile_id,
external_enabled, external_api_key, max_request_mb and max_normalized_request_mb in appmetadatarecord.model_settings.
HTTP bodies default to 32 MiB (1..100); the strict integer normalized limit defaults to 128 MiB (1..1024). Omitted PATCH fields retain values; null/invalid normalized limits return 422.
Defaults apply to absent settings; explicitly saved HTTP limits remain authoritative. No database schema change or settings conversion is required.
Models → Dashboard → External API shows both limits in MiB; valid edits autosave on blur or Enter, while blank, fractional and out-of-range drafts are not submitted.
The normalized limit also applies to in-app local chat, WD14, SigLIP and reranking while the external service is disabled. Chat image hints display the configured value; help distinguishes runtime limits.
Changes apply to subsequent request preparation without restarting workers. [Models](models.md#external-inference-api) owns byte accounting and the lower native GGUF ceiling.
The default initializes new sessions; changing it preserves existing selections. Header/session
settings select concrete LLMs without a Global default option. [Models](models.md) owns profile
parameters; [chat/context](chat-context.md#auxiliary-tasks-and-titles) owns titles.

Models contains Dashboard followed by kinds with saved profiles, including disabled, unloaded and unavailable profiles. Dashboard and the collapsible Models heading remain when all kinds are empty. Filtering affects navigation only: empty-kind URLs and their Add model shortcuts remain usable, including after deleting the last profile. Dashboard stacks Default models above External API; only enabled LLMs appear in the default chat/auxiliary selectors. Each kind page owns its filtered card list and independent editor draft; its Add model, edit and copy actions keep the kind read-only. There is no list kind selector.
The Models heading places an Add model icon before its collapse arrow, with Project-style header hover/keyboard focus and visible touch targets. Adding does not toggle expansion. It opens a shared editor from any settings page, with all nine kinds selectable at the top; the initial kind is the current model page or LLM elsewhere. Changing kind preserves name, alias and external visibility, resetting source, reference, parameters and inspection to that kind's defaults. Image generation still requires explicit provider selection. Failed saves retain the draft; busy saves block close and departure. Successful creation refreshes the list, expands Models and navigates through the existing leave guard to the new kind. Rejecting departure preserves the created model and current settings draft. The destination shows the list while retaining previous category drafts for subsequent navigation. Mobile creation closes the sidebar; cancelling returns focus to the sidebar toggle. Other cancellation returns focus to the heading action. Accepted navigation closes the shared creation editor.
Providers & Runtime contains Model Providers for external connections and Local Runtime for runtime cards, Storage & cache, collapsed download settings and task history with a log dialog. Both menus share model state and the busy navigation guard. Forms retain drafts across their subpages, with inactive overlays hidden. Removed profiles/service views follow the normal Dashboard default, without redirects. LLM/text embedding/TTS offer Local Runtime and configured providers; image generation requires a provider, while other kinds use Local Runtime only. Disabled providers are marked. New forms default to Local Runtime except image generation, which requires explicit provider selection. Existing unbound profiles show Unconfigured; editing/copying requires selecting a source before saving, without changing the nullable backend contract. Detected Kokoro/WD14 use CPU, DLSS NR uses D3D12, and other engines use CUDA. Unresolved
LLM/TTS/WD14 directories expose no guessed engine options. Local editors expose directory suggestions, execution options and release policy. Vision shows detected WD14/backbone information, read-only Tags,
general/character thresholds (0.35/0.85), CPU with four threads, release policy and external visibility. Thresholds require finite values in [0,1]; zero and fractions round-trip, while blank fields
prevent submission. The removed vision batch-size field is rejected by the API. WD14 directory suggestions require model.onnx and selected_tags.csv; arbitrary safe manual relative references remain
editable. GGUF references select directories; the information panel shows the main model and optional projector without file selectors. LLM editors expose Streaming (default on), and local-only Skip tool capability check / Skip image capability check plus Instant / Reasoning preflight declarations (all default off). The declaration group explains the exclusive skip rules owned by [Models](models.md#resolution-and-request-options). Directory inspection never changes these options; source changes clear all skips. There are no general capability or JSON-format declarations. Missing projectors never disable the skip control. Ambiguity is shown as a blocking load diagnostic while saving remains available. Provider models expose model-ID entry and optional discovery; failed discovery leaves manual entry, saving and
inference available. Opening an active editor or changing sources loads suggestions for its kind/source; reopening refreshes them. Local suggestions include directories already used by profiles. Loading, empty directories/models, no matches and failures have distinct feedback; manual references remain valid. Late results from a previous source cannot replace current suggestions. Changing local/provider source or provider id clears model_ref and replaces source options and
source-specific embedding parameters. Binding an existing unbound draft retains its reference for validation. Reselecting is a no-op. Single-column cards show an unlabeled, accessible enable switch, name/source badge and alias; references and engine/version/installation summaries are omitted. Local cards retain health/load/unload/residency/logs, device/GPU details, tower states and diagnostics; providers show recent-request state and occupancy. Switches PATCH only enabled, stay locked during saving and retain their state on failure. Card details/actions wrap on narrow screens. One toolbar holds status refresh and Add model; there is no inventory list or scan button. Local engine selection follows directory inspection.
New model drafts (including copies) fill each blank name/alias on reference selection or manual-input blur, for every kind and source. Names use the full trimmed reference; aliases lowercase it, replace runs outside [a-z0-9._-] with a hyphen, strip non-alphanumeric prefixes and truncate to 128 characters. Empty results require manual aliases; collisions use normal save validation. Nonempty fields and saved-profile identities are preserved. New LLM drafts require an integer context window before saving (minimum 512; local maximum 1048576). Local drafts start at 4096. Source selection fills only an empty window with 4096 locally or 258000 for providers; nonempty windows, including defaults, carry across sources into the corresponding existing API field. Directory inspection preserves entered windows, including deliberately cleared drafts. Existing editors retain optional-context behavior and the nullable API contract is unchanged. Model dialogs omit Enabled; cards own enablement, new profiles default enabled, and editing retains saved enablement. External API visibility remains in the dialog.
Image generation keeps Local Runtime visible but disabled in Model source. Save requires a provider; discovery and manual model IDs share the normal provider flow. Editors expose image count (default 1) and optional size, quality, style and URL/base64 response format, with Provider default clearing optional values. There are no local execution/lifecycle controls, architecture selection, image history or generation page.
TTS also supports Model Providers. External editors select grok-voice-latest or Customize as a voice architecture independently of the upstream model ID. Grok offers the 33 presets listed in [Models](models.md#provider-tts); Customize requires a manual voice ID. Requests may override the saved default voice. Switching to a provider initializes Grok/alloy; source/provider changes clear model_ref, retain speed/format and reset source-specific parameters. Switching to Customize retains the voice; switching to Grok retains a supported voice or selects alloy, without changing model_ref. Defaults are speed=1/MP3; new models still start locally and TTS cannot be unbound. External editors have no local execution or lifecycle controls. Language is request-only through the shared tts.language contract; there is no saved language setting.
TTS directories automatically identify Kokoro, Chatterbox or Qwen3-TTS Base; architecture is read-only. New drafts contain speed=1/MP3 defaults. Chatterbox/Qwen expose an optional seed: blank saves
null (unfixed), and 0 is a valid fixed seed. Speech requests may override it; omitted/null request seeds inherit the profile. Fixed seeds control randomness without guaranteeing identical audio. Seed
edits use the existing profile save/lifecycle flow. Switching architecture preserves speed/format and clears incompatible generation and execution settings, resetting seed to null for Audio or
removing it for Kokoro. Same-engine directory changes preserve customized settings. Directory changes clear old information and ignore late responses; new draft identity suggestions follow the shared model form rules. Saved Kokoro editors show preset availability by language; Audio editors explain reference-based API usage and Qwen's optional transcripts. Local voices are request selections, not profile records. Ownership/expiry belong to [Models](models.md#audio-tts-and-temporary-references).

Image embedding uses Local Runtime. Choosing/editing a directory reads inspect information without loading; structure, image/text dimensions, native text position limit and processor settings are
read-only, with missing values marked Determined when loading. Tokenizer placeholder lengths are not presented as the position limit. Diagnostics/errors do not block saving. Changing the reference
clears old information immediately and ignores late responses, preserving names and runtime policies; new empty identity fields follow the shared model form rules.
The strict unload_other_tower_on_call switch defaults on. Off permits both towers to reside while requests remain serial. Device, threads, worker batch limit (1..16) and release policy remain
editable; architecture/dimensions/normalization are not parameters. Rows expose separate tower badges and cached vector identity. Load and log menus select Image/Text; Unload releases the whole
profile. Health, busy locks and hidden subpage menus use the shared lifecycle. [Models](models.md#siglip-image-and-text-embeddings) owns execution and acceptance limits.

Text embedding offers Local Runtime/providers. Directory selection inspects metadata without loading; pipeline, pooling, prompt inclusion, normalization, similarity, dimensions and
effective token limit are read-only. Resolved query/document templates are visible; collapsed advanced controls select declared prompt names or automatic resolution. Directory changes clear stale
information and prompt selections; source changes reset incompatible parameters/options. Diagnostics block loading, not saving. Runtime controls retain CPU/CUDA, four threads, batch 1..16 and manual
release defaults. [Models](models.md#local-text-embeddings) owns native semantics and Harrier-only acceptance limits. Rerankers use Local Runtime and automatically inspect
architecture, scoring/activation, pipeline and effective token limit. Directory changes clear old information and ignore late responses; unnamed new drafts receive directory-name suggestions.
Diagnostics block loading, not saving. Parameters are empty: architecture, templates and scoring tokens are not editable. CPU/CUDA, four threads, batch 1..16 (default 1), manual release and external
visibility use existing controls. [Models](models.md#local-reranking) owns native processing and acceptance limits.

ASR uses Local Runtime, with CUDA, four threads, manual release and external visibility off by default. Directory selection inspects architecture, processor, sample rate, features, native window,
languages and timestamp support as read-only information. Changing directories clears stale results and preserves edited names/defaults; unnamed new drafts receive directory-name suggestions. Invalid
directories remain saveable. Language (auto or supported code), prompt, temperature (0..1) and response format are editable defaults for internal/public requests. Explicit auto/empty prompt resets
them; request overrides never change the profile. Both locales explain that json/text omit timestamps and verbose_json returns segment timestamps, while every format transcribes complete recordings.
There is no architecture selector, duplicated preprocessing configuration or transcription page. [Models](models.md#local-speech-recognition) owns execution and limitations.

Processor fixes its source to Local Runtime and shows read-only DLSS NR/image processing, resource diagnostics, style/preset/intensity/tone/structure/skin/auto-mask/channel-order defaults, GPU index,
release policy and external visibility. Incomplete directories remain saveable. There is no processing page. [Models](models.md#dlss-nr-image-processing) owns ranges and execution. Local Runtime has
full-width Core Runtime and DLSS NR cards, one per row at every viewport. Version, platform and architecture appear as three separate badges beside each title, wrapping on narrow screens; status and running jobs stay separate.
Completed jobs remain in history. Install/update, repair-required and cancel are contextual primary actions; other maintenance/log actions use a menu. Cards have no Details disclosure; the DLSS summary names
the manual NR resource requirement. Installing/repairing components requires a healthy base. Component completion refreshes profiles so the generated default appears immediately.

Model Providers uses one full-width card per row: an unlabeled left switch, name/URL, and edit/delete actions that wrap right on narrow screens. Switches have localized accessible names and save only enabled through PATCH; busy actions lock and errors retain the last confirmed state. Refresh/Add share one toolbar without introductory copy or status badges. Provider editors expose the default-off connection.allow_unindexed_complete_tool_call switch with localized scope guidance. Creation defaults to false; PATCH omission retains its value, explicit false disables it, and null/non-boolean values fail. It uses existing connection JSON storage and busy-edit/client-invalidation behavior; no database rewrite or automatic enablement occurs.
Provider editors own only name/connection; creation enables by default and editing omits enabled. Provider/settings reads omit secret keys and expose presence flags. PATCH omission retains keys; empty strings clear them. External enablement requires a nonempty key; storage is unencrypted. Busy connection edits, referenced deletion and invalid combinations fail.

LocalRuntimeSettings has no profile id, enablement switch or editable name. GET/PATCH `/api/models/local-runtime/settings` owns only nested download defaults. Local Runtime is always enabled without
automatic installation/loading. Download edits do not invalidate local models or refresh runtime/profile reads. Settings remain independent of provider CRUD and runtime
job identity. Providers can be added, edited and deleted when unreferenced; local maintenance does not block provider inference. Installation details show the recorded installed version. Reads check
dependency identity, metadata and entries; source changes reuse the environment. Invalid/old metadata or changed dependencies show Repair required. Checks recover on refresh when files/dependencies
are restored; failed/interrupted jobs require explicit repair. Install never rebuilds an unavailable installation; manual Repair also rebuilds healthy ones. Finalizing precedes promotion. The local
settings download object owns http_proxy, pypi_index_url, pytorch_index_url and github_release_proxy_url, patched at `/api/models/local-runtime/settings`. Index/release proxy URLs require HTTPS; HTTP
is allowed for the explicit proxy. Credentials are rejected; these settings serve runtime artifacts/dependencies only. Refresh status reads runtime metadata; only Scan storage fetches page storage
statistics. Entry, navigation, reconnects, disclosure and maintenance completion never scan automatically. Before scanning the card shows an empty state; snapshots survive subpage navigation in memory,
show their scan time and become stale after maintenance. Failed rescans retain the last snapshot with an error. Incomplete scans show unknown sizes, never zero. Cache recovery uses an exclusive logical-size
estimate. Prune is a secondary action; Clear cache lives in the cache menu and confirms consequences even without a scan. Maintenance shares the task lock and retains its internal before/after accounting.
The page adopts active cache jobs and jobs started there; terminal feedback is dismissible and clears on leaving/reload, while history/details retain results and logs. Log reads do not refresh other state.
CUDA profiles use an Automatic/Manual GPU-layer control, preserving a draft's manual value while switching modes.
Defaults and execution belong to Models.

## Other domains

Persona editors share identity/avatar/prompts and collection-specific resources; [chat/context](chat-context.md) owns restrictions.
Cogita Persona opens its singleton editor without create/delete controls. Other collections use lists/dialogs;
the protected Agent Cogita also has no delete control. Editors retain tab drafts, guard navigation and clean temporary avatars.
Session dialogs own Agent/model/context/temperature and Knowledge; the composer menu and [Harness Sheet](harness-tools.md) own Harness and tool selection. Workspace controls show inheritance and per-setting reset,
submit only changed overrides, lock Cogita identity and inherited Knowledge, and disable Project-forbidden tools.
Project editors offer type-specific Configuration and Knowledge/Worldbook tabs; missing required Personas
have management links. Context controls expose message/character limits and attachments, with no History selector.
Creation defaults to unlimited session history, global model inheritance and, for Workspace, the default Agent, fixed Cogita Persona, Harness off and the explicit current tool catalog.
QQBot settings place an optional external image-description model selector beside image input, with an explicit Do not use choice. Image input permits at most five current-batch images, prioritizing pictures and recent occurrences; history uses current description placeholders. Descriptions and original display are independent of main model input; [Chat/context](chat-context.md#qqbot-conversations) owns selection, sharing and alt text. New QQBot forms initialize their editable conversational prompt in the opening UI language. Language changes preserve the draft; clearing and saving retains an empty prompt. Editing existing Projects never reapplies the default. QQBot image generation has a separate provider-only image_generation model selector with Disabled as the default. Selecting a model shows size/quality/style overrides, each supporting model defaults. Disabling generation retains the saved controls. Brief helpers state the current-batch image limit, later history descriptions, one generated image per call and size syntax; reply limits note the shared text/image allowance. Generated images use existing picture previews and delivery controls; no separate generation page is provided.
QQBot settings include a default-off group icebreaker switch beside reply triggers. Enabling it reveals three positive integer fields in seconds: cold silence, observation wait and cooldown. Disabling hides the fields while retaining values. Bilingual helpers explain real-mention nickname matching, the built-in @bot-account trigger and 60-second follow-up eligibility after a confirmed icebreaker reply; [Chat/context](chat-context.md#qqbot-conversations) owns defaults and trigger rules. QQBot context fields replace the shared descriptions with one blank/unlimited and zero/no-history hint; other editors retain their descriptions. Failed saves retain the draft.
Harness global settings own only searxng_base_url through `/api/tools/settings`.

ToolsPanel shows catalog, risk, parameter schema, direct JSON calls, results and
approval controls shared with RunPanel. Catalog and call/results use two columns
on wide screens and stack on narrow screens; search settings form a separate section.
Search configuration is snapshotted for a run; edits never change a pending call's destination. [Harness/tools](harness-tools.md)
owns the runtime workflow and permissions.

Knowledge settings own chunk/retrieval/context controls and unified reranker
selection. KB records select unified embedding profiles. Model paths, connection
timeouts, preprocessing instructions, dimensions, batching and normalization
belong to Models. [Knowledge](knowledge.md) owns index invalidation and retrieval.
Worldbook settings stay at `/api/worldbook/settings`; chat/context owns matching and context rules.

Knowledge and Worldbook default to resource lists, with a separate Global settings
sidebar page and inline details. Refreshing a resource page returns to its list.
Internal detail Tabs preserve drafts; switching list/settings retains global-settings
drafts. Clicking Resources while in a detail returns to the list. Leaving an edited
detail asks before discarding; switching domains or returning to chat also protects
global-settings drafts. Browser unload protects unsaved work. Busy mutations prevent
departure, and stale detail reads cannot replace a new selection.

Worldbook submits only editable settings, omitting id and timestamps. One
case-sensitive control synchronizes its inverse regex field. Advanced context,
matching and recursion controls start collapsed. Knowledge exposes all retained
retrieval, chunk, source-limit and context fields; advanced items start collapsed.
Its optional score threshold precedes default_min_score; both empty means no
score filtering. Chunk overlap must be smaller than chunk size. Model kinds,
paths and source settings remain under Models. Both forms retain advanced drafts
when collapsed and preserve nullable override semantics.

## Pet foundations

The Codex Pet overlay, sprite format, package service, settings page and all
discovery/import/selection/deletion/asset flows are removed. Their routes return
404; no placeholder routes or package scanning remain. Existing data/pet files
are untouched. No Pet is mounted or fetched by the current application.

PetSettings remains nested in AppSettings with only position:
`{mode: default|custom, x: int|null, y: int|null}`. Coordinates are strict integers
between -20000 and 20000. Default position has null coordinates. GET
`/api/pets/settings` returns `{settings: {position}}`; PATCH accepts
`{values: {position?: Partial[PetPosition]}}`. It deep-merges position using the
same AppSettingsStore as General. Removed fields and null position/mode return
422. Settings reset effects belong to the data-layout document above.

usePetPosition receives saved position, width, height and onCommit. It bounds
dragging to the viewport, commits rounded coordinates on pointer release and
returns saving/error state. Pointer cancellation restores the drag origin and
does not save. It has no sprite, package, API client or event-dispatch dependency.
Without both custom coordinates it uses a default bottom-right position.

petTaskState is a pure current-session selector over existing runs and steps.
It returns run_id, raw RunStatus (or IDLE), step_kind and progress fields. Active
runs take precedence over recent terminal runs; timestamps retain microseconds.
Approval steps take precedence while waiting; terminal states expose no active
step. It imports no animation states or bubble text. Future visuals subscribe
to the existing Cogita store; no Pet-specific task endpoint or polling is added.
New appearance, asset format and animations are explicitly deferred.

## HTTP schemas

OpenAPI covers every retained settings owner, derived General fields, Pet
position, storage maintenance and cached health/resource diagnostics. Ordinary
JSON responses have runtime validation. Manual PATCH request documentation
preserves merge-time validation, field omission, explicit null and empty-string
semantics; keys remain write-only with presence flags in read models.
All errors use the application's error envelope, including 422, and invalid
server responses return sanitized 500 INTERNAL_ERROR. Frontend types and clients
are maintained directly rather than generated from OpenAPI.
