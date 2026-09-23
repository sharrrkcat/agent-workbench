import assert from 'node:assert/strict';
import { apiMocks, createModuleLoader } from './module-loader.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { useWorkbenchStore: store } = (await load('../src/store/useWorkbenchStore.ts')).exports;
const session = (id) => ({ session_id: id, title: id, effective: {}, updated_at: '2026-09-23T00:00:00Z' });
const first = session('first'),
  second = session('second'),
  third = session('third'),
  replacement = session('replacement');
const records = new Map([first, second, third, replacement].map((item) => [item.session_id, item]));
const messages = [{ message_id: 'message', session_id: 'first', role: 'user', parts: [] }];
const runs = [{ run_id: 'run', session_id: 'first', status: 'DONE' }];

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function reset(sessions = [first, second, third]) {
  store.setState(store.getInitialState(), true);
  store.setState({
    sessions,
    currentSession: first,
    messages,
    runs,
    stepsByRunId: { run: [{ step_id: 'step' }] },
    sessionEpoch: 7,
    sessionVersion: 3,
    sourceMessageId: 'message',
    composerDraftText: 'Retained draft',
  });
  api.deleteSession = async () => {};
  api.createSession = async () => replacement;
  api.getSession = async (id) => records.get(id);
  api.listMessages = async () => [];
  api.listRuns = async () => [];
}

reset();
await store.getState().deleteSession('second');
assert.deepEqual(store.getState().sessions, [first, third]);
assert.equal(store.getState().currentSession, first);
assert.equal(store.getState().messages, messages);
assert.equal(store.getState().runs, runs);
assert.equal(store.getState().sessionEpoch, 7);
assert.equal(store.getState().sourceMessageId, 'message');
assert.equal(store.getState().composerDraftText, 'Retained draft');

reset();
await store.getState().deleteSession('first');
assert.equal(store.getState().currentSession, second);
assert.deepEqual(store.getState().sessions, [second, third]);
assert.deepEqual(store.getState().messages, []);
assert.deepEqual(store.getState().runs, []);
assert.equal(store.getState().sourceMessageId, null);
assert.equal(store.getState().sessionEpoch, 8);

reset([first]);
await store.getState().deleteSession('first');
assert.deepEqual(store.getState().sessions, [replacement]);
assert.equal(store.getState().currentSession, replacement);

reset();
const delayedDelete = deferred();
api.deleteSession = () => delayedDelete.promise;
const deleting = store.getState().deleteSession('first');
await store.getState().selectSession('third');
const selected = store.getState();
delayedDelete.resolve();
await deleting;
assert.equal(store.getState().currentSession, third);
assert.equal(store.getState().messages, selected.messages);
assert.equal(store.getState().sessionEpoch, selected.sessionEpoch);
assert.deepEqual(store.getState().sessions, [second, third]);

reset([first]);
const delayedCreate = deferred(),
  creating = deferred();
api.createSession = () => {
  creating.resolve();
  return delayedCreate.promise;
};
const deletingLast = store.getState().deleteSession('first');
await creating.promise;
store.setState({ sessions: [first, third] });
await store.getState().selectSession('third');
const changed = store.getState();
delayedCreate.resolve(replacement);
await deletingLast;
assert.equal(store.getState().currentSession, third);
assert.equal(store.getState().messages, changed.messages);
assert.equal(store.getState().sessionEpoch, changed.sessionEpoch);
assert.deepEqual(store.getState().sessions, [third, replacement]);

reset();
const oldList = deferred();
api.listSessions = () => oldList.promise;
const reloading = store.getState().reloadSessions();
await store.getState().deleteSession('second');
oldList.resolve([first, second, third]);
await reloading;
assert.deepEqual(
  store.getState().sessions,
  [first, third],
  'A stale session list cannot restore a deleted row',
);

reset();
const beforeFailure = store.getState();
api.deleteSession = async () => {
  throw new Error('Deletion failed');
};
await store.getState().deleteSession('first');
assert.equal(store.getState().sessions, beforeFailure.sessions);
assert.equal(store.getState().currentSession, beforeFailure.currentSession);
assert.equal(store.getState().messages, beforeFailure.messages);
assert.equal(store.getState().sessionEpoch, beforeFailure.sessionEpoch);
assert.match(store.getState().error, /Deletion failed/);
console.log(
  'Session deletion preserves other chats, handles replacement and ignores stale selection/list responses: ok',
);
