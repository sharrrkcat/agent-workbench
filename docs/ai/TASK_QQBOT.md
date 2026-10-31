# Task: QQBot

Read the [QQBot contract](../contracts/qqbot.md) for configuration, triggers, batches,
media, delivery, history, UI/API behavior and acceptance limits.
[Chat/context](../contracts/chat-context.md), [Harness/tools](../contracts/harness-tools.md)
and [Runs/streaming](../contracts/runs-streaming.md) own shared execution contracts.
[Models](../contracts/models.md) owns inference; [Settings](../contracts/settings.md)
and the [Frontend task](TASK_FRONTEND_UI.md) own shared UI/navigation foundations.

## Backend source map

Paths below are under [ai_workbench/](../../ai_workbench/):

- core/qq_service.py assembles OneBot connections, receipt-ordered trigger decisions,
  Project FIFO execution, the four QQ tools, delivery confirmation and pause/resume/stop.
  api/deps.py wires the service; core/harness/agent_loop.py integrates tool visibility,
  reply decisions, quotas, budget exceptions and run metadata.
- core/qq_programs.py handles direct commands, administrator routing and durable
  notifications; core/qq_diagnostics.py formats local checks and prior-call context statistics.
- core/qq_protocol.py owns OneBot transport, normalization, cards and native-timeout
  classification. core/qq_names.py owns mention spans, identity lookup/cache and
  frozen model-facing names; core/qq_segments.py projects ordered display/model segments.
- core/qq_store.py owns durable batches, participants, receipts and restart recovery;
  db/qq_models.py defines QQ records. core/qq_icebreaker.py owns group activity,
  observations, cancellation eligibility and cooldowns.
- core/qq_context.py builds current/historical input and per-call QQ runtime data;
  core/qq_history.py owns local deletion, input reconstruction and history invalidation.
  Shared token budgets and request inspection use core/context.py and core/context_snapshot.py.
- core/qq_media.py acquires/decodes originals and static model frames;
  core/qq_descriptions.py owns asynchronous captions. core/qq_generation.py prepares
  provider images; core/qq_resources.py owns gallery queries, edits and shared deletion.
  core/harness/network.py owns public-network downloads; core/attachments.py owns files.
- core/schema/project.py defines Project settings and the default prompt;
  core/schema/qq.py defines tool identities, candidates and ordered media types.
  api/schemas/projects.py and api/routes/qq.py expose strict Project/QQ APIs.
- core/qq_faces.json and [third_party/qface/](../../third_party/qface/) contain
  system-face data/notices. [Data layout](../DATA_LAYOUT.md) owns QQ revision effects;
  executable migrations live in [alembic/versions/](../../alembic/versions/).

## Frontend source map

Paths below are under [frontend/src/](../../frontend/src/):

- components/projects/QQBotEditor.tsx owns shared creation/settings tabs and drafts;
  QQImageGenerationFields.tsx owns generation controls; QQSessionDialog.tsx binds targets.
- QQSessionView.tsx, QQMessageContent.tsx and useQQConversation.ts in components/projects/
  own conversation rendering, model/reasoning controls, delivery states and polling.
  qqConversation.ts owns history/version reconciliation and local deletion state.
- QQResourcesPage.tsx and qqResources.ts in the same directory own gallery/Sheet
  state, filtering, URL pagination, favorites, descriptions and guarded navigation.
- api/qq.ts and types/projects.ts define clients/types; store/useProjectsStore.ts
  owns Project mutations. components/projects/ProjectsTree.tsx, ProjectPage.tsx,
  NewProjectDialog.tsx and navigation.ts connect QQ views to the shared shell and App.tsx.
- Follow the [i18n guide](../../frontend/src/i18n/README.md) for both locales.

## Verification map

Use [README verification](../../README.md#verification) and the
[QQBot browser command](../../README.md#qqbot-projects). Backend tests run only for
backend changes; docs-only work still runs frontend tests/build and documentation gates.
The [run guide](../../README_RUN.md#qqbot-deployment) owns deployment conclusions;
simulated tests do not establish the [outstanding live acceptance](../contracts/qqbot.md#limits-and-acceptance).

Backend tests under [tests/](../../tests/):

- test_qqbot.py: Project/token/binding restrictions, fake OneBot/model integration,
  FIFO/dedup, reply failures, stop, reconnect and memory/SQLite recovery.
- test_qq_triggers.py, test_qq_followup.py and test_qq_names.py: real mentions/account
  keywords, receipt ordering, lookup deadlines, participant epochs and skip/renewal races.
- test_qq_resume.py: atomic backlog coalescing, retained participants/keywords/media,
  FIFO placement, pending nickname decisions and rollback.
- test_qq_commands.py, test_qq_notifications.py and test_qq_commands_migration.py:
  permissions, context isolation, atomic controls, send concurrency, alerts and restart.
- test_qq_reply_policy.py and test_qq_delivery_receipts.py: mandatory decisions,
  shared quotas, exact receipt identity, early self reports, deadlines and unknown sends.
- test_qq_web_tools.py: global web settings, citation-free requests/results, shared rounds,
  reply/skip decisions, request snapshots, error recovery, timeouts and cancellation.
- test_qq_icebreaker.py: cold/observation timing, single replies, cancellation races,
  eligibility grants, cooldown isolation and lifecycle recovery.
- test_qq_context.py, test_qq_cards.py and test_qq_history_deletion.py: paired history,
  context pruning, prompt snapshots, normalized cards and local deletion semantics.
- test_qq_media.py, test_qq_media_assets.py and test_qq_resources.py: ordered media,
  current-batch selection, acquisition/captions, shared retention, gallery edits/deletion.
- test_qq_image_tools.py and test_qq_image_generation.py: candidate snapshots,
  original animations, generation keyword permissions, provider preparation, shared
  quotas, text-only history, cancellation, timeout exemptions and resource retention.
- test_qq_followup_migration.py, test_qq_media_assets_migration.py,
  test_qq_icebreaker_migration.py and test_qq_trigger_grants_migration.py cover
  durable schema changes; QQ/image suites also cover their associated migrations.

Frontend scripts under [frontend/scripts/](../../frontend/scripts/) include
test-qq-conversation.mjs for history/deletion/version and editor state, and
test-qq-resources.mjs for resource API, URL and pagination contracts.
Browser suites under [frontend/tests/](../../frontend/tests/) use English/Chinese desktop/touch fixtures:

- qqbot.spec.ts: creation/token/binding, sender grouping, history, delivery/skip,
  usage/context inspection, composer controls and delayed/failed Project saves.
- qqbot-web-tools.spec.ts: search/fetch traces without citations, error recovery and reload.
- qqbot-images.spec.ts and qqbot-send-image.spec.ts: image input, ordered media,
  original animations, previews, pending refresh, placeholders and delivery deletion.
- qqbot-generation.spec.ts: provider-only selection/controls, retained failed saves,
  generation recovery, image delivery/deletion and Stop.
- qqbot-delete.spec.ts: bubble/reply confirmations, busy/failure feedback and reconciliation.
- qqbot-resources.spec.ts: gallery/grid, Sheet drafts, favorites, sorting/pagination,
  deletion placeholders and navigation races.
- qqbot-icebreaker.spec.ts and qqbot-settings-layout.spec.ts: defaults, conditional
  controls, tabs/grids, bounded fields, cross-tab validation and busy/failed saves.
- qqbot-commands.spec.ts: administrator validation/saves and program-message history.

[tests/qq_browser_fixture.py](../../tests/qq_browser_fixture.py) supplies isolated
browser APIs/media. Shared Project/navigation and context-detail suites remain
listed in the [Frontend task](TASK_FRONTEND_UI.md).
