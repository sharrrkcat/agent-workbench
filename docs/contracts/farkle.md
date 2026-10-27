# Farkle contract

Farkle is a browser-local game with a human player (B) and an automatic opponent (A), embedded at `/playground/farkle` or built as a standalone static site.
[Settings](settings.md#frontend-styling-foundation) owns the shared shell, controls, Playground navigation and conversation-departure rules. The
[Farkle task card](../ai/TASK_FARKLE.md) locates source, artifacts and tests; [README](../../README.md#verification) owns verification commands.

## Standalone hosting

The standalone entry includes only Farkle, shared controls, styles and English/Chinese resources; it initializes no application stores, APIs or WebSockets.
Its title/brand is Farkle. The root table has no idle Back button or footer; Exit Game, Back to table and dialog Back controls retain their game behavior.
History uses `/?view=history&page=N`, supporting static-host refresh and browser history while keeping the mounted match during in-page navigation.
The build-selected host supplies branding, routes and storage prefix: standalone uses `farkle.*` and `farkle.locale`; the embedded game retains the keys below. No storage migration occurs.
Valid saved language wins; otherwise browser languages are matched in order (single browser language if the list is unavailable/empty): all Chinese variants use Simplified Chinese, English variants use English, and no match uses English. The initial choice is saved; manual changes persist.
Fonts, trajectories, calibration, the AI Worker and a 64px normal five-pip PNG favicon ship locally with relative URLs; WebGL and HTTP(S) hosting are required. Builds stage and update only manifest-owned files; README, Git metadata and other files are maintained separately.

## Navigation and match setup

SidebarProvider contains New Game, Custom game, Match history, Inventory, Shop and Settings; its footer offers Back to Playground when idle and Exit Game while playing on the table.
In history, the footer offers Back to table, preserving the match even during save errors and closing the mobile drawer. On short screens navigation scrolls above the footer.
Exit clears both sides and cancels animations/opponent work. The camera follows turns without manual switching. The header has its title/toggle and actual Merchant balance, which opens Shop.

Idle/exited/finished tables open New Game by pointer or keyboard. Dialogs/mobile drawers disable this entry; dismissal cannot click through.
New Game defaults to Beggars. First-win Merchant dice supplement victory rewards; [settlement](#rewards-and-browser-storage) owns defeat/conversion/persistence.

| Level | Target | Special dice per victory | Merchant dice per victory | First-win Merchant dice |
| --- | ---: | ---: | ---: | ---: |
| Beggars | 1500 | 2 | 1 | 1 |
| Wagoners | 2000 | 2 | 1 | 1 |
| Masters | 3000 | 3 | 2 | 2 |
| Courtiers | 4000 | 3 | 2 | 2 |
| Burgomasters | 5000 | 3 | 3 | 3 |
| Stewards | 6000 | 3 | 3 | 3 |
| Governors | 7000 | 4 | 3 | 3 |
| Chancellors | 8000 | 4 | 3 | 3 |
| Burgraves | 9000 | 4 | 4 | 4 |
| Electors | 10000 | 4 | 4 | 4 |

The single-select level list scrolls above fixed controls. Choose dice shows owned types, muted `owned N` / `拥有N` below names and minus/count/plus
on the right. Normal fills selections to six. Selected rows have six green intensity steps; zero-count rows and Inventory have no highlight.
Adding a non-Normal replaces one Normal, subject to ownership and a spare Normal; removing one restores a Normal. Normal cannot be removed directly;
adding one replaces the first selected non-Normal in full English-name order, including Merchant.
Chooser reset icons restore only that side's draft to six Normal. Player choosers place Random between Back and Start; small screens put Start above
equal-width Back/Random. Random samples six stock copies uniformly without replacement: owned counts with Merchant capped at six for ordinary games,
or six of all 22 types for custom games. The opponent chooser has no Random button.
Start game saves the selection, resets both sides and rolls B's dice immediately; A uses the [opponent loadout rules](#opponent). Back retains the draft;
closing discards unconfirmed changes. Selection and sampling consume no inventory. Types stay fixed through rerolls and handoffs.

### Custom games

Custom game has a target input and sliding Normal / Random / Wild / Custom choice independent of Settings. Decimal integer targets must be strictly
between 1 and 9007199254740991, including nonmultiples of 50; syntax/lower/upper errors block progression with distinct localized feedback.
Generated modes open the player chooser; Custom opens the opponent chooser first. Both reuse ordinary controls/previews/cards, with six of all 22
types per side and no inventory quantities/limits. Back retains drafts; closing discards edits.
Custom matches retain their confirmed setup and grant no rewards or first wins, even at ordinary targets. Play again reopens the corresponding
opponent/player chooser with both loadouts; result New Game opens ordinary level selection.

## Scoring, input and turns

Natural single ones score 100 and fives 50. Three equal faces score 1000 for ones or face × 100 otherwise; each extra die through six doubles the
score. Straights 1-5, 2-6 and 1-6 score 500, 750 and 1500. Only Devil's head (physical face 1) is wild, substituting within equal-face groups of three or more
and straights, never scoring singles. Other types use ordinary numeric scoring. Selection uses the highest-scoring partition covering every selected
die once; invalid selections show zero and block F/Q. No three-pair bonus or badge rules apply; combinations cannot span stored batches or rolls.

### Input and HUD

The score display, Bust and turn notices, and result summary use local serif typography instead of the shared body font. The bottom-left score display
is transparent and borderless, with three columns, inner separators, Player/Goal/Opponent headings and Round/Selected rows. Player means B and
Opponent A; totals are banked and Selected updates with selection. Bottom-right Hold die (E), Score and continue (F) and Pass (Q) use content-width
buttons aligned on their right edges, with separate shadcn Kbd hints. Coarse pointers hide Hold and keyboard hints. The sidebar has no separate Roll action.

Dice retain face values and idle/selected/scored state with independent hover. Human input operates B only; reducer inputs identify human/AI ownership
and reject AI operations from older rolls. Settled B rolls randomly hover one non-scored die for fine pointers. WASD picks the nearest eligible die
within 45 degrees of the requested screen direction, including the boundary, using projected centers. Fixed index breaks distance ties; an empty
cone retains hover without wrapping or widening the search. Mouse movement transfers B's hover; E, Hold or direct activation toggles selection in place.
Hover draws a gold ring and face icon (the engraved head for wilds), plus localized names for non-Normal types. Selection adds a blue lower half-ring
for B or deep orange for A. Both use thick bands with black outlines, including half-ring ends. Touch selects without hover, showing only the last selected die's face icon and localized name, including Normal, below its half-ring.
Deselecting any die clears the hint without falling back; other selection rings remain. Roll/score/turn/reset/exit and mouse or game-keyboard input clear it. Dialogs/drawers hide it and restore only its still-selected, same-roll target; resize reprojects it.
A's automatic hover/selection stays visible on desktop and touch, but human dice, HUD and hotkeys cannot operate A or alter its hover. Scored dice cannot be retrieved. Animations, dialogs, mobile drawers and text entry block game input; E/F/Q ignore key repeat.

### Banking and handoff

F requires a valid nonempty selection: the batch moves together over 280ms, becomes scored, adds its score to Round and clears Selected, then the
remaining dice roll. Each batch occupies one right-aligned row, sorted left-to-right by physical face then fixed index; rows remain separate. Scoring
all six preserves Round, clears that side's batches and rolls all six. Q accepts a valid selection or no selection (including Round zero): selected
dice first complete the same storage animation, then Round plus Selected is banked into Total and both temporary scores clear.
After each settled roll, only its idle dice are checked for scoring subsets. None means Bust: Round becomes zero, Total stays unchanged and input
locks. The table center shows localized Bust! for 1.2 seconds with score-heading typography, gold color, shadow and independent responsive 32–64px
size. Nonwinning Q and Bust hand off over a 500ms camera transition, clear incoming batches and roll all six incoming dice. A retains its view/turn
notice with locked input for another 500ms after banking or the Bust notice, before returning to B; B has no added pause. Banking updates totals
before this pause; winning never hands off.
Each B turn displays localized Your turn! at the table's top center, fading in for 200ms, holding for 1200ms and fading out for 400ms. The same
position continuously shows localized Opponent's turn during A turns. Both reuse score-heading typography without intercepting input. A turn
identifier changes only at match start and handoff; rerolls, selection and dialogs do not repeat the notice. Results, exit and departure clear
notices/timers; reduced motion omits the fade.

### Results and lifecycle

Only Q banking at or above the target wins; an unbanked winning Round can still Bust. Winning keeps the winner's view, disables dice/hotkeys/HUD
actions and opens localized Victory! / Defeat! in centered gold/red score-heading typography. The centered Score line shows only B's banked total,
using score-total typography and Round color, always smaller than the title; no separate winner or opponent-score rows appear. Ordinary Play again
opens Choose dice at the same level with the last confirmed selection; New Game opens that level in difficulty selection. Closing leaves the finished
board frozen.

Restart/exit/departure cancel animations, pending Bust handoffs, opponent timers and worker results. Matches reset on refresh/departure; inventory,
first wins, ordinary selection, custom configuration, opponent settings and completed match history persist locally.

### Match history

`/playground/farkle?view=history&page=N` retains the table with Back to table, pauses input/AI and lets animations finish; wins save and show results on return.
Browser back/forward and refresh preserve the page; sidebar entry selects page one. The list scrolls between fixed heading/pagination, 20 records per page, newest first.

At ≥800px content width, time/duration sits beside player dice/outcome/scores/opponent dice, centered together in the remaining width, with both side labels visible.
At 480–799px, the centered dice/score group sits below time/outcome/duration; below 480px, scores sit above both dice groups. Compact outcomes center on the whole row.
Scores remain Player/Goal/Opponent; custom games replace Goal with Custom without a badge. Goals are muted, outcomes gold/red, and long values remain complete.
All twelve previews share one line, scale from 20–28px and retain 44px touch height with narrower triggers. Each side keeps English-name order, duplicates and faces 1–6.
Image Hover Cards show only one localized name on one line via hover/focus/touch. Counts and opponent mode are stored but not displayed.

Ordinary/custom winners append once; abandoned games create no record. Start captures epoch milliseconds, actual loadouts and opponent mode.
Settlement fixes elapsed whole seconds including dialogs/history/background time, final scores/target/winner, ordinary level or custom identity,
both sides' completed turns and throws, and rules/AI policy versions. Every bank, including zero and victory, or Bust ends one turn; initial,
continued and hot-dice throws each count once. Render, animation and save retries cannot duplicate counters, records or rewards.

`cogita.farkle.history` keeps 100 records, dropping the oldest on append. Format 1 uses `[1, rows]`, numeric enums and fixed six-character dice codes;
no names/images are serialized. Missing means empty; invalid data/access errors retain originals and offer retry while blocking new games.
Failed writes retain one in-page snapshot and block new games/Exit until retry or cache reset; reload loses unsaved records. History and reward
saves are independent, and neither retry repeats the other.

## Dice catalog and presentation

The [typed dice catalog](../../frontend/src/components/playground/farkle/dice.ts) owns all 22 integer face distributions, shared by rolling,
probability cards and AI. Favourable never rolls two; Pie never rolls five or six. Random results are supplied to the reducer; deterministic face
drawing does not consume gameplay randomness.

| Type | Material and face appearance |
| --- | --- |
| Normal | Tan wood; large recessed rings |
| Even | Dark yellow metal; large recessed circles |
| Odd / Pie | Copper; large recessed circles |
| Favourable | Silver metal; large recessed circles |
| Devil | Orange amber; large recessed circles, with an engraved head on one |
| Monk | Rusted copper; large recessed circles; the only type with a fine border and slight green edge patina |
| Lucky / Strip / Shrinking | Pale blue-white / pale blue-purple / faded dark blue nonmetal; large recessed circles |
| Unlucky / Grimy | Emerald green / green; large yellow recessed circles |
| Unbalanced | Worn stone; large dark recessed circles |
| Weighted / Misfortune / Aranka | Rough earth-brown plaster / light brown earth / a lighter Weighted finish; small black dots |
| Painted | Blue; large white painted circles |
| Lu / Ci / Fer | Identical blue; large pale blue-white painted circles |
| Heavenly | Warm white; large black painted circles and a broad-ended Maltese cross styled like ✠ on six |
| Merchant | Matte graphite ceramic; teal outlined diamond pips |

Painted circles have no recessed relief. Heavenly uses a sphere cut by six planes into circular faces with the same unit bounds, face normals and material
ordering; its curved connecting surface shares one body material. Physics approximates every type with the standard rounded cube. Heavenly's six-face
texture and preview share the broad-ended ✠ cross; its hover icon, accessible labels and scoring retain numeric six. Lu, Ci and Fer have separate inventory
identities but identical blue appearances and ordinary numeric scoring.

### Inventory and chooser views

Inventory shows all 22 previews: Normal 6 / 6, specials N / 6 and Merchant N / ∞. Preview faces show owned counts capped at six, or five when unowned.
Only unowned images are grayscale, restoring color while hovered. Other views keep their fixed preview faces and colors.
Inventory, custom choosers and Shop use 1200px; ordinary Choose dice uses 480px for 1–6 owned types, 800px for 7–12 and 1200px above 12, independent of copy counts.
All retain 16px viewport margins. Lists use one column below 720px available width, two from 720px and three from 1080px; titles and footers stay outside scrolling.

Inventory/chooser/shop lists sort by full English name in either locale, wrapping long names. Text-height name triggers stay adjacent to quantities
on desktop/touch; hover/focus/touch opens six face-ordered percentages rounded to one decimal, with accessible face descriptions including Devil's head.
Previews, quantities and controls do not trigger these probability cards.

### Shop

Shop lists all twenty special types, including zero stock, with shared previews, probability cards and owned quantities below names; Normal/Merchant are excluded.
Rows have destructive-color Sell and outline Buy buttons; Sell appears only with positive stock. The Merchant icon/count sits beside Shop, with prices below.
Each click trades one die immediately without confirmation: Buy costs two Merchant, Sell returns one. Buy is disabled at six copies or insufficient funds; Sell at safe-integer overflow.
Each trade writes stock and balance together, preserving first wins and current match dice. Failed writes retain the changed in-page inventory and
one snapshot for explicit retry, blocking trades, new matches and Exit. Retry never repeats the trade. Inventory read/reset errors also block trading.
Closing keeps trades; the next ordinary chooser revalidates ownership. Persistence and retry reuse the inventory maintenance mechanism.

## Opponent

Opponent difficulty is `d = clamp(target / 10000, 0, 1)`. Normal and Random choose special counts uniformly from the listed pools, exclude Merchant,
cap Weighted at one and every other named special at three, and fill six slots with Normal dice. These restrictions apply only to A. Normal chooses a
pool equally, then a named combination equally within its score interval. Pool zero is all Normal; pool one samples all twenty special types without
strength filtering.

| Difficulty d | Special-count pools | Normal calibration score intervals |
| --- | --- | --- |
| [0, 0.2] | 0, 1 | Unfiltered |
| (0.2, 0.4] | 1, 2 | Pool 1 unfiltered; pool 2 (40%, 60%] |
| (0.4, 0.6] | 2, 3 | Pool 2 (50%, 80%]; pool 3 (50%, 70%] |
| (0.6, 0.8] | 3, 4 | Both (50%, 80%] |
| (0.8, 1] | 3, 4, 5 | Pool 3 (50%, 90%]; pools 4/5 (50%, 80%] |

Random sequentially samples equally among special types still below their caps, initially 1/20 each. Wild independently samples six slots with
replacement from all 22 types, including Normal/Merchant, without copy or special-count limits. All methods draw only on confirmed Start game;
rerolls, handoffs and AI retries preserve the loadout. Existing scoring, B ownership, AI policy and rewards apply.

### Calibration

Normal's checked-in calibration.json has 50,959 named combinations in pools of 20/209/1,520/8,626/40,584, encoded as fixed-length base-20 special-type
codes and integer wins out of 2,000. Provenance is calibration-full-20261026 at target 5000/policy 1 against ordinary dice; scores are frozen
selection labels, not predicted player win rates. Lu/Ci/Fer retain separate names, caps and probability mass. Candidate indexes are reused. Only the
Farkle page imports the table; the AI worker/shared catalog do not. Capture/test boundaries verify source parity, record digest, catalog identity and
validity, with no generator, external source path or per-match hash scan.

### Decisions and timing

All levels enumerate complete scoring subsets and share exact full-turn expected values in a match-local Web Worker, caching roll outcomes with
50-point dynamic-programming steps and omitting zero-probability faces. The stopping threshold is the maximum single-roll expected bank score divided
by Bust probability across canonical remaining type sets. Dynamic programming allocates only these sets and rounds below the smaller of the threshold
and remaining goal; above it, one roll then banking gives the exact value. Computation and memory therefore depend on loadout, without truncating the
winning target; highly weighted six-die combinations cost more. Values use remaining dice types, Round, remaining target and six-die renewal, capping
final rewards at that target.

Banking takes the highest score; immediate wins always bank. Continuing cannot omit another independently scoring batch when both release all six
dice. Choices retaining different die types stay distinct. Values assume optimal subsequent play; lower-level moves continue only if the best
continuation exceeds banking by 15% × (1-d). Ties bank; continuation ties prefer higher immediate score, then stable die order.

After each A roll, calculation overlaps 1500ms thinking; action waits for both. A hovers each selected die for 550ms in physical-face/index order,
then holds the completed selection for 900ms before ordinary store/pass animation and reduction.

Dialogs, history, mobile drawers and document invisibility pause operations with remaining delays intact. In-flight animations/end-of-turn pauses
still finish. Calculation failures offer localized retry of the same position and selected dice, without a random or simplified strategy.

## Rewards and browser storage

Every ordinary-level defeat grants 1 special. Ordinary-level rewards settle once when Q banking produces a winner: B means victory and A defeat. Exit,
refresh and mid-game restart grant nothing. Special rewards choose uniformly among types still below six, updating candidates after each award. When
all twenty types are full, remaining special awards convert together to ceil(remaining / 2) Merchant dice, added to the base and first-win amounts.

First wins are per level and only for victories. Results list regular, first-win Merchant and converted Merchant rewards, separating only nonempty groups.
Regular Merchant quantity excludes first-win and converted amounts. Bonus rows prefix their +N with localized First win or Converted, with no
secondary explanations. Rewards scroll on short screens while the summary and replay controls remain visible.

One fixed settlement writes inventory and first wins together. Dialog changes and renders cannot award again. Failed saves retain the same pending
reward for explicit retry, update the in-page balance and block another match or Exit until saved; a full page reload loses an unsaved settlement.

### Browser storage

Browser localStorage shares fixed `a–v` identities from [diceEncoding.ts](../../frontend/src/components/playground/farkle/diceEncoding.ts). `cogita.farkle.inventory` stores
`{dice: {code: count}, firstWins: [...]}`: only positive special/Merchant counts, with missing counts zero. Specials cap at six; Merchant has no gameplay cap.
Normal stays six and is never written. Parsing validates codes/counts/levels, ignores injected `a`, and preserves unreadable inventory with localized retry.

`cogita.farkle.loadout` stores a raw six-character dice string on ordinary Start. Missing/invalid selections default to six Normal without writing.
Ownership clipping replaces only missing copies with Normal without writing. Read/save failures retain drafts, offer retry and block starting.

`cogita.farkle.settings` stores `{opponentDiceMode: dynamic|random|wild}`. Missing/malformed values default to Normal without writing. Changes save immediately;
read failures show retry and temporarily use Normal, while save failures retain the effective mode and requested choice for retry.

`cogita.farkle.customGame` stores `{target, opponentDiceMode, opponentLoadout, playerLoadout}` with six-character loadouts, defaulting to 1500/Normal/six Normal.
Only the current short-code representations are read; no migration occurs. Missing/malformed configurations default without writing; access failures require retry.
Custom Start saves this configuration before sampling, retaining both drafts and blocking start on failure; ordinary loadout storage is untouched.

## Settings and maintenance

Settings opens a scrolling modal with English / Simplified Chinese, Opponent dice and inventory controls; it shares pause/drawer/focus behavior.
Language changes apply globally, persist in `cogita.locale` and retain matches, with save retry. Opponent Normal / Random / Wild uses a sliding
single-select with keyboard/touch/reduced-motion support. Settings and Custom game describe tested/bounded/unrestricted/manual combinations.
Mode IDs are dynamic/random/wild/custom; changes apply to the next confirmed new game or replay.

| Inventory action | Effect |
| --- | --- |
| Fill dice | Set all twenty special counts to six and Merchant to exactly 999 |
| Clear dice | Set all special and Merchant counts to zero |
| Add Merchant dice | Add 999 Merchant dice |
| Clear Merchant dice | Set only Merchant to zero |

Actions have no helper text, use two desktop/one mobile columns and preserve Normal, first wins, current dice and selections. Choosers revalidate ownership.
Unreadable inventory/pending writes disable actions; unsafe additions are disabled. One fixed snapshot supports retry without repeating additions/rewards.

Clear cache is a separated destructive-color button with a repair/reset description. It removes all five Farkle keys, including history and first
wins, preserves language/unrelated preferences and remains available on storage errors.

Successful removal closes the modal, ends the match, cancels animations/opponent work and discards rewards, history, pending writes and drafts.
Removal failure can leave some keys removed; an error offers retry of all five removals, and blocks inventory changes, new matches and Exit
until reset succeeds. None of the five actions opens a confirmation dialog.

## Table rendering and trajectories

Tavern-green baize fills the content, with fine weave, subtle relief and diffuse nap. A central antique golden silk ribbon has dark stitching,
cord piping and soft shadow; it peeks into both views and the camera crosses it. Outer edges/slot outlines are hidden. Deterministic repeating
color/bump textures retain world scale and anchoring on resize.

The 85-degree perspective camera excludes opposite dice and center-line midpoint when settled. At widths ≥768px, mirrored storage anchors sit near
the center-line edge, extending left at fixed dice scale/camera distance. Narrow views enlarge/center throws with storage offscreen right.
Resize/sidebar changes reframe airborne and settled dice; projected targets follow, with offscreen dice excluded from focus/accessibility navigation.

Desktop scores stay compact; narrow/short HUDs compress spacing/type to keep six-digit totals/targets/rounds, four-digit Selected and row labels
on one line. Longer numbers wrap within aligned columns without overlapping actions; touch actions retain 44px targets.

The lazy Three.js scene only interpolates offline Rapier poses: 32 deterministic throws each for 1-5 dice and 64 for six. Unit rounded dice fall from
5.8-6.8 plus 0.15 per channel onto an open plane without invisible walls. The 960Hz simulation records at 60Hz; accepted throws last 0.9-1.35 seconds,
stay within center bounds x ±3.2/z ±2.5, settle flat at least 1.4 apart and limit floor/dice penetration to 0.02, including interpolated playback. The
checked-in recipe owns gravity, contact and damping parameters. Playback uses only 0/180-degree yaw, X reflection, shuffled channels and 0.94-1.06
speed; each dice count excludes its last eight trajectories until match reset.

Face correction retains chosen values and height-based shadows. Geometry/materials are cached by shape/type; rendering occurs only on invalidation
or animation. Departure disposes resources/textures. Renderer failure gives localized reload feedback; the embedded version also retains Back.

## Current limitations

History is summary-only, without cross-device/multi-tab coordination. Gameplay badges, in-progress saves, replay/event logs and game APIs are unavailable,
as are personality traits, random errors, whole-match win-probability modeling, live physics, audio and binary trajectories.
