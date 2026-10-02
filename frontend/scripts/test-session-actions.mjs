import assert from 'node:assert/strict';
import { apiMocks, createModuleLoader } from './module-loader.mjs';
import { mockDraftCatalogs } from './draft-fixtures.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const session = (id) => ({ session_id: id, kind: 'ordinary', project_id: null, title: id, effective: {}, updated_at: '2026-09-23T00:00:00Z' });
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
  mockDraftCatalogs(api);
  store.setState(store.getInitialState(), true);
  store.setState({
    sessions,
    currentSession: first,
    messages,
    runs,
    stepsByRunId: { run: [{ step_id: 'step' }] },
    sessionEpoch: 7,
    sessionVersion: 3,
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
assert.equal(store.getState().composerDraftText, 'Retained draft');

reset();
await store.getState().deleteSession('first');
assert.equal(store.getState().currentSession, second);
assert.deepEqual(store.getState().sessions, [second, third]);
assert.deepEqual(store.getState().messages, []);
assert.deepEqual(store.getState().runs, []);
assert.equal(store.getState().sessionEpoch, 8);

reset([first]);
await store.getState().deleteSession('first');
assert.deepEqual(store.getState().sessions, []);
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().chatDraft.kind, 'ordinary');

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
const delayedCatalog = deferred(),
  creating = deferred();
api.listTools = () => {
  creating.resolve();
  return delayedCatalog.promise;
};
const deletingLast = store.getState().deleteSession('first');
await creating.promise;
store.setState({ sessions: [third] });
await store.getState().selectSession('third');
const changed = store.getState();
delayedCatalog.resolve([]);
await deletingLast;
assert.equal(store.getState().currentSession, third);
assert.equal(store.getState().messages, changed.messages);
assert.equal(store.getState().sessionEpoch, changed.sessionEpoch);
assert.deepEqual(store.getState().sessions, [third]);

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
  'Session deletion preserves other chats, opens a draft and ignores stale selection/list responses: ok',
);

reset();
let reads = 0;
const history = deferred();
api.listMessages = () => { reads++; return history.promise; };
await store.getState().selectSession('first');
assert.equal(reads, 0, 'Clicking the current session preserves its draft and history');
assert.equal(store.getState().composerDraftText, 'Retained draft');
const selecting = store.getState().selectSession('second');
const epoch = store.getState().sessionEpoch;
assert.equal(store.getState().currentSession, second);
assert.equal(store.getState().sessionLoad.status, 'loading');
assert.deepEqual(store.getState().messages, []);
assert.equal(store.getState().composerDraftText, '');
await store.getState().selectSession('second');
await store.getState().activateLocation(null);
await store.getState().refreshCurrent();
assert.equal(reads, 1, 'Repeated selection and background refresh cannot duplicate a pending load');
assert.equal(store.getState().sessionEpoch, epoch);
api.sendMessage = async () => { throw new Error('Must not send while loading'); };
assert.equal(await store.getState().sendMessage('blocked'), false);
history.resolve([]);
await selecting;
assert.equal(store.getState().sessionLoad.status, 'ready');

store.setState({ composerDraftText: 'Keep this' });
await store.getState().selectSession('second');
assert.equal(reads, 1);
assert.equal(store.getState().composerDraftText, 'Keep this');

reset();
api.listRuns = async () => { throw new Error('History unavailable'); };
await store.getState().selectSession('second');
assert.equal(store.getState().currentSession, second);
assert.equal(store.getState().sessionLoad.status, 'error');
assert.match(store.getState().sessionLoad.error, /History unavailable/);
const failedEpoch = store.getState().sessionEpoch;
await store.getState().selectSession('second');
assert.equal(store.getState().sessionLoad.status, 'error', 'Only explicit retry restarts a failed load');
api.listRuns = async () => [];
await store.getState().retrySession();
assert.equal(store.getState().sessionLoad.status, 'ready');
assert.equal(store.getState().sessionEpoch, failedEpoch, 'Retry does not reset the conversation identity');
api.listMessages = async () => { throw new Error('Background refresh failed'); };
await store.getState().refreshCurrent();
assert.equal(store.getState().sessionLoad.status, 'ready', 'Background errors do not replace the conversation');
assert.match(store.getState().error, /Background refresh failed/);

for (const destination of ['third', 'first']) {
  reset();
  const oldHistory = deferred();
  api.listMessages = (id) => id === 'second' ? oldHistory.promise : Promise.resolve([]);
  const oldSelection = store.getState().selectSession('second');
  await store.getState().selectSession(destination);
  const currentEpoch = store.getState().sessionEpoch;
  oldHistory.resolve([{ message_id: 'late', session_id: 'second' }]);
  await oldSelection;
  store.getState().applyRuntimeEvent({ type: 'message_updated', session_id: 'second',
    payload: { message: { message_id: 'late-event', session_id: 'second' } } });
  assert.equal(store.getState().currentSession.session_id, destination);
  assert.equal(store.getState().sessionEpoch, currentEpoch);
  assert.deepEqual(store.getState().messages, []);
}

reset();
const earlierVisit = deferred();
let visits = 0;
api.listMessages = (id) => id === 'second' && ++visits === 1 ? earlierVisit.promise : Promise.resolve([]);
const earlierSelection = store.getState().selectSession('second');
await store.getState().selectSession('third');
await store.getState().selectSession('second');
earlierVisit.resolve([{ message_id: 'earlier-visit', session_id: 'second' }]);
await earlierSelection;
assert.deepEqual(store.getState().messages, [], 'Returning to the same id rejects the earlier visit');
console.log('Session loading, deduplication, retry, background refresh and navigation races: ok');

reset();
const lateDetails = deferred();
api.getSession = () => lateDetails.promise;
api.listMessages = async () => { throw new Error('Messages failed before details'); };
await store.getState().selectSession('uncached');
assert.equal(store.getState().sessionLoad.status, 'error');
assert.equal(store.getState().currentSession, null);
api.getSession = async () => ({ ...replacement, session_id: 'uncached', title: 'Retried details' });
api.listMessages = async () => [];
await store.getState().retrySession();
lateDetails.resolve({ ...replacement, session_id: 'uncached', title: 'Stale details' });
await Promise.resolve();
assert.equal(store.getState().currentSession.title, 'Retried details');
assert.equal(store.getState().sessionLoad.status, 'ready');


reset();
api.updateSession = async (id, patch) => ({ ...first, ...patch });
assert.equal(await store.getState().updateSession({ harness_enabled: false, tools_allowed: [] }), true);
assert.equal(store.getState().currentSession.harness_enabled, false);
assert.deepEqual(store.getState().currentSession.tools_allowed, []);
api.updateSession = async () => { throw new Error('Configuration save failed'); };
assert.equal(await store.getState().updateSession({ harness_enabled: true }), false);
assert.equal(store.getState().currentSession.harness_enabled, false);
assert.match(store.getState().error, /Configuration save failed/);

reset();
const pendingConfiguration = deferred();
api.updateSession = () => pendingConfiguration.promise;
const savingConfiguration = store.getState().updateSession({ harness_enabled: true });
await store.getState().selectSession('third');
pendingConfiguration.resolve({ ...first, harness_enabled: true });
assert.equal(await savingConfiguration, false);
assert.equal(store.getState().currentSession.session_id, 'third');

reset();
await store.getState().startDraft();
assert.equal(await store.getState().updateSession({ harness_enabled: true, tools_allowed: [] }), true);
assert.equal(store.getState().chatDraft.harness_enabled, true);
assert.deepEqual(store.getState().chatDraft.tools_allowed, []);
store.setState({ sending: true });
assert.equal(await store.getState().updateSession({ harness_enabled: false }), false);
assert.equal(store.getState().chatDraft.harness_enabled, true);
