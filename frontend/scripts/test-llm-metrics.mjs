import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { createModuleLoader, mockModule, apiMocks } from './module-loader.mjs';

const resources = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale, {
  runs: JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/runs.json`, import.meta.url), 'utf8')),
}]));
const i18n = i18next.createInstance();
await i18n.init({ resources, lng: 'en', fallbackLng: 'en', interpolation: { escapeValue: false } });
const load = createModuleLoader({ ...apiMocks({}),
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace), i18n }) }),
});
const { buildReplyMetrics } = (await load('../src/components/messages/aggregateReplyMetrics.ts')).exports;
const { ReplyMetrics } = (await load('../src/components/messages/ReplyMetrics.tsx')).exports;
const { MessageScrollerProvider } = (await load('../src/components/ui/message-scroller.tsx')).exports;
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const at = (seconds) => `2026-10-01T00:00:${String(seconds).padStart(2, '0')}.000000Z`;
const run = { run_id: 'r', session_id: 's', kind: 'chat', persona_id: 'p', status: 'DONE',
  started_at: at(0), created_at: at(0), finished_at: at(15), updated_at: at(15) };
const call = (id, order, generated, ms, source) => ({
  step_id: id, run_id: 'r', kind: 'model', status: 'completed', order, created_at: at(order), updated_at: at(14),
  metadata: { llm: { model_profile_id: 'p', model: 'local-model', message_id: id, started_at: at(order),
    first_response_at: at(order + 2), completed: true,
    usage: { prompt_tokens: 1000, completion_tokens: generated, total_tokens: 1000 + generated,
      prompt_tokens_details: { cached_tokens: 800 }, completion_tokens_details: { reasoning_tokens: 10 } },
    timing: { first_response_ms: 2000, total_ms: 2500, queue_ms: 0, load_ms: null,
      generation_tokens: generated, generation_ms: ms, tokens_per_second: generated * 1000 / ms, tps_source: source } } },
});
const first = call('a', 0, 100, 2000, 'native');
const second = call('b', 1, 50, 3000, 'estimated');
const reply = { run, steps: [second, first], messages: [], process: [], answerParts: [] };
const metrics = buildReplyMetrics(reply);
assert.equal(metrics.inputTokens, 2000);
assert.equal(metrics.outputTokens, 150);
assert.equal(metrics.tokensPerSecond, 30, 'Speed is weighted by generation duration, excluding tool/approval time');
assert.equal(metrics.estimated, true);
assert.equal(metrics.complete, true);
assert.equal(metrics.firstResponseMs, 2000);
assert.equal(metrics.totalMs, 15000);
assert.deepEqual(metrics.steps.map((step) => step.step_id), ['a', 'b']);
assert.equal(buildReplyMetrics({ ...reply, run: { ...run, kind: 'tool' } }), null);
assert.equal(buildReplyMetrics({ ...reply, steps: [{ ...first, metadata: {} }] }), null);
const incompleteCall = { ...second, metadata: { llm: { ...second.metadata.llm, usage: null, completed: false } } };
const partial = { ...reply, run: { ...run, status: 'CANCELLED' }, steps: [first, incompleteCall] };
const known = buildReplyMetrics(partial);
assert.equal(known.complete, false);
assert.equal(known.inputTokens, 1000);
assert.equal(known.outputTokens, 100);
assert.equal(known.tokensPerSecond, null);
const missing = buildReplyMetrics({ ...reply, steps: [first, { ...second, metadata: {} }] });
assert.equal(missing.complete, false);
assert.equal(missing.tokensPerSecond, null);
const zero = { ...first, metadata: { llm: { ...first.metadata.llm,
  usage: { ...first.metadata.llm.usage, prompt_tokens: 0, completion_tokens: null, total_tokens: null } } } };
assert.equal(buildReplyMetrics({ ...reply, steps: [zero] }).inputTokens, 0);
assert.equal(buildReplyMetrics({ ...reply, steps: [zero] }).outputTokens, null);
const paused = { ...reply, run: { ...run, status: 'WAITING_FOR_USER', finished_at: null }, steps: [first] };
assert.equal(buildReplyMetrics(paused, Date.parse(at(50))).totalMs, 50000);
assert.equal(buildReplyMetrics(paused, Date.parse(at(50))).tokensPerSecond, 50);
const nonstream = { ...first, metadata: { llm: { ...first.metadata.llm, first_response_at: null,
  timing: { ...first.metadata.llm.timing, first_response_ms: null, generation_tokens: null, generation_ms: null, tokens_per_second: null, tps_source: null } } } };
assert.equal(buildReplyMetrics({ ...reply, steps: [nonstream] }).firstResponseMs, null);
assert.equal(buildReplyMetrics({ ...reply, steps: [nonstream] }).tokensPerSecond, null);

// Existing event reconciliation must retain one snapshot per step, including
// terminal histories and late duplicates, without incrementing totals.
store.setState({ currentSession: { session_id: 's' }, runs: [run], stepsByRunId: {},
  deletedRunIds: [], deletedMessageIds: [], runVersion: 0 });
const event = (step) => ({ type: 'run_step_updated', session_id: 's', run_id: 'r', payload: { step } });
store.getState().applyRuntimeEvent(event(first));
store.getState().applyRuntimeEvent(event(first));
store.getState().applyRuntimeEvent(event(second));
store.getState().applyRuntimeEvent(event({ ...first, updated_at: at(1), metadata: {} }));
const reconciled = buildReplyMetrics({ ...reply, steps: store.getState().stepsByRunId.r });
assert.equal(reconciled.inputTokens, 2000);
assert.equal(reconciled.outputTokens, 150);
store.getState().applyRuntimeEvent({ type: 'history_pruned', session_id: 's', payload: { deleted_run_ids: ['r'], deleted_message_ids: [] } });
store.getState().applyRuntimeEvent(event(first));
assert.equal(store.getState().stepsByRunId.r, undefined);

const render = (value) => renderToStaticMarkup(React.createElement(MessageScrollerProvider,
  { autoScroll: true }, React.createElement(ReplyMetrics, { reply: value })));
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const html = render(reply);
  assert.ok(html.includes(i18n.t('runs:metrics.details')));
  assert.ok(html.includes(i18n.t('runs:metrics.estimated')));
  assert.match(html, /2,000|2&#x2C;000/);
  assert.match(html, /30 tok\/s/);
  assert.match(html, /aria-expanded="false"/);
  assert.ok(render(partial).includes(i18n.t('runs:metrics.incomplete')));
  assert.ok(render(paused).includes(i18n.t('runs:metrics.soFar')));
  assert.match(render({ ...reply, steps: [nonstream] }), /—/);
}
console.log('LLM reply accounting, incomplete usage, weighted speeds, event reconciliation and bilingual rendering: ok');
