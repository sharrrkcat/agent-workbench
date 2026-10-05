import assert from 'node:assert/strict';
import React from 'react';
import { readFileSync } from 'node:fs';
import { createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const load = createModuleLoader();
const { emptyQQRows, refreshQQRows, olderQQRows, buildQQConversation, QQHistoryChanged, unsettledQQMessage } = (await load('../src/components/projects/qqConversation.ts')).exports;
let rows = Array.from({ length: 65 }, (_, n) => ({ id: n + 1, disposition: 'pending' }));
let pageVersion = 0;
const calls = [];
const fetchPage = async (before) => {
  calls.push(before);
  const selected = rows.filter((row) => !before || row.id < before).sort((a, b) => b.id - a.id);
  return { items: selected.slice(0, 50), next_cursor: selected.length > 50 ? selected[49].id : null, history_version: pageVersion };
};
const unsettled = (row) => row.disposition === 'pending';
let window = await refreshQQRows(emptyQQRows(), fetchPage, unsettled);
assert.equal(window.items.length, 50);
assert.equal(window.next_cursor, 16);
window = await olderQQRows(window, fetchPage);
assert.equal(window.items.length, 65);
assert.equal(window.next_cursor, null);
rows = rows.map((row) => ({ ...row, disposition: 'batched' }));
rows.push(...Array.from({ length: 110 }, (_, n) => ({ id: n + 66, disposition: 'pending' })));
window = await refreshQQRows(window, fetchPage, unsettled);
assert.equal(window.items.length, 175, 'A burst spanning several pages must not lose messages');
assert.equal(window.items.find((row) => row.id === 1).disposition, 'batched', 'Loaded old pending records update');
assert.equal(window.next_cursor, null);
assert.equal(new Set(window.items.map((row) => row.id)).size, 175);
const empty = await refreshQQRows(emptyQQRows(), async () => ({ items: [], next_cursor: null, history_version: 0 }), unsettled);
const populated = await refreshQQRows(empty, fetchPage, unsettled);
assert.equal(populated.next_cursor, 126, 'An initially empty session can acquire older history');
await assert.rejects(refreshQQRows(window, async () => { throw new Error('offline'); }, unsettled), /offline/);
assert.equal(window.items.length, 175, 'A failed refresh leaves the saved window intact');
rows = rows.filter((row) => ![1, 40, 174].includes(row.id)); pageVersion++;
window = await refreshQQRows(window, fetchPage, unsettled);
assert.equal(window.items.length, 172, 'A changed version removes deleted records throughout the loaded range');
assert.equal(window.next_cursor, null);
assert.equal(window.items.find((row) => row.id === 41).disposition, 'batched');
await assert.rejects(olderQQRows({ ...window, next_cursor: 40, history_version: 0 }, fetchPage), QQHistoryChanged);
await assert.rejects(refreshQQRows({ ...window, history_version: 0 }, async (before) => {
  const page = await fetchPage(before);
  if (before) page.history_version++;
  return page;
}, unsettled), QQHistoryChanged, 'A mixed-version page sequence cannot resurrect deleted records');

const at = (second) => new Date(Date.parse('2026-10-04T00:00:00Z') + second * 1000).toISOString();
const incoming = (id, sender, second = id) => ({ id, sender_id: sender, sender_name: 'Same display name', timestamp: at(second), text: `Input ${id}`, segments: [{ type: 'text', text: `Input ${id}` }], disposition: 'batched', batch_id: 1 });
const run = { run_id: 'run', created_at: at(4), kind: 'chat', status: 'DONE' };
const batches = [{ id: 1, run_id: 'run' }];
const deliveries = ['pending', 'sending', 'sent', 'failed', 'unknown'].map((status, id) => ({ id, run_id: 'run', status, text: `Reply ${id}` }));
const runs = { run: { run, messages: [{ message_id: 'internal', role: 'assistant', created_at: at(4), parts: [{ id: 'body', type: 'text', text: 'Internal model response' }] }] } };
runs.run.messages.push({ message_id: 'confirmed', role: 'assistant', created_at: at(5), metadata: { qq_delivery_id: 2 },
  parts: [{ id: 'sent', type: 'text', text: 'Confirmed QQ text' }] });
const transcript = buildQQConversation([incoming(1, 'a'), incoming(2, 'a'), incoming(3, 'b'), { ...incoming(5, 'b'), batch_id: null }], batches, deliveries, runs);
assert.deepEqual(transcript.map((item) => item.kind), ['incoming', 'incoming', 'incoming', 'reply', 'incoming']);
assert.deepEqual(transcript.filter((item) => item.kind === 'incoming').map((item) => item.showIdentity), [true, false, true, true]);
assert.equal(transcript[3].reply.answerParts[0].text, 'Internal model response');
assert.equal(transcript[3].reply.messages.length, 1, 'Persisted QQ delivery messages must not duplicate the separate delivery bubbles');
assert.deepEqual(transcript[3].deliveries.map((row) => row.status), ['pending', 'sending', 'sent', 'failed', 'unknown']);
assert.equal(buildQQConversation([], [], deliveries, runs).length, 1, 'Delivery-only history still loads its run');
assert.equal(buildQQConversation([], batches, [], runs).length, 1, 'Runs without QQ replies remain visible');
const prepend = buildQQConversation([incoming(0, 'a'), incoming(1, 'a'), incoming(2, 'a')], [], [], {});
assert.deepEqual(prepend.map((item) => item.showIdentity), [true, false, false]);
const grouping = (messages) => buildQQConversation(messages, [], [], {}).map((item) => item.showIdentity);
assert.deepEqual(grouping([incoming(1, 'a', 0), incoming(2, 'a', 120), incoming(3, 'a', 120.001)]), [true, false, true]);
const fixedWindow = [incoming(1, 'a', 0), incoming(2, 'a', 90), incoming(3, 'a', 180)];
const original = structuredClone(fixedWindow);
assert.deepEqual(grouping(fixedWindow), [true, false, true], 'Grouping uses the first message, not a sliding window');
assert.deepEqual(fixedWindow, original, 'Presentation grouping preserves message timestamps and data');
assert.deepEqual(grouping(fixedWindow.slice(1)), [true, false]);
assert.deepEqual(grouping(fixedWindow), [true, false, true], 'Prepending history recomputes the group start');
assert.deepEqual(grouping([incoming(1, 'a', 0), incoming(2, 'b', 1), incoming(3, 'a', 2)]), [true, true, true]);
console.log('QQ conversation history, statuses, grouping and run projection passed');

for (const disposition of ['batched', 'skipped']) {
  const saved = { ...emptyQQRows(), initialized: true, items: [incoming(60, 'a'), { ...incoming(1, 'a'), disposition, segments: [{ type: 'image', status: 'pending' }] }] };
  const calls = [];
  const refreshed = await refreshQQRows(saved, async (before) => {
    calls.push(before);
    return { items: before ? [{ ...saved.items[1], segments: [{ type: 'image', status: 'ready' }] }] : [saved.items[0]], next_cursor: before ? null : 60, history_version: 0 };
  }, unsettledQQMessage);
  assert.deepEqual(calls, [undefined, 2]);
  assert.equal(refreshed.items[1].segments[0].status, 'ready', 'Settled old messages still refresh pending images');
}

// Exercise asynchronous lifecycle and caching through the real hook with controlled API promises.
let slots = [], cursor = 0, cleanup, timer;
const intervals = { setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval };
globalThis.setInterval = (callback) => { timer = callback; return 1; };
globalThis.clearInterval = () => {};
let runReads = 0, runStatus = 'RUNNING', historyVersion = 0, failMessages = false;
let messageRows = [incoming(1, 'a')], deliveryRows = [], batchRows = [{ id: 1, run_id: 'run', status: 'running' }];
const bindingValue = (paused = false) => ({ paused, busy: runStatus === 'RUNNING', history_version: historyVersion });
let bindingRead = async () => bindingValue(), removeRead;
const api = {
  binding: () => bindingRead(),
  messages: async () => { if (failMessages) throw new Error('offline'); return { items: messageRows, next_cursor: null, history_version: historyVersion }; },
  batches: async () => ({ items: batchRows, next_cursor: null, history_version: historyVersion }),
  deliveries: async () => ({ items: deliveryRows, next_cursor: null, history_version: historyVersion }),
  control: async () => bindingValue(true),
  remove: (...args) => removeRead(...args),
};
const hookLoader = createModuleLoader({
  react: mockModule({ ...React,
    useState(initial) {
      const cell = slots[cursor++] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [cell.value, (value) => { cell.value = typeof value === 'function' ? value(cell.value) : value; }];
    },
    useRef(initial) { return slots[cursor++] ??= { current: initial }; },
    useEffect(effect) {
      const cell = slots[cursor++] ??= { mounted: false };
      if (!cell.mounted) { cell.mounted = true; cleanup = effect(); }
    },
  }),
  [sourceUrl('api/qq.ts')]: mockModule({ qqApi: api }),
  [sourceUrl('api/tools.ts')]: mockModule({ toolsApi: { getToolRun: async () => { runReads++; return { ...runs.run, run: { ...run, status: runStatus } }; } } }),
  [sourceUrl('components/settings/resources/ResourceUI.tsx')]: mockModule({ errorText: (error) => error.message }),
});
try {
  const { useQQConversation } = (await hookLoader('../src/components/projects/useQQConversation.ts')).exports;
  const render = (id = 's') => { cursor = 0; return useQQConversation(id); };
  const settle = () => new Promise(setImmediate);
  render(); await settle();
  assert.equal(render().loading, false);
  assert.equal(render().messages.items.length, 1);
  runStatus = 'DONE'; await render().refresh();
  assert.equal(render().runs.run.run.status, 'DONE');
  const cachedReads = runReads;
  await render().refresh();
  assert.equal(runReads, cachedReads, 'Completed runs are cached across refreshes');
  failMessages = true; await render().refresh();
  assert.equal(render().error, 'offline');
  assert.equal(render().messages.items.length, 1);
  failMessages = false; await render().refresh();
  assert.equal(render().error, '');

  messageRows = [incoming(2, 'a'), incoming(1, 'a')];
  deliveryRows = [{ ...deliveries[2], id: 10 }, { ...deliveries[2], id: 11 }];
  await render().refresh();
  removeRead = async () => { throw new Error('SESSION_BUSY'); };
  await render().remove({ kind: 'message', id: 1 });
  assert.equal(render().messages.items.length, 2, 'Failed deletion preserves messages');
  await settle();
  removeRead = async (_id, target) => {
    if (target.kind === 'message') messageRows = messageRows.filter((row) => row.id !== target.id);
    if (target.kind === 'delivery') deliveryRows = deliveryRows.filter((row) => row.id !== target.id);
    if (target.kind === 'reply') { batchRows = [{ id: 1, run_id: null, status: 'done' }]; deliveryRows = []; }
    return { deleted_message_ids: [], deleted_run_ids: target.kind === 'reply' ? ['run'] : [],
      deleted_qq_message_ids: target.kind === 'message' ? [target.id] : [],
      deleted_qq_delivery_ids: target.kind === 'delivery' ? [target.id] : target.kind === 'reply' ? [11] : [],
      history_version: ++historyVersion };
  };
  let resolveBeforeDeletion;
  const beforeDeletion = bindingValue();
  bindingRead = () => new Promise((resolve) => { resolveBeforeDeletion = resolve; });
  const oldPoll = render().refresh();
  await render().remove({ kind: 'message', id: 1 });
  resolveBeforeDeletion(beforeDeletion); await oldPoll;
  assert.deepEqual(render().messages.items.map((row) => row.id), [2], 'A pre-delete poll cannot restore the removed bubble');
  assert.equal(render().messages.items[0].disposition, 'batched');
  bindingRead = async () => bindingValue(); await render().refresh();
  await render().remove({ kind: 'delivery', id: 10 }); await settle();
  assert.deepEqual(render().deliveries.items.map((row) => row.id), [11]);
  assert.equal(render().deliveries.items[0].status, 'sent');
  assert.ok(render().runs.run, 'Deleting a delivery keeps the model reply');
  await render().remove({ kind: 'reply', id: 'run' }); await settle();
  assert.equal(render().deliveries.items.length, 0);
  assert.equal(Object.keys(render().runs).length, 0);
  assert.equal(render().batches.items[0].run_id, null);
  assert.equal(render().messages.items.length, 1, 'Deleting a reply preserves its remaining input');
  let resolveRead;
  bindingRead = () => new Promise((resolve) => { resolveRead = resolve; });
  const inflight = render().refresh();
  await render().control('pause');
  assert.equal(render().binding.paused, true);
  resolveRead(bindingValue()); await inflight;
  assert.equal(render().binding.paused, true, 'A pre-control poll cannot overwrite the control response');
  const oldRead = render().refresh();
  const resolveOld = resolveRead;
  cleanup();
  slots = []; bindingRead = async () => bindingValue(true);
  render('other'); await settle();
  resolveOld(bindingValue()); await oldRead;
  assert.equal(render('other').binding.paused, true, 'Unmounted session responses do not affect the next session');
  assert.equal(typeof timer, 'function');
  cleanup();
} finally {
  Object.assign(globalThis, intervals);
}
console.log('QQ refresh caching, retry, control races and session isolation passed');

// Use the editor's actual textarea handlers and retained hook state across locale changes.
const prompts = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale,
  JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8')).qq.defaultPrompt]));
let editorCells = [], editorCursor = 0, editorLocale = 'en', editorCleanups = [];
const savedWindow = globalThis.window;
globalThis.window = { addEventListener() {}, removeEventListener() {} };
const storeHook = (state) => Object.assign((select) => select(state), { getState: () => ({ reload: async () => {} }) });
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
  [sourceUrl('store/useProjectsStore.ts')]: mockModule({ useProjectsStore: storeHook({}) }),
  [sourceUrl('store/useCogitaStore.ts')]: mockModule({ useCogitaStore: storeHook({}) }),
});
try {
  const { QQBotEditor, qqInput } = (await editorLoader('../src/components/projects/QQBotEditor.tsx')).exports;
  assert.equal(qqInput().image_input_enabled, false);
  assert.equal(qqInput().icebreaker_enabled, false);
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
console.log('QQ editor defaults, edits and cleared prompts survive language changes; saved projects retain their prompts');
