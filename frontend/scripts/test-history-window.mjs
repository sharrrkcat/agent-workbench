import assert from 'node:assert/strict';
import { apiMocks, createModuleLoader } from './module-loader.mjs';
import { historyPage } from './history-fixtures.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const session = { session_id: 'history', kind: 'ordinary', project_id: null, updated_at: '2026-01-01T00:00:00Z' };
const messages = Array.from({ length: 650 }, (_, i) => ({ message_id: `m-${String(i).padStart(4, '0')}`, session_id: 'history',
  role: 'user', created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, i)).toISOString(), parts: [{ type: 'text', id: 't', text: String(i) }] }));
api.getSession = async () => session;
api.getHistory = async (_, query) => historyPage(messages, [], query);
store.setState({ ...store.getInitialState(), currentSession: session, sessions: [session] }, true);
await store.getState().loadHistory('latest');
assert.equal(store.getState().messages.length, 50);
assert.equal(store.getState().historyWindow.items.at(-1).number, 650);
for (let i = 0; i < 5; i++) await store.getState().loadHistory('before');
assert.equal(store.getState().messages.length, 200);
assert.equal(store.getState().historyWindow.items[0].number, 351);
assert.equal(store.getState().historyWindow.has_after, true);
assert.equal(store.getState().historyFollowing, false);
const ids = store.getState().messages.map((m) => m.message_id);
store.getState().applyRuntimeEvent({ type: 'message_started', session_id: 'history', message_id: 'outside', run_id: 'outside-run',
  payload: { message: { ...messages[0], message_id: 'outside', role: 'assistant', run_id: 'outside-run' } } });
assert.deepEqual(store.getState().messages.map((m) => m.message_id), ids);
await store.getState().loadHistory('after');
assert.equal(store.getState().messages.length, 200);
await store.getState().loadHistory('latest');
assert.equal(store.getState().messages.length, 50);
assert.equal(store.getState().historyFollowing, true);

const anchor = store.getState().historyWindow.items[10].cursor;
let release;
const pending = new Promise((resolve) => { release = resolve; });
api.getHistory = (_, query) => query.before ? pending : Promise.resolve(historyPage(messages, [], query));
const earlier = store.getState().loadHistory('before');
await store.getState().loadHistory('around', anchor);
const selected = store.getState().historyWindow;
release(historyPage(messages.slice(0, 200), []));
await earlier;
assert.equal(store.getState().historyWindow, selected);
assert.equal(store.getState().historyLoading, false);
console.log('History windows: global numbers, 200-item retention, off-window events and late page rejection: ok');
