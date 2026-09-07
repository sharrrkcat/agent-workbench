# Conversation replies and processing history

Accepted 2026-09-07 after the completed roadmap and session simplification.
Status: complete.

## Accepted behavior

- One visible reply per run, with one Persona identity, processing timeline,
  final answer and action bar. Internal assistant/tool messages remain distinct.
- Remove the chat footer RunPanel. General show_full_processing defaults false;
  it controls initial active expansion only. Terminal replies collapse history.
- Adjacent tool calls share a collapsed group. Expanding a group reveals command
  rows; expanding a command reveals arguments, output, errors and truncation.
- Stream ordinary text immediately, moving it into processing history when its
  model round produces tool calls. Keep reasoning separate from answer text.
- Approvals remain actionable outside collapsed history. Run elapsed time includes
  preparation, tools and approval waits, and freezes at the terminal timestamp.
- Preserve incomplete output on controlled cancellation and caught failures.
- Delete and retry whole replies. Retry removes the selected run and later
  conversation, preserving its input and using the original Persona.

## Implementation checklist

- [x] Shared reasoning normalization, typed deltas and incomplete persistence.
- [x] Transactional history pruning, run deletion/retry and stale-response guards.
- [x] Reply timeline, approvals, nested tools, scrolling and General preference.
- [x] Backend/frontend tests, desktop/mobile and both-locale browser checks.
- [x] Contracts, task cards, full quality gates and final verification record.

Existing JSON columns and content_version=2 remain. No schema migration or old
record conversion is required. Hard process termination retains only data already
persisted; streaming-delta event persistence remains a separate debug setting.

## Verification record

Completed 2026-09-07. Backend checks use deterministic OpenAI-compatible responses
and both memory/SQLite stores. Browser checks use isolated temporary files/state;
no real-model inference or schema/data reset was performed.

| Command | Result |
| --- | --- |
| `uv run --no-sync pytest -q --tb=short` | 282 passed in 217.98s |
| `uv run --no-sync python -m compileall -q ai_workbench` | Passed |
| frontend `npm test` | All suites passed, including presentation/state tests |
| frontend `npm run build` | TypeScript and production build passed |
| frontend `npm run test:browser` | 14 passed, 1.9 minutes |
| `uv run --no-sync python scripts/check_docs_size.py` | All limits passed |
| `uv run --no-sync python scripts/audit_workspace.py --check` | Integrity ok; 0009; no errors |
| `git -c core.safecrlf=false diff --check` | Passed |

Browser cases cover English/Chinese at 1366x900 and 390x844, both live modes,
manual expansion through deltas, terminal collapse, 12 adjacent commands, bounded
large JSON, approval controls, cancellation/reload, explicit scroll following,
whole-reply retry and deletion. Screenshots are in frontend/test-results.
Desktop and mobile completion, processing and approval screenshots were inspected.

The normal local application was started with
`.venv/Scripts/python.exe scripts/run_app.py --no-open --port 8765`.
GET / and /api/health returned 200; health reports database ok and schema 0009.
Logs are data/presentation-server.out.log and data/presentation-server.err.log.

## API and workflow changes

- General GET/PATCH adds strict show_full_processing=false. The saved preference
  immediately updates active reply display; it never controls recording.
- Assistant reasoning parts are strict {id,type:reasoning,text}; model messages
  and deltas accept reasoning_content. Internal <think> parsing preserves inline,
  fenced and indented code. General history omits reasoning/incomplete output.
- message_delta includes part_id/part_type plus its existing per-message seq.
  Failed/cancelled partial output uses the original id and incomplete=true.
- DELETE /api/runs/{id} removes a whole reply. POST /api/runs/{id}/retry replaces
  the selected chat reply and later conversation. Message retry is removed;
  message delete/edit now applies to users and also prunes associated runs.
- Pruning commits atomically and returns/emits deleted_message_ids/deleted_run_ids.
  Frontend deletion guards and session epochs prevent stale restoration.
- Controlled cancellation returns its cancelled run through REST without HTTP
  errors. Final/partial answers and approvals remain outside collapsed history.
- Added @playwright/test 1.63.0 as a development dependency and test:browser;
  Chromium is required only for browser checks. Runtime dependencies are unchanged.

## Changed files

- API: ai_workbench/api/deps.py, routes/messages.py and routes/runs.py.
- Core: assistant_output.py, conversation_history.py, chat_runner.py, context.py,
  events.py, harness/agent_loop.py, message_parts.py, models/schema.py, runtime.py,
  schema/message.py, settings.py and stores.py under ai_workbench/core.
- Persistence: ai_workbench/db/stores.py. Existing JSON columns and schema head
  remain; no migration, record conversion or compatibility implementation.
- Frontend composition: src/App.tsx; components/ChatInput.tsx, ChatView.tsx,
  MessageBubble.tsx, RunPanel.tsx and settings/GeneralPanel.tsx.
- Message UI: MessageActions.tsx, MessageParts.tsx, MessageFrame.tsx,
  ReplyActions.tsx, RunApproval.tsx, RunReply.tsx, ToolGroup.tsx, ToolResultBody.tsx,
  messageContent.ts and turns.ts under frontend/src/components/messages.
- Frontend state/contracts: src/api/chat.ts and runs.ts; src/types/messages.ts,
  runs.ts and settings.ts; src/store/messageStream.ts, useWorkbenchStore.ts,
  workbench/mergeState.ts, messageActions.ts, runActions.ts, runtimeEvents.ts,
  sessionActions.ts and state.ts; src/styles.css.
- Locales: en and zh-CN personas.json, runs.json and settings.json under
  frontend/src/i18n/resources.
- Tests: tests/test_chat_presentation.py, presentation_smoke_server.py,
  test_phase3_personas.py, test_phase4_harness.py and tool_fixtures.py;
  frontend/scripts/test-chat-presentation.mjs, test-all.mjs, test-contracts.mjs,
  test-model-stream.mjs; frontend/tests/chat-presentation.spec.ts,
  playwright.config.ts, package.json and package-lock.json.
- Documentation: README.md, docs/AI_CONTEXT.md, this plan,
  docs/ai/DOCS_MAINTENANCE.md, TASK_FRONTEND_UI.md and TASK_SETTINGS.md;
  chat-context, harness-tools, models, runs-streaming and settings contracts.

## Remaining limits

- Real model/provider behavior was not exercised; fixtures cover the accepted
  OpenAI-compatible fields and native tool continuations.
- Hard process termination retains only persisted data. This change does not
  checkpoint each streaming token or reconstruct previous-version records.
- An ordinary-text round is provisional until its tool/no-tool finish is known;
  text moves into processing when calls arrive, as accepted in the plan.
