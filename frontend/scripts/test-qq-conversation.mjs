import assert from 'node:assert/strict';
import React from 'react';
import { createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const load = createModuleLoader();
const { emptyQQRows, refreshQQRows, olderQQRows, buildQQConversation } = (await load('../src/components/projects/qqConversation.ts')).exports;
let rows = Array.from({ length: 65 }, (_, n) => ({ id: n + 1, disposition: 'pending' }));
const calls = [];
const fetchPage = async (before) => {
  calls.push(before);
  const selected = rows.filter((row) => !before || row.id < before).sort((a, b) => b.id - a.id);
  return { items: selected.slice(0, 50), next_cursor: selected.length > 50 ? selected[49].id : null };
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
const empty = await refreshQQRows(emptyQQRows(), async () => ({ items: [], next_cursor: null }), unsettled);
const populated = await refreshQQRows(empty, fetchPage, unsettled);
assert.equal(populated.next_cursor, 126, 'An initially empty session can acquire older history');
await assert.rejects(refreshQQRows(window, async () => { throw new Error('offline'); }, unsettled), /offline/);
assert.equal(window.items.length, 175, 'A failed refresh leaves the saved window intact');

const at = (second) => new Date(Date.parse('2026-10-04T00:00:00Z') + second * 1000).toISOString();
const incoming = (id, sender, second = id) => ({ id, sender_id: sender, sender_name: 'Same display name', timestamp: at(second), text: `Input ${id}`, disposition: 'batched', batch_id: 1 });
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

// Exercise asynchronous lifecycle and caching through the real hook with controlled API promises.
let slots = [], cursor = 0, cleanup, timer;
const intervals = { setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval };
globalThis.setInterval = (callback) => { timer = callback; return 1; };
globalThis.clearInterval = () => {};
let runReads = 0, runStatus = 'RUNNING', bindingRead = async () => ({ paused: false }), failMessages = false;
const api = {
  binding: () => bindingRead(),
  messages: async () => { if (failMessages) throw new Error('offline'); return { items: [incoming(1, 'a')], next_cursor: null }; },
  batches: async () => ({ items: [{ id: 1, run_id: 'run', status: 'running' }], next_cursor: null }),
  deliveries: async () => ({ items: [], next_cursor: null }),
  control: async () => ({ paused: true }),
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
  let resolveRead;
  bindingRead = () => new Promise((resolve) => { resolveRead = resolve; });
  const inflight = render().refresh();
  await render().control('pause');
  assert.equal(render().binding.paused, true);
  resolveRead({ paused: false }); await inflight;
  assert.equal(render().binding.paused, true, 'A pre-control poll cannot overwrite the control response');
  const oldRead = render().refresh();
  const resolveOld = resolveRead;
  cleanup();
  slots = []; bindingRead = async () => ({ paused: true });
  render('other'); await settle();
  resolveOld({ paused: false }); await oldRead;
  assert.equal(render('other').binding.paused, true, 'Unmounted session responses do not affect the next session');
  assert.equal(typeof timer, 'function');
  cleanup();
} finally {
  Object.assign(globalThis, intervals);
}
console.log('QQ refresh caching, retry, control races and session isolation passed');
