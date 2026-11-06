import assert from 'node:assert/strict';
import { apiMocks, createModuleLoader } from './module-loader.mjs';
import { mockDraftCatalogs, normalCharacter, policy, COGITA } from './draft-fixtures.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const { useModelsStore: models } = (await load('../src/store/useModelsStore.ts')).exports;
const { draftConfiguration, resolveDraft } = (await load('../src/store/cogita/drafts.ts')).exports;
const { newChatUrl, readCharacterRoute, isDraftRoute } = (await load('../src/components/characters/navigation.ts')).exports;
const character = normalCharacter('custom');
const saved = (id, characterId = COGITA) => ({ session_id: id, kind: 'normal', character_id: characterId,
  title: '', overrides: {}, effective: {}, updated_at: '2026-09-30T00:00:00Z' });
const result = (session) => ({ success: true, session, messages: [], run: { run_id: 'run', session_id: session.session_id,
  status: 'DONE', created_at: session.updated_at, updated_at: session.updated_at } });
function deferred() { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
let calls;
function reset() {
  store.setState(store.getInitialState(), true);
  mockDraftCatalogs(api);
  calls = [];
  api.get = async (id) => normalCharacter(id);
  api.listSessions = async () => [];
  api.getGeneralSettings = async () => ({});
  api.getSession = async (id) => saved(id);
  api.messageRows = async () => [];
  api.runRows = async () => [];
  api.createSession = async (...args) => { calls.push(['create', ...args]); return saved('created', args[0]); };
  api.sendMessage = async (...args) => { calls.push(['send', ...args]); return result(saved(args[0])); };
}

reset();
const providers = [{ id: 'provider', name: 'Available provider' }];
api.listProviderProfiles = async () => providers;
await store.getState().initialize();
assert.deepEqual(models.getState().providers, providers, 'Startup supplies provider names to the chat model menu');
assert.equal(store.getState().currentSession, null);
assert.equal(store.getState().chatDraft.kind, 'normal');
assert.deepEqual(calls, []);
store.getState().setComposerDraftText('keep this');
const epoch = store.getState().sessionEpoch;
for (let i = 0; i < 100; i++) await store.getState().startDraft();
assert.equal(store.getState().sessionEpoch, epoch);
assert.equal(store.getState().composerDraftText, 'keep this');
assert.equal(draftConfiguration(store.getState().chatDraft, [], normalCharacter()).reasoning, true);
store.getState().saveDraft({ title: 'Manual', overrides: { persona_id: 'chosen', context_policy: { ...policy, history_enabled: false }, temperature: 0, reasoning: false, tools_allowed: [], knowledge_base_ids: ['kb'], worldbook_ids: ['book'] } });
assert.deepEqual(calls, []);
assert.equal(await store.getState().sendMessage('   '), false);
assert.deepEqual(calls, []);
const attachment = { type: 'image', name: 'image.png', id: 'attachment' };
await store.getState().sendMessage('question', [attachment]);
assert.deepEqual(calls.map((c) => c[0]), ['create', 'send']);
assert.equal(calls[0][1], COGITA);
assert.deepEqual(calls[0][2], { title: 'Manual', overrides: { persona_id: 'chosen', context_policy: { ...policy, history_enabled: false },
  temperature: 0, reasoning: false, tools_allowed: [], knowledge_base_ids: ['kb'], worldbook_ids: ['book'] } });
assert.deepEqual(calls[1].slice(1, 4), ['created', 'question', [attachment]]);
assert.equal(store.getState().sessionEpoch, epoch, 'Promotion must not reset the composer or attachment hook');
assert.equal(store.getState().chatDraft, null);

reset();
await store.getState().startDraft('custom');
assert.equal(draftConfiguration(store.getState().chatDraft, [], character).reasoning, true);
store.getState().saveDraft({ overrides: { context_policy: { ...policy, history_enabled: false }, temperature: 0, tools_allowed: [], harness_enabled: false, reasoning: false } });
assert.equal(draftConfiguration(store.getState().chatDraft, [], character).context_policy.history_enabled, false);
assert.equal(draftConfiguration(store.getState().chatDraft, [], character).reasoning, false);
await store.getState().sendMessage('', [attachment]);
assert.deepEqual(calls[0], ['create', 'custom', { title: '', overrides: { context_policy: { ...policy, history_enabled: false }, temperature: 0, tools_allowed: [], harness_enabled: false, reasoning: false } }]);

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
assert.equal(store.getState().chatDraft.kind, 'normal');
assert.equal(store.getState().composerDraftText, 'retry me');
assert.equal(store.getState().awaitingAcceptance, false);
assert.match(store.getState().error, /Creation failed/);

reset();
await store.getState().startDraft();
api.sendMessage = async () => { throw new Error('Send failed'); };
await store.getState().sendMessage('retry');
assert.equal(store.getState().currentSession.session_id, 'created');
assert.match(store.getState().error, /Send failed/);
api.sendMessage = async () => result(saved('created'));
await store.getState().sendMessage('retry');
assert.equal(calls.filter((c) => c[0] === 'create').length, 1);

reset();
await store.getState().startDraft();
store.getState().saveDraft({ overrides: { knowledge_base_ids: ['original-kb'] } });
const late = deferred();
api.createSession = () => late.promise;
const oldSend = store.getState().sendMessage('original', [attachment]);
await store.getState().selectSession('other');
store.getState().setComposerDraftText('new page');
late.resolve(saved('late'));
await oldSend;
assert.equal(store.getState().currentSession.session_id, 'other');
assert.equal(store.getState().composerDraftText, 'new page');
assert.deepEqual(calls[0].slice(1, 4), ['late', 'original', [attachment]]);
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
  api.messageRows = async () => [{ message_id: 'saved', session_id: 'recovered', role: 'user',
    created_at: recoveredSession.updated_at, parts: [], metadata: { client_message_id: id } }];
  throw new Error('Lost response before WebSocket notification');
};
assert.equal(await store.getState().sendMessage('saved input'), true);
assert.equal(store.getState().composerDraftText, '');

assert.equal(newChatUrl(), `/characters/${COGITA}/new`);
assert.equal(newChatUrl('a/b'), '/characters/a%2Fb/new');
assert.deepEqual(readCharacterRoute({ pathname: '/characters/a%2Fb/new', search: '' }), { characterId: 'a/b', sessionId: null });
assert.equal(isDraftRoute({ pathname: `/characters/${COGITA}/new` }), true);
assert.equal(isDraftRoute({ pathname: '/characters/a' }), false);
assert.equal(resolveDraft({ overrides: {} }, { ...character, model_profile_id: null }).model_profile_id, null);
assert.equal(resolveDraft({ overrides: { reasoning: false, temperature: 0, knowledge_base_ids: [], worldbook_ids: null } },
  { ...character, knowledge_base_ids: ['parent'], worldbook_ids: ['lore'] }).reasoning, false);
assert.deepEqual(resolveDraft({ overrides: { knowledge_base_ids: [] } }, { ...character, knowledge_base_ids: ['parent'] }).knowledge_base_ids, []);
console.log('Chat drafts: atomic creation, sparse overrides, failures, routes and navigation isolation: ok');
