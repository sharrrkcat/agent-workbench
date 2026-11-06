import assert from 'node:assert/strict';
import { apiMocks, createModuleLoader } from './module-loader.mjs';
import { mockDraftCatalogs, COGITA } from './draft-fixtures.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const { useCharactersStore: characters } = (await load('../src/store/useCharactersStore.ts')).exports;
const { characterUrl, readCharacterRoute } = (await load('../src/components/characters/navigation.ts')).exports;
const normal = { session_id: 'normal', kind: 'normal', character_id: COGITA, title: 'Cogita', updated_at: '2026-09-25T00:00:00Z', effective: {} };
const child = (id, characterId) => ({ session_id: id, kind: 'normal', character_id: characterId, title: id, updated_at: '2026-09-25T00:00:00Z', overrides: {}, effective: {} });
const first = child('first', 'a'), second = child('second', 'b');
const character = (id, kind = 'normal') => ({ id, kind, name: id, updated_at: '2026-09-25T00:00:00Z' });
function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }
function reset() {
  mockDraftCatalogs(api);
  store.setState(store.getInitialState(), true);
  characters.setState(characters.getInitialState(), true);
  store.setState({ initialized: true, sessions: [normal, first, second], currentSession: first, currentCharacterId: 'a',
    composerDraftText: 'Draft', messages: [{ message_id: 'old-message' }] });
  characters.setState({ characters: [character('a'), character('b'), character('qq', 'qqbot')] });
  api.get = async (id) => character(id, id === 'qq' ? 'qqbot' : 'normal');
  api.listSessions = async (id) => store.getState().sessions.filter((s) => s.character_id === id);
  api.getSession = async (id) => [normal, first, second].find((session) => session.session_id === id);
  api.messageRows = async () => [];
  api.runRows = async () => [];
  api.deleteSession = async () => {};
  api.remove = async () => {};
}

assert.equal(characterUrl('character/id', 'session/id'), '/characters/character%2Fid?session=session%2Fid');
assert.deepEqual(readCharacterRoute({ pathname: '/characters/a', search: '?session=first' }), { characterId: 'a', sessionId: 'first' });
assert.deepEqual(readCharacterRoute({ pathname: '/', search: '' }), { characterId: COGITA, sessionId: null });

reset();
await store.getState().activateLocation('b');
assert.equal(store.getState().currentCharacterId, 'b');
assert.equal(store.getState().currentSession.session_id, 'second');
assert.equal(store.getState().composerDraftText, '');
await store.getState().activateLocation('b', 'second');
assert.equal(store.getState().currentSession.session_id, 'second');
await store.getState().activateLocation(null);
assert.equal(store.getState().currentSession.session_id, 'normal');

reset();
await store.getState().activateLocation('b', 'first');
assert.equal(store.getState().currentSession, null, 'A foreign session cannot be displayed in another Character');
assert.match(store.getState().sessionLoad.error, /SESSION_CHARACTER_MISMATCH/);
await store.getState().activateLocation('qq');
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().chatDraft, null);

reset();
const late = deferred();
api.get = (id) => id === 'a' ? late.promise : Promise.resolve(character(id));
const openingA = store.getState().activateLocation('a');
await store.getState().activateLocation('b', 'second');
late.resolve(character('a'));
await openingA;
assert.equal(store.getState().currentSession.session_id, 'second');
assert.equal(store.getState().currentCharacterId, 'b');

reset();
let creations = 0;
api.createSession = async () => { creations++; return { ...normal, session_id: 'replacement' }; };
await store.getState().deleteSession('first');
assert.equal(creations, 0, 'An empty Character must not create a saved Session');
assert.equal(store.getState().currentCharacterId, 'a');
assert.equal(store.getState().currentSession, null);
assert.deepEqual(store.getState().sessions, [normal, second]);
await store.getState().selectSession('normal', null);
await store.getState().deleteSession('normal');
assert.equal(creations, 0, 'Deleting the last normal Session must not create a replacement');
assert.equal(store.getState().chatDraft.kind, 'normal');

reset();
const created = deferred();
api.get = () => created.promise;
const creating = store.getState().startDraft('a');
await store.getState().selectSession('second', 'b');
created.resolve(character('a'));
await creating;
assert.equal(store.getState().currentSession.session_id, 'second');
assert.equal(store.getState().chatDraft, null);

reset();
const lateSession = deferred();
api.getSession = () => lateSession.promise;
const selecting = store.getState().selectSession('uncached', 'a');
const fetched = child('uncached', 'a');
api.listSessions = async () => [first, fetched];
await store.getState().reloadSessions('a');
lateSession.resolve(fetched);
await selecting;
assert.equal(store.getState().sessions.filter((session) => session.session_id === 'uncached').length, 1,
  'A Character list arriving during session selection must not duplicate the session');

reset();
const pendingDetails = deferred();
api.getSession = () => pendingDetails.promise;
const pendingSelection = store.getState().selectSession('uncached', 'a');
store.getState().deactivateConversation();
pendingDetails.resolve(fetched);
await pendingSelection;
assert.equal(store.getState().currentSession, null, 'Character settings invalidate an uncached pending session');
assert.equal(store.getState().sessionLoad, null);

reset();
store.setState({ currentSession: null });
const lateCreation = deferred();
api.get = () => lateCreation.promise;
const creatingVisible = store.getState().startDraft('a');
api.listSessions = async () => [first, fetched];
await store.getState().reloadSessions('a');
lateCreation.resolve(character('a'));
await creatingVisible;
assert.equal(store.getState().sessions.filter((session) => session.session_id === 'uncached').length, 1,
  'Loading a draft must preserve the session list');

reset();
const oldCharacters = deferred();
api.list = () => oldCharacters.promise;
const reading = characters.getState().reload();
await characters.getState().remove('a');
store.getState().forgetCharacter('a');
oldCharacters.resolve([character('a'), character('b')]);
await reading;
assert.ok(!characters.getState().characters.some((character) => character.id === 'a'));
assert.ok(!store.getState().sessions.some((session) => session.character_id === 'a'));
assert.equal(store.getState().currentSession, null);

reset();
const staleList = deferred();
api.list = () => staleList.promise;
const beforePatch = characters.getState().reload();
const patches = [];
api.update = async (id, values) => {
  patches.push({ id, values });
  return { ...character(id, 'qqbot'), reasoning: false, system_prompt: 'Retained prompt', has_access_token: true };
};
await characters.getState().patch('a', { reasoning: false });
staleList.resolve([character('a'), character('b')]);
await beforePatch;
assert.deepEqual(patches, [{ id: 'a', values: { reasoning: false } }]);
assert.equal(characters.getState().characters.find((item) => item.id === 'a').reasoning, false,
  'A stale list cannot replace the confirmed Character patch');
assert.equal(characters.getState().characters.find((item) => item.id === 'a').has_access_token, true);
const confirmed = characters.getState().characters;
api.update = async () => { throw new Error('Character save failed'); };
await assert.rejects(characters.getState().patch('a', { reasoning: true }), /Character save failed/);
assert.equal(characters.getState().characters, confirmed, 'A rejected patch preserves confirmed settings');
const latePatch = deferred();
api.update = () => latePatch.promise;
const savingRemoved = characters.getState().patch('a', { reasoning: true });
await characters.getState().remove('a');
latePatch.resolve({ ...character('a', 'qqbot'), reasoning: true });
await savingRemoved;
assert.ok(!characters.getState().characters.some((item) => item.id === 'a'), 'A late patch cannot restore a removed Character');

const requests = [];
globalThis.fetch = async (url, options) => {
  requests.push({ url, method: options?.method, body: options?.body ? JSON.parse(options.body) : null });
  return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
};
const realLoad = createModuleLoader();
const { charactersApi } = (await realLoad('../src/api/characters.ts')).exports;
const { chatApi } = (await realLoad('../src/api/chat.ts')).exports;
await charactersApi.createSession('a/b');
assert.deepEqual(requests.at(-1), { url: '/api/characters/a%2Fb/sessions', method: 'POST', body: {} });
await chatApi.updateSession('child', { overrides: { temperature: 0, harness_enabled: false, tools_allowed: [] } });
assert.deepEqual(requests.at(-1).body, { overrides: { temperature: 0, harness_enabled: false, tools_allowed: [] } });
await chatApi.updateSession('child', { overrides: { temperature: null } });
assert.deepEqual(requests.at(-1).body, { overrides: { temperature: null } });
const { qqApi } = (await realLoad('../src/api/qq.ts')).exports;
await qqApi.createSession('qq/a', { title: '', target_kind: 'friend', target_id: '12345678901234567' });
assert.deepEqual(requests.at(-1), { url: '/api/characters/qq%2Fa/sessions', method: 'POST',
  body: { title: '', target_kind: 'friend', target_id: '12345678901234567' } });
await qqApi.control('session/a', 'stop');
assert.deepEqual(requests.at(-1), { url: '/api/qq/sessions/session%2Fa/control', method: 'POST', body: { action: 'stop' } });
await qqApi.history('session/a', { before: 'cursor/42' });
assert.equal(requests.at(-1).url, '/api/qq/sessions/session%2Fa/history?before=cursor%2F42');
console.log('Character routing, scope isolation, delayed selection/deletion and sparse override payloads: ok');
