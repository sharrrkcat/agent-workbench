import assert from 'node:assert/strict';
import { apiMocks, createModuleLoader } from './module-loader.mjs';
import { mockDraftCatalogs, COGITA, normalCharacter } from './draft-fixtures.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const { playgroundUrl, readPlaygroundRoute } = (await load('../src/components/playground/navigation.ts')).exports;
const session = (id) => ({ session_id: id, kind: 'normal', character_id: COGITA, title: id, effective: {}, updated_at: '2026-10-25T00:00:00Z' });
const saved = session('saved');
function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }
let reads, sends;
function reset() {
  store.setState(store.getInitialState(), true);
  mockDraftCatalogs(api);
  reads = []; sends = [];
  api.listSessions = async () => [saved];
  api.getGeneralSettings = async () => ({});
  api.getSession = async (id) => { reads.push(id); return session(id); };
  api.messageRows = async () => [];
  api.runRows = async () => [];
  api.sendMessage = async (id, content) => {
    sends.push([id, content]);
    return { success: true, session: session(id), messages: [], run: { run_id: 'run', session_id: id,
      status: 'DONE', created_at: saved.updated_at, updated_at: saved.updated_at } };
  };
}

assert.equal(readPlaygroundRoute({ pathname: playgroundUrl() }), 'index');
assert.equal(readPlaygroundRoute({ pathname: playgroundUrl('farkle') }), 'farkle');
for (const pathname of ['/', '/new', '/settings', '/characters/one', '/playground/whisper', '/playground/unknown'])
  assert.equal(readPlaygroundRoute({ pathname }), null);

reset();
await store.getState().initialize(false);
assert.deepEqual(store.getState().sessions, []);
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().chatDraft, null);
assert.deepEqual(reads, [], 'Playground startup leaves conversations unopened');

await store.getState().selectSession(saved.session_id);
store.getState().enqueueMessage('queued message', [{ id: 'file', name: 'queued.txt', type: 'file' }]);
store.getState().setComposerDraftText('unsent text');
store.setState({ queueTarget: saved.session_id });
const before = store.getState();
store.getState().deactivateConversation();
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().currentCharacterId, null);
assert.equal(store.getState().sessionLoad, null);
assert.equal(store.getState().composerDraftText, '');
assert.equal(store.getState().queueTarget, null);
assert.equal(store.getState().sessionEpoch, before.sessionEpoch + 1);
assert.deepEqual(store.getState().sessions, before.sessions);
assert.deepEqual(store.getState().messageQueues, before.messageQueues);
await store.getState().dispatchQueuedMessage();
assert.deepEqual(sends, [], 'Hidden conversations cannot dispatch queued messages');
await store.getState().activateLocation(null);
assert.equal(store.getState().currentSession.session_id, saved.session_id);
assert.equal(store.getState().sessionLoad.status, 'ready');
store.setState({ queueTarget: saved.session_id });
await store.getState().dispatchQueuedMessage();
assert.deepEqual(sends, [[saved.session_id, 'queued message']]);

reset();
await store.getState().startDraft();
store.getState().saveDraft({ title: 'Unsaved title', overrides: { knowledge_base_ids: ['knowledge'] } });
store.getState().setComposerDraftText('unsaved draft');
store.getState().deactivateConversation();
assert.equal(store.getState().chatDraft, null);
assert.equal(store.getState().composerDraftText, '');
await store.getState().startDraft();
assert.equal(store.getState().chatDraft.title, '');
assert.deepEqual(store.getState().chatDraft.overrides, {});

reset();
const lateList = deferred();
api.listSessions = () => lateList.promise;
const initializing = store.getState().initialize();
store.getState().deactivateConversation();
lateList.resolve([saved]);
await initializing;
assert.equal(store.getState().initialized, true);
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().chatDraft, null);
assert.deepEqual(reads, [], 'A pending home initialization cannot open a chat after departure');

reset();
const lateDetails = deferred(), lateHistory = deferred();
api.getSession = () => lateDetails.promise;
api.messageRows = () => lateHistory.promise;
const selecting = store.getState().selectSession(saved.session_id);
store.getState().deactivateConversation();
const departedEpoch = store.getState().sessionEpoch;
lateDetails.resolve(saved);
lateHistory.resolve([]);
await selecting;
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().sessionLoad, null);
assert.equal(store.getState().sessionEpoch, departedEpoch);
assert.deepEqual(store.getState().messages, []);

reset();
const lateTools = deferred();
api.get = () => lateTools.promise;
const drafting = store.getState().startDraft();
store.getState().deactivateConversation();
lateTools.resolve(normalCharacter());
await drafting;
assert.equal(store.getState().chatDraft, null, 'A pending draft cannot reopen the composer');

reset();
await store.getState().startDraft();
const lateCreation = deferred();
api.createSession = () => lateCreation.promise;
const sending = store.getState().sendMessage('first message');
store.getState().deactivateConversation();
lateCreation.resolve(saved);
await sending;
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().chatDraft, null);
assert.equal(store.getState().composerDraftText, '');
assert.ok(store.getState().sessions.some((item) => item.session_id === saved.session_id));
assert.deepEqual(sends, [[saved.session_id, 'first message']], 'An already submitted message completes in its original session');

console.log('Playground routes, startup, conversation departure, queue return and late responses: ok');
