import assert from 'node:assert/strict';
import { apiMocks, createModuleLoader } from './module-loader.mjs';
import { mockDraftCatalogs } from './draft-fixtures.mjs';
import { historyPage } from './history-fixtures.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const state = () => store.getState();
const queue = (id = 'one') => state().messageQueues[id];
const session = (id, projectId = null) => ({ session_id: id, kind: projectId ? 'workspace' : 'ordinary',
  project_id: projectId, title: id, updated_at: '2026-10-03T00:00:00Z', effective: {} });
const attachment = { id: 'file', type: 'file', name: 'notes.txt', uri: 'local://attachments/file' };
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
let calls, runs, messages, serial;
function run(id, status = 'DONE', sessionId = 'one') {
  const created_at = `2026-10-03T00:00:${String(++serial).padStart(2, '0')}.000000Z`;
  return { run_id: id, session_id: sessionId, status, created_at, updated_at: created_at, metadata: {} };
}
function response(value) { runs.set(value.run_id, value); return { success: true, run: value, session: session(value.session_id), messages: [] }; }
function reset(projectId = null) {
  calls = []; runs = new Map(); messages = []; serial = 0;
  mockDraftCatalogs(api);
  store.setState(store.getInitialState(), true);
  store.setState({ sessions: [session('one', projectId), session('two')], currentSession: session('one', projectId),
    sessionLoad: { sessionId: 'one', projectId, status: 'ready', error: null }, queueTarget: 'one' });
  api.getSession = async (id) => session(id, id === 'one' ? projectId : null);
  api.getHistory = async (id, query) => historyPage(messages.filter((m) => m.session_id === id), [...runs.values()].filter((r) => r.session_id === id), query);
  api.getRun = async (id) => runs.get(id);
  api.deleteSession = async () => {};
  api.updateSession = async (id, patch) => ({ ...session(id), ...patch });
  api.sendMessage = async (...args) => { calls.push(args); return response(run(`sent-${calls.length}`, 'DONE', args[0])); };
}
async function event(value, type = 'run_completed') {
  runs.set(value.run_id, value);
  state().applyRuntimeEvent({ type, session_id: value.session_id, run_id: value.run_id, payload: { run: value } });
  await state().refreshCurrent();
}

// FIFO and editing use stable identities; a non-head edit does not block preceding items.
reset();
for (const text of ['first', 'second', 'third']) assert.equal(state().enqueueMessage(text, [attachment]), true);
const ids = queue().items.map((item) => item.id);
state().setComposerDraftText('discard this draft');
assert.equal(state().beginQueuedEdit(ids[2]), true);
assert.equal(state().composerDraftText, 'third');
assert.equal(state().beginQueuedEdit(ids[0]), false);
state().setComposerDraftText('edited third');
state().setQueuedEditAttachments('one', ids[2], () => []);
await state().dispatchQueuedMessage();
await state().dispatchQueuedMessage();
await state().dispatchQueuedMessage();
assert.deepEqual(calls.map((c) => c[1]), ['first', 'second']);
assert.equal(state().composerDraftText, 'edited third');
assert.equal(queue().items[0].id, ids[2]);
assert.equal(state().saveQueuedEdit(), true);
assert.deepEqual(queue().items[0], { id: ids[2], content: 'edited third', attachments: [] });
await state().dispatchQueuedMessage();
assert.deepEqual(calls.map((c) => c[1]), ['first', 'second', 'edited third']);
assert.equal(queue().items.length, 0);

// Deleting the head edit clears its composer and allows the next item; invalid uploads cannot save.
reset();
state().enqueueMessage('head'); state().enqueueMessage('next');
state().beginQueuedEdit(queue().items[0].id);
state().setQueuedEditAttachments('one', queue().editing.id, () => [{ ...attachment, status: 'uploading' }]);
assert.equal(state().saveQueuedEdit(), false);
await state().dispatchQueuedMessage(); assert.equal(calls.length, 0);
state().deleteQueuedMessage(queue().editing.id);
assert.equal(state().composerDraftText, ''); assert.equal(queue().editing, null);
await state().dispatchQueuedMessage(); assert.equal(calls[0][1], 'next');

// Normal acceptance unlocks enqueueing while its HTTP response is still pending.
reset();
const firstPost = deferred();
api.sendMessage = async (...args) => { calls.push(args); return firstPost.promise; };
const firstSend = state().sendMessage('normal');
assert.equal(state().enqueueMessage('too early'), false);
const clientId = calls[0][3];
messages.push({ message_id: 'accepted', session_id: 'one', role: 'user', parts: [], created_at: '2026-10-03T00:00:00Z', metadata: { client_message_id: clientId } });
state().applyRuntimeEvent({ type: 'message_updated', session_id: 'one', payload: { message: messages[0] } });
assert.equal(state().awaitingAcceptance, false);
assert.equal(state().enqueueMessage('queued'), true);
assert.equal(state().enqueueMessage('also queued'), true);
state().setComposerDraftText('new draft');
await state().dispatchQueuedMessage(); assert.equal(calls.length, 1);
firstPost.resolve(response(run('normal'))); await firstSend;
assert.equal(state().composerDraftText, 'new draft');

// Automatic submission locks only that item, deduplicates triggers and never touches the draft.
reset(); state().enqueueMessage('queued', [attachment]);
const pending = deferred(); api.sendMessage = async (...args) => { calls.push(args); return pending.promise; };
state().setComposerDraftText('keep typing');
const automatic = state().dispatchQueuedMessage();
await state().dispatchQueuedMessage();
assert.equal(calls.length, 1);
assert.equal(state().beginQueuedEdit(queue().items[0].id), false);
state().deleteQueuedMessage(queue().items[0].id); assert.equal(queue().items.length, 1);
state().enqueueMessage('next'); state().setComposerDraftText('newest draft');
pending.resolve(response(run('queued'))); await automatic;
assert.equal(queue().items.length, 1); assert.equal(state().composerDraftText, 'newest draft');

// Approval, history mutations, offscreen navigation and settings saves block scheduling.
reset(); state().enqueueMessage('wait');
const waiting = run('approval', 'WAITING_FOR_USER');
await event(waiting, 'approval_requested'); await state().dispatchQueuedMessage(); assert.equal(calls.length, 0);
await event({ ...waiting, status: 'DONE', updated_at: '2026-10-03T00:01:00Z' });
for (const lock of [{ mutatingHistory: true }, { historyLoading: true }, { queueTarget: null },
  { savingSessionIds: ['one'] }, { resolvingApprovals: ['approval'] },
  { sessionLoad: { sessionId: 'one', projectId: null, status: 'loading' } }]) {
  const previous = Object.fromEntries(Object.keys(lock).map((key) => [key, state()[key]]));
  store.setState(lock); await state().dispatchQueuedMessage(); assert.equal(calls.length, 0);
  store.setState(previous);
}
const saving = deferred(); api.updateSession = () => saving.promise;
const save = state().updateSession({ reasoning: false });
await state().dispatchQueuedMessage(); assert.equal(calls.length, 0);
saving.resolve({ ...session('one'), reasoning: false }); await save;
await state().dispatchQueuedMessage(); assert.equal(calls.length, 1);

// All abnormal terminals pause, and editing/deleting/appending cannot resume implicitly.
for (const status of ['FAILED', 'CANCELLED', 'INTERRUPTED']) {
  reset(); state().enqueueMessage('first');
  const failed = run('failed', status); await event(failed, 'run_failed');
  assert.equal(queue().paused, 'failed');
  state().beginQueuedEdit(queue().items[0].id); state().setComposerDraftText('edited'); state().saveQueuedEdit();
  state().deleteQueuedMessage(queue().items[0].id); state().enqueueMessage('replacement');
  await state().dispatchQueuedMessage(); assert.equal(calls.length, 0);
  await state().resumeMessageQueue();
  await event(failed, 'run_failed'); assert.equal(queue().paused, null, 'Repeated completion cannot undo an explicit resume');
  await state().dispatchQueuedMessage(); assert.equal(calls.length, 1);
}
reset(); state().enqueueMessage('keep paused');
const running = run('stopping', 'RUNNING'); await event(running, 'run_started');
const cancel = deferred(); api.cancelRun = () => cancel.promise;
const cancellation = state().cancelRun(running.run_id);
assert.equal(queue().paused, 'stopped');
const done = { ...running, status: 'DONE', updated_at: '2026-10-03T00:01:00Z' };
await event(done); await state().dispatchQueuedMessage(); assert.equal(calls.length, 0);
cancel.resolve({ run: done }); await cancellation;
assert.equal(queue().paused, 'stopped');

// Rejection preserves position. A lost response searches paged history before allowing a retry.
reset();
api.sendMessage = async (...args) => { calls.push(args); throw new Error('Rejected before acceptance'); };
assert.equal(await state().sendMessage('retry ordinary', [attachment]), false);
assert.equal(state().composerDraftText, 'retry ordinary');
assert.equal(queue().paused, null, 'An unaccepted ordinary send without queued items stays directly retryable');
assert.equal(queue().submission, null);
api.sendMessage = async (...args) => { calls.push(args); return response(run('ordinary retry')); };
assert.equal(await state().sendMessage('retry ordinary', [attachment]), true);
assert.equal(calls.length, 2);

reset(); state().enqueueMessage('rejected');
api.sendMessage = async (...args) => { calls.push(args); return { success: false, error: 'Rejected' }; };
await state().dispatchQueuedMessage(); await state().dispatchQueuedMessage();
assert.equal(calls.length, 1); assert.equal(queue().items[0].content, 'rejected'); assert.equal(queue().paused, 'submission');
reset(); state().enqueueMessage('accepted behind history pages');
api.sendMessage = async (...args) => {
  calls.push(args);
  messages.push({ message_id: 'hidden', role: 'user', session_id: 'one', created_at: '2026-10-03T00:00:00Z', parts: [], metadata: { client_message_id: args[3] } });
  for (let i = 0; i < 65; i++) messages.push({ message_id: `later-${i}`, role: 'user', session_id: 'one', created_at: '2026-10-03T00:01:00Z', parts: [] });
  throw new Error('Response lost');
};
await state().dispatchQueuedMessage();
assert.equal(queue().items.length, 0); assert.equal(queue().submission, null); assert.equal(calls.length, 1);

reset(); state().enqueueMessage('uncertain');
const history = api.getHistory;
api.sendMessage = async (...args) => { calls.push(args); throw new Error('Network lost'); };
api.getHistory = async () => { throw new Error('Cannot reconcile'); };
await state().dispatchQueuedMessage();
assert.equal(queue().paused, 'unconfirmed'); assert.ok(queue().submission);
await state().resumeMessageQueue(); await state().dispatchQueuedMessage(); assert.equal(calls.length, 1);
api.getHistory = history;
await state().resumeMessageQueue(); assert.equal(queue().submission, null); assert.equal(queue().paused, null);
api.sendMessage = async (...args) => { calls.push(args); return response(run('retried')); };
await state().dispatchQueuedMessage(); assert.equal(calls.length, 2);

// Terminal identity survives eviction, and late acceptance belongs to the original session.
reset(); state().enqueueMessage('late'); state().enqueueMessage('remaining');
const late = deferred(); api.sendMessage = async (...args) => { calls.push(args); return late.promise; };
const sending = state().dispatchQueuedMessage();
await state().selectSession('two'); state().setComposerDraftText('other draft');
late.resolve(response(run('old', 'DONE'))); await sending;
assert.equal(queue().items[0].content, 'remaining'); assert.equal(state().composerDraftText, 'other draft');
await state().selectSession('one'); store.setState({ queueTarget: 'one' });
state().beginQueuedEdit(queue().items[0].id); state().setComposerDraftText('retained edit');
await state().selectSession('two'); await state().selectSession('one');
assert.equal(state().composerDraftText, 'retained edit'); assert.equal(queue().editing.content, 'retained edit');
const editedId = queue().editing.id;
await state().selectSession('two');
state().setQueuedEditAttachments('one', editedId, () => [{ ...attachment, status: 'ready', attachment }]);
assert.equal(state().composerDraftText, ''); assert.equal(queue().editing.attachments.length, 1);
await state().selectSession('one'); store.setState({ queueTarget: 'one' });
const offscreen = run('outside', 'RUNNING'); await event(offscreen, 'run_started');
await state().loadHistory('latest'); store.setState({ runs: [], messages: [] });
assert.equal(queue().run.run_id, 'outside');
await state().dispatchQueuedMessage(); assert.equal(calls.length, 1);
await event({ ...offscreen, status: 'FAILED', updated_at: '2026-10-03T00:01:00Z' }, 'run_failed');
assert.equal(queue().paused, 'failed');

reset('workspace'); state().enqueueMessage('project queue'); state().forgetProject('workspace');
assert.equal(queue(), undefined);
reset(); state().enqueueMessage('deleted'); await state().deleteSession('one'); assert.equal(queue(), undefined);
store.setState(store.getInitialState(), true); assert.deepEqual(state().messageQueues, {});
console.log('Message queue: FIFO, editing, attachments, pauses, approvals, confirmation, settings, history and navigation: ok');
