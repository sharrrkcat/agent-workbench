import assert from 'node:assert/strict';
import { apiMocks, createModuleLoader } from './module-loader.mjs';
import { mockDraftCatalogs } from './draft-fixtures.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const { useProjectsStore: projects } = (await load('../src/store/useProjectsStore.ts')).exports;
const { projectUrl, readProjectRoute } = (await load('../src/components/projects/navigation.ts')).exports;
const normal = { session_id: 'ordinary', kind: 'ordinary', project_id: null, title: 'Ordinary', effective: {} };
const child = (id, projectId) => ({ session_id: id, kind: 'workspace', project_id: projectId, title: id, overrides: {}, effective: {} });
const first = child('first', 'a'), second = child('second', 'b');
const project = (id, kind = 'workspace') => ({ id, kind, name: id, updated_at: '2026-09-25T00:00:00Z' });
function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }
function reset() {
  mockDraftCatalogs(api);
  store.setState(store.getInitialState(), true);
  projects.setState(projects.getInitialState(), true);
  store.setState({ initialized: true, sessions: [normal, first, second], currentSession: first, currentProjectId: 'a',
    lastOrdinarySessionId: normal.session_id, composerDraftText: 'Draft', messages: [{ message_id: 'old-message' }] });
  projects.setState({ projects: [project('a'), project('b'), project('timeline', 'timeline')] });
  api.get = async (id) => project(id, id === 'timeline' ? 'timeline' : 'workspace');
  api.getSession = async (id) => [normal, first, second].find((session) => session.session_id === id);
  api.messageRows = async () => [];
  api.runRows = async () => [];
  api.deleteSession = async () => {};
  api.remove = async () => {};
}

assert.equal(projectUrl('project/id', 'session/id'), '/projects/project%2Fid?session=session%2Fid');
assert.deepEqual(readProjectRoute({ pathname: '/projects/a', search: '?session=first' }), { projectId: 'a', sessionId: 'first' });
assert.deepEqual(readProjectRoute({ pathname: '/', search: '' }), { projectId: null, sessionId: null });

reset();
await store.getState().activateLocation('b');
assert.equal(store.getState().currentProjectId, 'b');
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().composerDraftText, '');
await store.getState().activateLocation('b', 'second');
assert.equal(store.getState().currentSession.session_id, 'second');
await store.getState().activateLocation(null);
assert.equal(store.getState().currentSession.session_id, 'ordinary');

reset();
await store.getState().activateLocation('b', 'first');
assert.equal(store.getState().currentSession, null, 'A foreign session cannot be displayed in another Project');
assert.match(store.getState().sessionLoad.error, /SESSION_PROJECT_MISMATCH/);
await store.getState().activateLocation('timeline', 'first');
assert.equal(store.getState().currentSession, null);
assert.match(store.getState().sessionLoad.error, /PROJECT_CHAT_UNAVAILABLE/);

reset();
const late = deferred();
api.get = (id) => id === 'a' ? late.promise : Promise.resolve(project(id));
const openingA = store.getState().activateLocation('a');
await store.getState().activateLocation('b', 'second');
late.resolve(project('a'));
await openingA;
assert.equal(store.getState().currentSession.session_id, 'second');
assert.equal(store.getState().currentProjectId, 'b');

reset();
let creations = 0;
api.createSession = async () => { creations++; return { ...normal, session_id: 'replacement' }; };
await store.getState().deleteSession('first');
assert.equal(creations, 0, 'An empty Workspace must not create an ordinary session');
assert.equal(store.getState().currentProjectId, 'a');
assert.equal(store.getState().currentSession, null);
assert.deepEqual(store.getState().sessions, [normal, second]);
await store.getState().selectSession('ordinary', null);
await store.getState().deleteSession('ordinary');
assert.equal(creations, 0, 'Deleting the last ordinary session must not create a replacement');
assert.equal(store.getState().chatDraft.kind, 'ordinary');

reset();
const created = deferred();
api.get = () => created.promise;
const creating = store.getState().startDraft('a');
await store.getState().selectSession('second', 'b');
created.resolve(project('a'));
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
  'A Project list arriving during session selection must not duplicate the session');

reset();
const pendingDetails = deferred();
api.getSession = () => pendingDetails.promise;
const pendingSelection = store.getState().selectSession('uncached', 'a');
await store.getState().activateLocation('a');
pendingDetails.resolve(fetched);
await pendingSelection;
assert.equal(store.getState().currentSession, null, 'Project settings invalidate an uncached pending session');
assert.equal(store.getState().sessionLoad, null);

reset();
store.setState({ currentSession: null });
const lateCreation = deferred();
api.get = () => lateCreation.promise;
const creatingVisible = store.getState().startDraft('a');
api.listSessions = async () => [first, fetched];
await store.getState().reloadSessions('a');
lateCreation.resolve(project('a'));
await creatingVisible;
assert.equal(store.getState().sessions.filter((session) => session.session_id === 'uncached').length, 1,
  'Loading a draft must preserve the session list');

reset();
const oldProjects = deferred();
api.list = () => oldProjects.promise;
const reading = projects.getState().reload();
await projects.getState().remove('a');
store.getState().forgetProject('a');
oldProjects.resolve([project('a'), project('b')]);
await reading;
assert.ok(!projects.getState().projects.some((project) => project.id === 'a'));
assert.ok(!store.getState().sessions.some((session) => session.project_id === 'a'));
assert.equal(store.getState().currentSession, null);

reset();
const staleList = deferred();
api.list = () => staleList.promise;
const beforePatch = projects.getState().reload();
const patches = [];
api.update = async (id, values) => {
  patches.push({ id, values });
  return { ...project(id, 'qqbot'), reasoning: false, system_prompt: 'Retained prompt', has_access_token: true };
};
await projects.getState().patch('a', { reasoning: false });
staleList.resolve([project('a'), project('b')]);
await beforePatch;
assert.deepEqual(patches, [{ id: 'a', values: { reasoning: false } }]);
assert.equal(projects.getState().projects.find((item) => item.id === 'a').reasoning, false,
  'A stale list cannot replace the confirmed Project patch');
assert.equal(projects.getState().projects.find((item) => item.id === 'a').has_access_token, true);
const confirmed = projects.getState().projects;
api.update = async () => { throw new Error('Project save failed'); };
await assert.rejects(projects.getState().patch('a', { reasoning: true }), /Project save failed/);
assert.equal(projects.getState().projects, confirmed, 'A rejected patch preserves confirmed settings');
const latePatch = deferred();
api.update = () => latePatch.promise;
const savingRemoved = projects.getState().patch('a', { reasoning: true });
await projects.getState().remove('a');
latePatch.resolve({ ...project('a', 'qqbot'), reasoning: true });
await savingRemoved;
assert.ok(!projects.getState().projects.some((item) => item.id === 'a'), 'A late patch cannot restore a removed Project');

const requests = [];
globalThis.fetch = async (url, options) => {
  requests.push({ url, method: options?.method, body: options?.body ? JSON.parse(options.body) : null });
  return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
};
const realLoad = createModuleLoader();
const { projectsApi } = (await realLoad('../src/api/projects.ts')).exports;
const { chatApi } = (await realLoad('../src/api/chat.ts')).exports;
await projectsApi.createSession('a/b');
assert.deepEqual(requests.at(-1), { url: '/api/projects/a%2Fb/sessions', method: 'POST', body: {} });
await chatApi.updateSession('child', { overrides: { temperature: 0, harness_enabled: false, tools_allowed: [] } });
assert.deepEqual(requests.at(-1).body, { overrides: { temperature: 0, harness_enabled: false, tools_allowed: [] } });
await chatApi.updateSession('child', { overrides: { temperature: null } });
assert.deepEqual(requests.at(-1).body, { overrides: { temperature: null } });
const { qqApi } = (await realLoad('../src/api/qq.ts')).exports;
await qqApi.createSession('qq/a', { title: '', target_kind: 'friend', target_id: '12345678901234567' });
assert.deepEqual(requests.at(-1), { url: '/api/projects/qq%2Fa/sessions', method: 'POST',
  body: { title: '', target_kind: 'friend', target_id: '12345678901234567' } });
await qqApi.control('session/a', 'stop');
assert.deepEqual(requests.at(-1), { url: '/api/qq/sessions/session%2Fa/control', method: 'POST', body: { action: 'stop' } });
await qqApi.messages('session/a', 42);
assert.equal(requests.at(-1).url, '/api/qq/sessions/session%2Fa/messages?before=42');
console.log('Project routing, scope isolation, delayed selection/deletion and sparse override payloads: ok');
