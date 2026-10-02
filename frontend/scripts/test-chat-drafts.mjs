import assert from 'node:assert/strict';
import { apiMocks, createModuleLoader } from './module-loader.mjs';
import { mockDraftCatalogs } from './draft-fixtures.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const { draftConfiguration, defaultModelId } = (await load('../src/store/cogita/drafts.ts')).exports;
const { newChatUrl, readProjectRoute, isDraftRoute } = (await load('../src/components/projects/navigation.ts')).exports;
const policy = { include_attachments: 'explicit', max_messages: null, max_chars: null };
const project = { id: 'workspace', kind: 'workspace', agent_persona_id: 'agent', context_policy: policy };
const saved = (id, projectId = null) => ({ session_id: id, kind: projectId ? 'workspace' : 'ordinary', project_id: projectId,
  title: '', effective: {}, updated_at: '2026-09-30T00:00:00Z' });
const result = (session) => ({ success: true, session, messages: [], run: { run_id: 'run', session_id: session.session_id,
  status: 'DONE', created_at: session.updated_at, updated_at: session.updated_at } });
function deferred() { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
let calls;
function reset() {
  store.setState(store.getInitialState(), true);
  mockDraftCatalogs(api);
  calls = [];
  api.get = async () => project;
  api.listSessions = async () => [];
  api.getGeneralSettings = async () => ({});
  api.getSession = async (id) => saved(id);
  api.listMessages = async () => [];
  api.listRuns = async () => [];
  api.listRuns = async () => [];
  api.createSession = async (...args) => { calls.push(['create', ...args]); return saved('created', typeof args[0] === 'string' ? args[0] : null); };
  api.updateSessionKnowledgeBases = async (...args) => { calls.push(['bindings', ...args]); };
  api.sendMessage = async (...args) => { calls.push(['send', ...args]); return result(saved(args[0])); };
}

reset();
await store.getState().initialize();
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().chatDraft.kind, 'ordinary');
assert.deepEqual(calls, []);
store.getState().setComposerDraftText('keep this');
const epoch = store.getState().sessionEpoch;
for (let i = 0; i < 100; i++) await store.getState().startDraft();
assert.equal(store.getState().sessionEpoch, epoch);
assert.equal(store.getState().composerDraftText, 'keep this');
assert.equal(store.getState().chatDraft.reasoning, true);
store.getState().saveDraft({ persona_id: 'chosen', title: 'Manual', context_policy: { ...policy, max_messages: 0 }, generation: { temperature: 0 }, reasoning: false, tools_allowed: [] }, ['kb']);
assert.deepEqual(calls, []);
assert.equal(await store.getState().sendMessage('   '), false);
assert.deepEqual(calls, []);
const attachment = { type: 'image', name: 'image.png', id: 'attachment' };
await store.getState().sendMessage('question', [attachment]);
assert.deepEqual(calls.map((c) => c[0]), ['create', 'bindings', 'send']);
assert.equal(calls[0][1].persona_id, 'chosen');
assert.equal(calls[0][1].title, 'Manual');
assert.deepEqual(calls[0][1].generation, { temperature: 0 });
assert.equal(calls[0][1].reasoning, false);
assert.deepEqual(calls[0][1].context_policy, { ...policy, max_messages: 0 });
assert.deepEqual(calls[0][1].tools_allowed, []);
assert.equal('knowledge_base_ids' in calls[0][1], false);
assert.deepEqual(calls[1], ['bindings', 'created', ['kb']]);
assert.deepEqual(calls[2].slice(1, 4), ['created', 'question', [attachment]]);
assert.equal(store.getState().sessionEpoch, epoch, 'Promotion must not reset the composer or attachment hook');
assert.equal(store.getState().chatDraft, null);

reset();
await store.getState().startDraft('workspace');
assert.equal(draftConfiguration(store.getState().chatDraft, [], [], null, project).reasoning, true);
store.getState().saveDraft({ overrides: { context_policy: { ...policy, max_messages: 0 }, temperature: 0, tools_allowed: [], harness_enabled: false, reasoning: false } }, ['kb']);
assert.equal(draftConfiguration(store.getState().chatDraft, [], [], null, project).context_policy.max_messages, 0);
assert.equal(draftConfiguration(store.getState().chatDraft, [], [], null, project).reasoning, false);
await store.getState().sendMessage('', [attachment]);
assert.deepEqual(calls[0], ['create', 'workspace', { title: '', overrides: { context_policy: { ...policy, max_messages: 0 }, temperature: 0, tools_allowed: [], harness_enabled: false, reasoning: false } }]);

reset();
await store.getState().startDraft();
const creation = deferred();
api.createSession = async () => { calls.push(['create']); return creation.promise; };
const sending = store.getState().sendMessage('first');
assert.equal(store.getState().sending, true);
assert.equal(store.getState().composerDraftText, '');
assert.equal(store.getState().awaitingAcceptance, true);
assert.equal(await store.getState().sendMessage('second'), false);
creation.resolve(saved('one'));
await sending;
assert.deepEqual(calls.map((c) => c[0]), ['create', 'send']);
assert.equal(store.getState().sending, false);

reset();
await store.getState().startDraft();
api.createSession = async () => { throw new Error('Creation failed'); };
store.getState().setComposerDraftText('retry me');
await store.getState().sendMessage('retry me');
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().chatDraft.kind, 'ordinary');
assert.equal(store.getState().composerDraftText, 'retry me');
assert.equal(store.getState().awaitingAcceptance, false);
assert.match(store.getState().error, /Creation failed/);

reset();
await store.getState().startDraft();
store.getState().saveDraft({}, ['kb']);
api.updateSessionKnowledgeBases = async () => { throw new Error('Bindings failed'); };
await store.getState().sendMessage('retry');
assert.equal(store.getState().currentSession.session_id, 'created');
assert.deepEqual(store.getState().pendingKnowledge, { sessionId: 'created', ids: ['kb'] });
api.updateSessionKnowledgeBases = async (...args) => { calls.push(['bindings', ...args]); };
api.sendMessage = async () => { throw new Error('Send failed'); };
await store.getState().sendMessage('retry');
assert.equal(store.getState().pendingKnowledge, null);
assert.match(store.getState().error, /Send failed/);
api.sendMessage = async () => result(saved('created'));
await store.getState().sendMessage('retry');
assert.equal(calls.filter((c) => c[0] === 'create').length, 1);

reset();
await store.getState().startDraft();
store.getState().saveDraft({}, ['original-kb']);
const late = deferred();
api.createSession = () => late.promise;
const oldSend = store.getState().sendMessage('original', [attachment]);
await store.getState().selectSession('other');
store.getState().setComposerDraftText('new page');
late.resolve(saved('late'));
await oldSend;
assert.equal(store.getState().currentSession.session_id, 'other');
assert.equal(store.getState().composerDraftText, 'new page');
assert.deepEqual(calls[0], ['bindings', 'late', ['original-kb']]);
assert.deepEqual(calls[1].slice(1, 4), ['late', 'original', [attachment]]);
assert.ok(store.getState().sessions.some((s) => s.session_id === 'late'));

for (const finish of ['success', 'failed-run', 'cancelled-run', 'lost-response']) {
  reset();
  const activeSession = saved('active');
  store.setState({ currentSession: activeSession, sessions: [activeSession], composerDraftText: 'captured' });
  const pending = deferred();
  let clientId;
  api.sendMessage = async (_session, _content, _attachments, id) => { clientId = id; return pending.promise; };
  const sending = store.getState().sendMessage('captured', [attachment]);
  assert.equal(store.getState().composerDraftText, '');
  assert.equal(store.getState().awaitingAcceptance, true);
  const persisted = { message_id: 'user', session_id: 'active', role: 'user', created_at: activeSession.updated_at,
    parts: [{ id: 'text', type: 'text', text: 'captured' }], metadata: { client_message_id: clientId, attachments: [attachment] } };
  store.getState().applyRuntimeEvent({ type: 'message_updated', session_id: 'active', message_id: persisted.message_id, payload: { message: persisted } });
  assert.equal(store.getState().awaitingAcceptance, false);
  store.getState().setComposerDraftText('next draft');
  if (finish === 'lost-response') pending.reject(new Error('Response connection lost'));
  else {
    const response = result(activeSession);
    if (finish !== 'success') { response.success = false; response.run.status = finish === 'failed-run' ? 'FAILED' : 'CANCELLED'; }
    pending.resolve(response);
  }
  assert.equal(await sending, true, finish);
  assert.equal(store.getState().composerDraftText, 'next draft', finish);
  assert.equal(store.getState().sending, false);
}

reset();
const recoveredSession = saved('recovered');
store.setState({ currentSession: recoveredSession, sessions: [recoveredSession] });
api.getSession = async () => recoveredSession;
api.sendMessage = async (_session, _content, _attachments, id) => {
  api.listMessages = async () => [{ message_id: 'saved', session_id: 'recovered', role: 'user',
    created_at: recoveredSession.updated_at, parts: [], metadata: { client_message_id: id } }];
  throw new Error('Lost response before WebSocket notification');
};
assert.equal(await store.getState().sendMessage('saved input'), true);
assert.equal(store.getState().composerDraftText, '');

assert.equal(newChatUrl(), '/new');
assert.equal(newChatUrl('a/b'), '/projects/a%2Fb/new');
assert.deepEqual(readProjectRoute({ pathname: '/projects/a%2Fb/new', search: '' }), { projectId: 'a/b', sessionId: null });
assert.equal(isDraftRoute({ pathname: '/new' }), true);
assert.equal(isDraftRoute({ pathname: '/projects/a' }), false);
assert.equal(defaultModelId([{ id: 'off', kind: 'llm', enabled: false }, { id: 'yes', kind: 'llm', enabled: true }], 'off'), 'yes');
assert.equal(defaultModelId([], null), null);
assert.equal(draftConfiguration({ kind: 'workspace', overrides: {} }, [], [{ id: 'global', kind: 'llm', enabled: true }], null, project).model_profile_id, 'global');
console.log('Chat drafts: deferred creation, complete configuration, duplicate submission, failures, routes and navigation isolation: ok');
