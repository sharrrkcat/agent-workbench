import assert from 'node:assert/strict';
import { apiMocks, createModuleLoader } from './module-loader.mjs';
import { historyPage } from './history-fixtures.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const { compactCommand, compactUnavailable } = (await load('../src/store/cogita/compactCommand.ts')).exports;
const session = { session_id: 'one', kind: 'ordinary', project_id: null, title: 'one',
  effective: { model_profile_id: 'model', context_policy: { strategy: 'token_budget', history_enabled: true } },
  updated_at: '2026-11-01T00:00:00Z' };
const message = { message_id: 'user', session_id: 'one', role: 'user', parts: [], created_at: '2026-11-01T00:00:01Z' };
const run = { run_id: 'compact', session_id: 'one', kind: 'compaction', persona_id: 'persona', status: 'RUNNING',
  created_at: '2026-11-01T00:00:02Z', updated_at: '2026-11-01T00:00:02Z' };
let rows = [], calls = 0;
api.getSession = async () => session;
api.getHistory = async (_, query) => historyPage([message], rows, query);
api.sendMessage = async () => { throw new Error('Command used the message endpoint'); };
api.createSession = async () => { throw new Error('Command created a draft session'); };
function reset() {
  rows = []; calls = 0;
  store.setState({ ...store.getInitialState(), currentSession: session, sessions: [session], queueTarget: 'one' }, true);
  api.compact = async () => { calls++; rows.push(run); return run; };
}

assert.deepEqual(['', '/', '/com', '/compact', ' /compact ', '/compact extra', 'say /compact', '/compactness']
  .map(compactCommand), ['none', 'prefix', 'prefix', 'compact', 'compact', 'invalid', 'none', 'none']);
reset();
store.getState().setComposerDraftText('/compact');
assert.equal(await store.getState().sendMessage('/compact'), true);
assert.equal(calls, 1);
assert.equal(store.getState().composerDraftText, '');
assert.deepEqual(store.getState().historyWindow.items.map((i) => i.number), [1, null]);
assert.equal(compactUnavailable(store.getState()), 'busy');
assert.equal(store.getState().enqueueMessage('/compact'), false);
assert.equal(store.getState().enqueueMessage('after compaction'), true);
await store.getState().dispatchQueuedMessage();
for (const status of ['FAILED', 'CANCELLED', 'INTERRUPTED']) {
  reset();
  await store.getState().compactContext();
  store.getState().enqueueMessage('wait');
  rows = [{ ...run, status, updated_at: '2026-11-01T00:00:03Z' }];
  store.getState().applyRuntimeEvent({ type: 'run_updated', session_id: 'one', payload: { run: rows[0] } });
  assert.equal(store.getState().messageQueues.one.paused, 'failed');
}
reset();
store.getState().enqueueMessage('queued');
store.getState().setComposerDraftText('/compact');
assert.equal(await store.getState().compactContext(), false);
assert.equal(calls, 0);
assert.equal(store.getState().composerDraftText, '/compact');
reset();
store.setState({ currentSession: null });
assert.equal(await store.getState().sendMessage('/compact'), false);
assert.equal(calls, 0);
reset();
assert.equal(await store.getState().sendMessage('/compact extra'), false);
assert.equal(await store.getState().sendMessage('/compact', [{ id: 'attachment' }]), false);
assert.equal(calls, 0);
reset();
let accept;
api.compact = () => { calls++; return new Promise((resolve) => { accept = resolve; }); };
store.getState().setComposerDraftText('/compact');
const pending = store.getState().compactContext();
assert.equal(await store.getState().compactContext(), false);
assert.equal(calls, 1);
store.getState().setComposerDraftText('new draft');
rows = [run]; accept(run); await pending;
assert.equal(store.getState().composerDraftText, 'new draft');
reset();
api.compact = async () => { throw new Error('Rejected'); };
store.getState().setComposerDraftText('/compact');
assert.equal(await store.getState().compactContext(), false);
assert.equal(store.getState().composerDraftText, '/compact');
assert.equal(store.getState().mutatingHistory, false);
console.log('Manual compaction commands, independent submission, queues, numbering and acceptance: ok');
