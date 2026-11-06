import assert from 'node:assert/strict';
import React from 'react';
import { readFileSync } from 'node:fs';
import { createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const { mergeQQHistory, pruneQQHistory, buildQQConversation, QQHistoryChanged } =
  (await createModuleLoader()('../src/components/characters/qqConversation.ts')).exports;
const at = (n) => new Date(Date.UTC(2026, 0, 1) + n * 1000).toISOString();
const input = (id, sender = 'a') => ({ id: `qq-message-${id}`, cursor: `c${id}`, created_at: at(id), kind: 'incoming',
  message: { id, sender_id: sender, sender_name: sender, timestamp: at(id), text: `Input ${id}`, segments: [], disposition: 'batched', batch_id: 1 } });
const run = { run_id: 'run', created_at: at(5), updated_at: at(6), session_id: 's', kind: 'chat', status: 'DONE', steps: [] };
const delivery = { id: 1, run_id: 'run', status: 'sent', text: 'QQ reply' };
const reply = { id: 'qq-run-run', cursor: 'r', created_at: at(5), kind: 'reply', run, deliveries: [delivery] };
const binding = { history_version: 0, paused: false, busy: false };
const page = (items, values = {}) => ({ items, binding, history_version: 0, before_cursor: items[0]?.cursor ?? null,
  after_cursor: items.at(-1)?.cursor ?? null, has_before: true, has_after: false, active_run: null, latest_run: run, ...values });
const all = Array.from({ length: 250 }, (_, i) => input(i + 1));
let window = page(all.slice(200));
for (const start of [150, 100, 50, 0]) window = mergeQQHistory(window, page(all.slice(start, start + 50), { has_before: start > 0 }), 'before');
assert.equal(window.items.length, 200);
assert.equal(window.items[0].message.id, 1);
assert.equal(window.items.at(-1).message.id, 200);
assert.equal(window.has_after, true);
window = mergeQQHistory(window, page(all.slice(200)), 'after');
assert.equal(window.items[0].message.id, 51);
assert.equal(window.has_before, true);
assert.throws(() => mergeQQHistory(window, page([], { history_version: 1 }), 'before'), QQHistoryChanged);
const earlierProgram = { kind: 'program', id: 'qq-delivery-1', cursor: 'p', created_at: at(1), delivery };
assert.deepEqual(mergeQQHistory(page([earlierProgram]), page([input(1)]), 'after').items.map((item) => item.kind),
  ['program', 'incoming'], 'Rounded display timestamps must not reorder authoritative adjacent pages');
const detail = { run, messages: [{ message_id: 'private', role: 'assistant', created_at: at(5),
  parts: [{ id: 'text', type: 'text', text: 'Internal work' }] }, { message_id: 'sent', role: 'assistant', created_at: at(6),
  metadata: { qq_delivery_id: 1 }, parts: [{ id: 'sent-text', type: 'text', text: 'QQ reply' }] }] };
const built = buildQQConversation([input(1), input(2), input(3, 'b'), reply, input(6, 'b')], { run: detail });
assert.deepEqual(built.filter(i => i.kind === 'incoming').map(i => i.showIdentity), [true, false, true, true]);
assert.deepEqual(built[3].reply.answerParts, []);
assert.equal(built[3].reply.process[0].part.text, 'Internal work');
assert.equal(built[3].reply.messages.length, 1);
const pruned = pruneQQHistory(page([input(1), reply]), { deleted_run_ids: [], deleted_message_ids: [],
  deleted_qq_message_ids: [1], deleted_qq_delivery_ids: [1], history_version: 1 });
assert.equal(pruned.items.length, 1);
assert.deepEqual(pruned.items[0].deliveries, []);
console.log('QQ unified window, eviction, grouping and internal processing: ok');

let cells = [], cursor = 0, effects = [], tick;
let historyReads = 0, detailReads = 0, refreshVersion = 0;
let response = page([input(1), input(2), reply]);
let readHistory = async () => response;
let readDetail = async () => detail;
const timers = { setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval };
globalThis.setInterval = callback => { tick = callback; return 1; };
globalThis.clearInterval = () => {};
const api = {
  history: (...args) => { historyReads++; return readHistory(...args); },
  control: async () => { response = { ...response, binding: { ...binding, paused: true } }; return response.binding; },
  remove: async () => {
    response = page([input(2), reply], { history_version: 1, binding: { ...binding, history_version: 1 } });
    return { deleted_run_ids: [], deleted_message_ids: [], deleted_qq_message_ids: [1], deleted_qq_delivery_ids: [], history_version: 1 };
  },
};
const loader = createModuleLoader({
  react: mockModule({ ...React,
    useState(initial) {
      const cell = cells[cursor++] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [cell.value, value => { cell.value = typeof value === 'function' ? value(cell.value) : value; }];
    },
    useRef(initial) { return cells[cursor++] ??= { current: initial }; },
    useEffect(effect, deps) {
      const cell = cells[cursor++] ??= {};
      if (!cell.deps || deps.some((value, i) => value !== cell.deps[i])) {
        cell.deps = deps;
        effects.push(() => { cell.cleanup?.(); cell.cleanup = effect(); });
      }
    },
  }),
  [sourceUrl('api/qq.ts')]: mockModule({ qqApi: api }),
  [sourceUrl('api/tools.ts')]: mockModule({ toolsApi: { getToolRun: (...args) => { detailReads++; return readDetail(...args); } } }),
  [sourceUrl('store/useCogitaStore.ts')]: mockModule({ useCogitaStore: select => select({ qqRefreshVersion: refreshVersion }) }),
  [sourceUrl('components/settings/resources/ResourceUI.tsx')]: mockModule({ errorText: error => error.message }),
});
const settle = () => new Promise(setImmediate);
const unmount = () => { for (const cell of cells) cell.cleanup?.(); };
try {
  const { useQQConversation } = (await loader('../src/components/characters/useQQConversation.ts')).exports;
  const render = () => { cursor = 0; const result = useQQConversation('s'); const pending = effects; effects = []; pending.forEach(effect => effect()); return result; };
  render(); await settle();
  assert.equal(render().loading, false);
  assert.equal(historyReads, 1);
  assert.equal(detailReads, 0, 'First paint never fans out to run details');
  let completeDetail;
  readDetail = () => new Promise(resolve => { completeDetail = resolve; });
  render().setProcessing('run', true);
  assert.equal(detailReads, 1);
  assert.equal(render().page.items.length, 3, 'Slow processing does not hide QQ messages');
  completeDetail(detail); await settle();
  assert.equal(render().details.run.data, detail);
  await render().refresh();
  assert.equal(detailReads, 1, 'Settled details remain cached');
  await render().remove({ kind: 'message', id: 1 }); await settle();
  assert.equal(render().page.items.filter(i => i.kind === 'incoming').length, 1);
  render().setProcessing('run', false);
  readDetail = async () => detail;
  await render().control('pause'); await settle();
  assert.equal(render().page.binding.paused, true);
  const prior = historyReads;
  refreshVersion++; render(); await settle();
  assert.equal(historyReads, prior + 1, 'Reconnect invalidation uses one QQ read');

  // Explicit navigation cancels an in-flight poll, then performs the requested page read.
  let pendingSignal;
  readHistory = (_id, query, signal) => {
    if (query.before) return Promise.resolve(page([input(0)], { history_version: 1, has_before: false }));
    pendingSignal = signal;
    return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true }));
  };
  const polling = render().refresh();
  const older = render().loadHistory('before');
  await Promise.all([polling, older]);
  assert.equal(pendingSignal.aborted, true);
  assert.equal(render().page.items[0].message.id, 0);
  assert.equal(render().error, '');
  unmount();

  // A response which ignores abort still cannot start work after unmount.
  cells = []; let finish, signal;
  readHistory = (_id, _query, receivedSignal) => { signal = receivedSignal; return new Promise(resolve => { finish = resolve; }); };
  const readsBefore = detailReads;
  render(); unmount();
  assert.equal(signal.aborted, true);
  finish(response); await settle();
  assert.equal(detailReads, readsBefore);
  assert.equal(typeof tick, 'function');

  cells = [];
  let timeline = all.slice(0, 1), version = 0;
  const queries = [];
  readHistory = async (_id, query) => {
    queries.push(query);
    const limit = query.limit ?? 50;
    const index = (value) => timeline.findIndex((item) => item.cursor === value);
    let start = Math.max(0, timeline.length - limit);
    if (query.before) start = Math.max(0, index(query.before) - limit);
    if (query.after) start = index(query.after) + 1;
    if (query.around) start = Math.max(0, index(query.around) - Math.floor(limit / 2));
    return page(timeline.slice(start, start + limit), { history_version: version, has_before: start > 0, has_after: start + limit < timeline.length });
  };
  render(); await settle();
  timeline = all.slice(0, 2);
  await render().refresh();
  assert.deepEqual(render().page.items.map((item) => item.message.id), [1, 2], 'A short conversation grows instead of retaining its initial page size');
  timeline = [...all];
  await render().loadHistory('latest');
  for (let i = 0; i < 3; i++) await render().loadHistory('before');
  const retained = render().page.items.map((item) => item.id);
  render().setAnchor('c100');
  timeline[69] = { ...input(70), message: { ...input(70).message, text: 'Old media updated' } };
  timeline.push(input(251));
  await render().refresh();
  assert.deepEqual(render().page.items.map((item) => item.id), retained, 'Polling preserves the entire 200-item historical window and excludes new tail arrivals');
  assert.equal(render().page.items.find((item) => item.message.id === 70).message.text, 'Old media updated');
  assert.equal(render().page.has_after, true);
  version++;
  timeline = timeline.filter((item) => item.message.id !== 120);
  await render().refresh();
  assert.equal(render().page.history_version, version);
  assert.ok(render().page.items.some((item) => item.message.id === 100));
  assert.ok(!render().page.items.some((item) => item.message.id === 120));
  assert.ok(queries.every((query) => (query.limit ?? 50) <= 100));
  unmount();
} finally { unmount(); Object.assign(globalThis, timers); }
console.log('QQ lazy details, cancellation, mutation and reconnect isolation: ok');

// Use the editor's actual textarea handlers and retained hook state across locale changes.
const prompts = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale,
  JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8')).qq.defaultPrompt]));
let editorCells = [], editorCursor = 0, editorLocale = 'en', editorCleanups = [];
const savedWindow = globalThis.window;
globalThis.window = { addEventListener() {}, removeEventListener() {} };
const storeHook = (state) => Object.assign((select) => select(state), { getState: () => ({ reload: async () => {}, reloadProfiles: async () => {}, reloadProviders: async () => {} }) });
const editorLoader = createModuleLoader({
  react: mockModule({ ...React,
    useId: () => 'qq-editor', useCallback: (callback) => callback,
    useState(initial) {
      const cell = editorCells[editorCursor++] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [cell.value, (value) => { cell.value = typeof value === 'function' ? value(cell.value) : value; }];
    },
    useRef(initial) { return editorCells[editorCursor++] ??= { current: initial }; },
    useEffect(effect) {
      const cell = editorCells[editorCursor++] ??= { mounted: false };
      if (!cell.mounted) { cell.mounted = true; const cleanup = effect(); if (cleanup) editorCleanups.push(cleanup); }
    },
  }),
  'react-i18next': mockModule({ useTranslation: () => ({ t: (key) => key === 'qq.defaultPrompt' ? prompts[editorLocale] : key }) }),
  [sourceUrl('hooks/useConfirmDialog.tsx')]: mockModule({ useConfirmDialog: () => ({ confirm: async () => true, confirmation: null }) }),
  [sourceUrl('store/useModelsStore.ts')]: mockModule({ useModelsStore: storeHook({ profiles: [] }) }),
  [sourceUrl('store/usePersonasStore.ts')]: mockModule({ usePersonasStore: storeHook({ personas: [] }) }),
  [sourceUrl('store/useCharactersStore.ts')]: mockModule({ useCharactersStore: storeHook({}) }),
  [sourceUrl('store/useCogitaStore.ts')]: mockModule({ useCogitaStore: storeHook({}) }),
});
try {
  const { QQBotEditor, qqInput } = (await editorLoader('../src/components/characters/QQBotEditor.tsx')).exports;
  assert.equal(qqInput().image_input_enabled, false);
  assert.equal(qqInput().icebreaker_enabled, false);
  assert.equal(qqInput().admin_qq, null);
  assert.equal(qqInput({ ...qqInput(), admin_qq: '9999' }).admin_qq, '9999');
  assert.deepEqual([qqInput().icebreaker_cold_seconds, qqInput().icebreaker_wait_seconds, qqInput().icebreaker_cooldown_seconds], [7200, 120, 10800]);
  assert.equal(qqInput({ ...qqInput(), image_input_enabled: true }).image_input_enabled, true);
  const children = (node) => Array.isArray(node) ? node.flatMap(children) : React.isValidElement(node)
    ? [node, ...children(node.props.children)] : [];
  const renderEditor = () => {
    editorCursor = 0;
    return QQBotEditor({ onSaved() {}, onLeaveGuardChange() {} });
  };
  const promptField = () => children(renderEditor()).find((node) => node.props.id === 'qq-editor-prompt');
  for (const locale of ['en', 'zh-CN']) {
    editorLocale = locale;
    renderEditor(); await new Promise(setImmediate);
    const imageSwitch = () => children(renderEditor()).find((node) => node.props.id === 'qq-editor-images');
    assert.equal(imageSwitch().props.checked, false);
    imageSwitch().props.onCheckedChange(true);
    assert.equal(imageSwitch().props.checked, true);
    const icebreakerSwitch = () => children(renderEditor()).find((node) => node.props.id === 'qq-editor-icebreaker');
    const waitField = () => children(renderEditor()).find((node) => node.props.id === 'qq-editor-wait');
    assert.equal(waitField(), undefined);
    icebreakerSwitch().props.onCheckedChange(true);
    waitField().props.onChange({ target: { value: '7' } });
    icebreakerSwitch().props.onCheckedChange(false);
    assert.equal(waitField(), undefined);
    icebreakerSwitch().props.onCheckedChange(true);
    assert.equal(waitField().props.value, 7);
    assert.equal(promptField().props.value, prompts[locale]);
    editorLocale = locale === 'en' ? 'zh-CN' : 'en';
    assert.equal(promptField().props.value, prompts[locale], 'A locale switch preserves the opening default');
    promptField().props.onChange({ target: { value: 'Edited prompt' } });
    editorLocale = locale;
    assert.equal(promptField().props.value, 'Edited prompt');
    promptField().props.onChange({ target: { value: '' } });
    editorLocale = locale === 'en' ? 'zh-CN' : 'en';
    assert.equal(promptField().props.value, '', 'A cleared draft remains empty after a locale switch');
    for (const cleanup of editorCleanups) cleanup();
    editorCells = []; editorCleanups = [];
  }
  for (const system_prompt of ['', 'Saved prompt']) {
    const existing = { ...qqInput(undefined, prompts.en), id: 'existing', system_prompt };
    assert.equal(qqInput(existing, prompts['zh-CN']).system_prompt, system_prompt);
  }
} finally {
  globalThis.window = savedWindow;
}
console.log('QQ editor defaults, edits and cleared prompts survive language changes; saved characters retain their prompts');
