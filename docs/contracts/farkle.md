# Farkle contract

Farkle is a browser-local Playground game at `/playground/farkle`, with a human player (B) and an automatic opponent (A).
[Settings](settings.md#frontend-styling-foundation) owns the shared shell, controls, Playground navigation and conversation-departure rules. The
[Farkle task card](../ai/TASK_FARKLE.md) locates source, artifacts and tests; [README](../../README.md#verification) owns verification commands.

## Navigation and match setup

Farkle uses SidebarProvider with New Game, Custom game, My Dice, Shop and Settings; the footer is Back to Playground when idle or Exit Game when
playing. Exit clears both sides and cancels animations and opponent operations. The camera follows turns automatically; manual view switching is
unavailable. The header keeps its title/toggle and the actual Merchant Dice balance; balance and Shop open the same trading dialog.

Clicking anywhere on the idle, exited or finished table opens New Game, with a keyboard-activatable full-table entry disabled while another dialog or
mobile drawer is open. Dismissal does not click through; New Game and Exit remain available.

New Game defaults to Beggars. Each ordinary level has its own target and victory rewards; first-win Merchant dice are additional. [Reward
settlement](#rewards-and-browser-storage) owns defeat awards, conversion and persistence.

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

The single-select level list scrolls between its heading and fixed progression controls. Choose dice is a separate dialog step with owned types,
smaller muted `owned N` / `拥有N` quantities below names and right-aligned minus/count/plus controls. Selections always total six, with Normal filling spare slots. All
choosers highlight selected types with a green border and background in six intensity steps; zero-count rows and My Dice have no highlight.

Adding a non-Normal replaces one Normal, subject to ownership and a spare Normal; removing one restores a Normal. Normal cannot be removed directly;
adding one replaces the first selected non-Normal in full English-name order, including Merchant.

Start game saves the selection, resets both sides and immediately rolls B's chosen dice; A uses the [opponent loadout rules](#opponent). Back retains
the draft at level selection; closing discards unconfirmed changes. Selection and sampling consume no inventory. Types stay fixed through rerolls and
handoffs.

### Custom games

Custom game has a target input and a sliding Normal / Random / Wild / Custom single-select, independent of Settings. Targets are decimal integers
strictly between 1 and Number.MAX_SAFE_INTEGER (9007199254740991), including nonmultiples of 50. Syntax, lower-bound and upper-bound errors each
disable progression with distinct localized feedback.

Generated modes open Choose dice for player; Custom first opens Choose dice for opponent. Both reuse six-die balancing, English ordering, previews and
probability cards. Both sides have all 22 types at six copies each without inventory quantities, independently of owned stock. Back retains drafts;
closing discards unconfirmed edits. Pause, drawer closure and focus restoration follow the ordinary flow.

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
actions and opens localized You win! / You lost! in centered gold/red score-heading typography. The centered Score line shows only B's banked total,
using score-total typography and Round color, always smaller than the title; no separate winner or opponent-score rows appear. Ordinary Play again
opens Choose dice at the same level with the last confirmed selection; New Game opens that level in difficulty selection. Closing leaves the finished
board frozen.

Restart/exit/departure cancel animations, pending Bust handoffs, opponent timers and worker results. Matches reset on refresh/departure.
Only inventory, per-level first wins, ordinary player selection, custom configuration including both loadouts and opponent settings persist locally.

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

Painted circles have no recessed relief. Heavenly uses a dedicated sphere cut by six planes to form circular faces, with the same unit bounds, face
normals and material ordering; its curved connecting surface shares one body material, while physics still approximates every type with the standard
rounded cube. The six-face texture and circular preview share the broad-ended ✠ cross for six; the hover hint uses the ordinary six-pip icon, and
accessible labels and scoring retain numeric six. Lu, Ci and Fer have separate inventory identities but identical blue appearances and ordinary
numeric scoring.

### Inventory and chooser views

My Dice shows all 22 material previews: Normal 6 / 6, special quantities out of six and Merchant N / ∞. Its maximum width is 1200px; Choose dice uses
480px for 1–6 owned types, 800px for 7–12 and 1200px above 12, independent of selected copy counts. Custom choosers and Shop use 1200px. All retain 16px viewport margins. Scrolling lists
use one column below 720px available width, two from 720px and three from 1080px; titles and footers stay outside the scroller.

All lists sort by full English name in either locale; long names wrap. Names above owned quantities use text-height triggers on desktop/touch, keeping both lines adjacent. Shared shadcn Hover Cards activate only
from names by hover, focus or touch. Each shows six face-ordered percentages from gameplay weights, rounded to one decimal percent, with accessible
face descriptions including Devil's head. Previews, quantities and quantity controls do not trigger cards.

### Shop

Shop lists all twenty special types, including zero stock, with shared previews, probability cards and owned quantities below names; Normal/Merchant are excluded.
Rows have destructive-color Sell and outline Buy buttons. The Merchant icon/count sits beside Shop; secondary text below states the prices.
Each click immediately trades one die without confirmation: Buy costs two Merchant, Sell returns one. Buy is disabled at six copies or insufficient funds; Sell at zero stock or safe-integer overflow.
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

After each settled A roll, calculation overlaps a 1500ms thinking pause; action waits for both. A then hovers each chosen die for 550ms before
selecting it, in physical-face/index order, and holds the completed selection for 900ms before using the ordinary store/pass animation and reducer
flow.

Dialogs, mobile drawers and document invisibility pause the operation clock, preserving the remaining delay; closing/resuming continues the same move.
In-flight roll/storage/camera animations and the end-of-turn pause retain their completion behavior. Calculation failures show localized feedback and
offer retry of the same position, preserving already selected dice; no random or simplified strategy is substituted.

## Rewards and browser storage

Every ordinary-level defeat grants 1 special. Ordinary-level rewards settle once when Q banking produces a winner: B means victory and A defeat. Exit,
refresh and mid-game restart grant nothing. Special rewards choose uniformly among types still below six, updating candidates after each award. When
all twenty types are full, remaining special awards convert together to ceil(remaining / 2) Merchant dice, added to the base and first-win amounts.

First wins are tracked independently by level; defeats do not claim them. A Courtiers victory with only two special copies missing grants those two
plus three Merchant dice, or five Merchant dice on the first win.

The result lists regular rewards, first-win Merchant dice and converted Merchant dice in that order, with separators only between nonempty groups.
Regular Merchant quantity excludes first-win and converted amounts. Bonus rows prefix their +N with localized First win or Converted, with no
secondary explanations. Rewards scroll on short screens while the summary and replay controls remain visible.

One fixed settlement writes inventory and first wins together. Dialog changes and renders cannot award again. Failed saves retain the same pending
reward for explicit retry, update the in-page balance and block another match or Exit until saved; a full page reload loses an unsaved settlement.

### Browser storage

The owned Normal count is always six by a frontend rule and is never serialized in inventory. `cogita.farkle.inventory` in localStorage holds twenty
special counts (each initially zero, maximum six), an initially zero Merchant count with no gameplay cap, and first-win level IDs. No database or
backend owns these values. Storage parsing requires every special count and validates counts and level IDs, ignores injected Normal counts and does
not overwrite unreadable data; localized errors allow retry.

`cogita.farkle.loadout` belongs only to ordinary Choose dice and stores all 22 counts on confirmed Start game. Missing/invalid selections default to six Normal;
parsing requires exactly six valid copies. Counts exceeding current ownership are clipped, with only missing copies replaced by Normal; other choices
remain selected. Reading never writes the adjusted draft. Read failures offer retry; save failures retain the draft and block starting for explicit retry.

`cogita.farkle.settings` stores `{opponentDiceMode: dynamic|random|wild}`. Missing/malformed values default to Normal without writing. Changes save immediately;
read failures show retry and temporarily use Normal, while save failures retain the effective mode and requested choice for retry.

`cogita.farkle.customGame` stores `{target, opponentDiceMode, opponentLoadout, playerLoadout}`, defaulting to 1500, Normal mode and six Normal dice per
side. Both loadouts require six valid copies from the full catalog. Missing/malformed values, including a missing playerLoadout, default without
writing or migration; access failures require retry. Custom Start game saves only this configuration before sampling or starting. A failed save retains
both drafts and blocks starting for explicit retry. Ordinary loadout storage is neither read nor written by custom games.

## Settings and maintenance

Settings follows Shop and opens a scrolling modal with the shared English / Simplified Chinese selector, Opponent dice and inventory controls.
Language changes apply application-wide immediately, persist in `cogita.locale` and preserve the match; failed writes offer retry. Opponent Normal /
Random / Wild is a sliding single-select with keyboard/touch and reduced-motion support. Settings and Custom game show localized mode descriptions:
tested combinations, bounded randomness, unrestricted randomness or manually chosen opponent dice. Mode IDs are dynamic/random/wild/custom; opponent
changes apply to the next confirmed new game or replay. The modal shares pause, drawer-close and focus restoration behavior.

Settings inventory actions have no helper text and use two columns on desktop and one on mobile.

| Inventory action | Effect |
| --- | --- |
| Fill dice | Set all twenty special counts to six and Merchant to exactly 999 |
| Clear dice | Set all special and Merchant counts to zero |
| Add Merchant dice | Add 999 Merchant dice |
| Clear Merchant dice | Set only Merchant to zero |

Normal stays six and first wins remain intact. Actions update the balance without changing confirmed match dice or the saved loadout; the next chooser
revalidates ownership and replaces only missing copies with Normal. Unreadable inventory and pending writes disable these actions; additions above
the safe-integer boundary are disabled. Each action retains one pending inventory snapshot for explicit save retry, without repeating additions or
settled rewards.

Clear cache is a separated destructive-color button with a repair/reset description. It directly removes the four Farkle localStorage keys above,
including first wins, while preserving the application language and unrelated preferences. It remains available on storage errors.

Successful removal closes the modal, ends the match, cancels animations/opponent work and discards rewards, pending writes and drafts before restoring
defaults. Removal failure can leave some keys removed; an error offers retry of all four removals, and blocks inventory changes, new matches and Exit
until reset succeeds. None of the five actions opens a confirmation dialog.

## Table rendering and trajectories

A continuous tavern-green baize table fills the content below the header, with fine woven texture, subtle relief and diffuse nap. An antique golden
silk ribbon divides its center, with dark stitched borders, cord piping and soft shadow; outer table edges and slot outlines are hidden. The ribbon
peeks into both views and the camera sweeps across it. Deterministic repeating color/bump textures have fixed world scale and anchoring, so resizing
does not stretch or slide either pattern.

The perspective camera stays at 85 degrees; settled views exclude opposite dice and the center-line midpoint. Widths of 768px and above frame the
throw and right-hand storage, with mirrored row anchors near the center-line edge; rows extend left without changing dice scale or camera distance.
Narrower views enlarge and center the throw and put every storage row beyond the right edge. Resizing/sidebar changes reframe the scene, including
airborne dice; projected hit targets follow the dice, and offscreen dice leave focus/accessibility navigation.

Desktop scores stay compact. Narrow/short layouts compress HUD spacing and typography, reducing number size when needed for six digits. Totals,
targets and rounds through six digits, four-digit Selected scores and Round/Selected labels stay on one line; longer values may wrap within aligned columns without overlapping
actions. Touch actions retain 44px targets.

Rapier is an offline development dependency; the browser only interpolates baked poses.
The lazy Three.js scene uses Cogita's deterministic Rapier trajectory library: 32 throws each for 1-5 dice and 64 for six. Unit rounded dice fall from
5.8-6.8 plus 0.15 per channel onto an open plane without invisible walls. The 960Hz simulation records at 60Hz; accepted throws last 0.9-1.35 seconds,
stay within center bounds x ±3.2/z ±2.5, settle flat at least 1.4 apart and limit floor/dice penetration to 0.02, including interpolated playback. The
checked-in recipe owns gravity, contact and damping parameters. Playback uses only 0/180-degree yaw, X reflection, shuffled channels and 0.94-1.06
speed; each dice count excludes its last eight trajectories until match reset.

Face correction retains gameplay-selected values and height-based shadows. Geometry and materials are shared and cached by shape/type; rendering
occurs only when invalidated/animating, and departure disposes resources including color and bump textures. Renderer failure displays localized
feedback and leaves Back available.

## Current limitations

Badges, saved matches and game APIs are unimplemented. There is no cross-device sync or coordination of simultaneous games in multiple tabs.

Personality traits, random decision errors, whole-match win-probability modeling, live physics, audio and a binary trajectory pipeline are unavailable.
