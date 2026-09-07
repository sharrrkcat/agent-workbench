import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { apiMocks, createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { buildReply, buildConversation, toolEntryStatus } = (await load('../src/components/messages/turns.ts')).exports;
const { applyMessageEvent } = (await load('../src/store/messageStream.ts')).exports;
const { useWorkbenchStore: store } = (await load('../src/store/useWorkbenchStore.ts')).exports;
const { toolResponseState } = (await load('../src/store/workbench/mergeState.ts')).exports;
const at = (n) => `2026-09-07T00:00:00.${String(n).padStart(6, '0')}Z`;
const run = { run_id: 'r', session_id: 's', persona_id: 'p', kind: 'chat', status: 'RUNNING',
  created_at: at(2), started_at: at(2), updated_at: at(3), metadata: { input_message_id: 'u', configuration: { persona_name: 'Original speaker' } } };
const user = { message_id: 'u', session_id: 's', role: 'user', created_at: at(1), parts: [{ id: 'input', type: 'text', text: 'encode and decode' }] };
const text = (id, value) => ({ id, type: 'text', text: value });
const reason = (id, value) => ({ id, type: 'reasoning', text: value });
const call = (id, name) => ({ id, type: 'tool_call', tool_call_id: id, tool_name: name, arguments: { value: 'aGk=' } });
const msg = (id, n, parts, extra = {}) => ({ message_id: id, session_id: 's', role: 'assistant', run_id: 'r',
  speaker_id: 'p', speaker_name: 'Original speaker', parent_message_id: 'u', created_at: at(n), parts, ...extra });
const calls = msg('calls', 3, [reason('r1', 'first reasoning'), text('t1', 'working'), call('a', 'base64_encode'), call('b', 'base64_decode')]);
const output = msg('output', 4, [{ id: 'out', type: 'tool_result', tool_call_id: 'a', tool_name: 'base64_encode', status: 'success', data: { value: 'aGk=' } }], { role: 'tool' });
const moreCalls = msg('more', 5, [reason('empty', ' '), call('c', 'base64_decode')]);
const answer = msg('answer', 6, [reason('r2', 'final reasoning'), text('t2', 'final answer')]);
const done = { ...run, status: 'DONE', updated_at: at(8), finished_at: '2026-09-07T00:00:12.000002Z' };

const reply = buildReply(done, [answer, output, moreCalls, calls], []);
assert.equal(reply.answer.message_id, 'answer');
assert.deepEqual(reply.answerParts.map((p) => p.text), ['final answer']);
assert.deepEqual(reply.process.map((p) => p.kind), ['content', 'content', 'tools', 'content']);
assert.deepEqual(reply.process[2].calls.map((c) => c.call.tool_call_id), ['a', 'b', 'c']);
assert.equal(reply.process[2].calls[0].resultMessage.message_id, 'output');
assert.equal(toolEntryStatus(reply.process[2].calls[0], done), 'success');
const separated = buildReply(run, [calls, { ...moreCalls, parts: [text('separator', 'next step'), call('c', 'base64_decode')] }, answer], []);
assert.equal(separated.process.filter((p) => p.kind === 'tools').length, 2);
const direct = buildReply({ ...done, kind: 'tool' }, [calls, output], []);
assert.equal(direct.answer, undefined);
const items = buildConversation('s', [user, calls, output, moreCalls, answer, { ...user, session_id: 'other', message_id: 'other' }], [done], {});
assert.deepEqual(items.map((i) => i.kind), ['message', 'reply']);
assert.equal(items[1].reply.messages.length, 4);
const failedEmpty = { ...done, run_id: 'empty', status: 'FAILED', created_at: at(9), error_code: 'MODEL_NOT_CONFIGURED', error: 'Select a model.' };
assert.equal(buildConversation('s', [user], [failedEmpty], {})[1].reply.process.length, 0);

const event = (type, payload, id = 'draft') => ({ type, session_id: 's', run_id: 'r', message_id: id, payload });
const delta = (seq, partId, kind, value) => event('message_delta', { seq, part_id: partId, part_type: kind, delta: value });
const draft = msg('draft', 6, []);
let messages = applyMessageEvent([], event('message_started', { message: draft }));
messages = applyMessageEvent(messages, delta(1, 'reason', 'reasoning', 'think'));
messages = applyMessageEvent(messages, delta(2, 'body', 'text', 'body'));
messages = applyMessageEvent(messages, delta(3, 'reason', 'reasoning', ' more'));
assert.deepEqual(messages[0].parts.map((p) => p.text), ['think more', 'body']);
for (const bad of [delta(3, 'reason', 'reasoning', 'duplicate'), delta(5, 'body', 'text', 'gap'),
  delta(4, 'reason', 'text', 'changed type'), event('message_delta', { seq: 4, delta: 'missing kind' })]) {
  assert.equal(applyMessageEvent(messages, bad), messages);
}
const incomplete = { ...draft, parts: [reason('reason', 'think more'), text('body', 'body')], metadata: { incomplete: true } };
messages = applyMessageEvent(messages, event('message_completed', { message: incomplete }));
assert.deepEqual(messages, [incomplete]);
assert.equal(applyMessageEvent(messages, delta(4, 'body', 'text', 'late')), messages);
const source = msg('progress', 7, [text('provisional', 'working live')], { metadata: { streaming: true } });
assert.equal(buildReply(run, [calls, source], []).answer.message_id, 'progress');
const classified = buildReply(run, [calls, { ...source, parts: [...source.parts, call('d', 'base64_encode')], metadata: {} }], []);
assert.equal(classified.answer, undefined);
assert.ok(classified.process.some((i) => i.kind === 'content' && i.part.text === 'working live'));

function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { resolve, promise }; }
const session = { session_id: 's', title: 'Session', updated_at: at(1), waiting_run_id: null, effective: { context_policy: { mode: 'selected_message' } } };
function reset() {
  store.setState({ currentSession: session, sessions: [session], messages: [user, calls, output, answer], runs: [done], stepsByRunId: {},
    deletedMessageIds: [], deletedRunIds: [], resolvingApprovals: [], sourceMessageId: 'answer', sending: false, mutatingHistory: false,
    messageVersion: 0, runVersion: 0, sessionVersion: 0, sessionEpoch: 0 });
}
reset();
const oldRead = deferred();
api.getSession = async () => session;
api.listMessages = () => oldRead.promise;
api.listRuns = async () => [done];
const refresh = store.getState().refreshCurrent();
const change = { deleted_message_ids: ['calls', 'output', 'answer'], deleted_run_ids: ['r'] };
store.getState().applyRuntimeEvent(event('history_pruned', change, undefined));
oldRead.resolve([user, calls, output, answer]);
await refresh;
assert.deepEqual(store.getState().messages, [user]);
assert.deepEqual(store.getState().runs, []);
assert.equal(store.getState().sourceMessageId, null);
for (const e of [event('message_completed', { message: answer }, 'answer'), event('tool_call_created', { message: calls }, 'calls'),
  event('run_completed', { run: done }), event('run_step_created', { step: { step_id: 'step', run_id: 'r' } })]) store.getState().applyRuntimeEvent(e);
store.setState(toolResponseState(store.getState(), { session, run: done, messages: [calls, answer] }));
assert.deepEqual(store.getState().messages, [user]);
assert.deepEqual(store.getState().stepsByRunId, {});
api.listMessages = async () => [user];
api.listRuns = async () => [];
await store.getState().refreshCurrent();
assert.deepEqual(store.getState().runs, []);

reset();
store.setState({ messages: [user, { ...draft, metadata: { streaming: true }, parts: [text('body', 'still visible')] }], runs: [{ ...run, status: 'CANCELLING' }] });
api.listMessages = async () => [user];
api.listRuns = async () => [{ ...run, status: 'CANCELLING' }];
await store.getState().refreshCurrent();
assert.equal(store.getState().messages.at(-1).parts[0].text, 'still visible');

reset();
store.setState({ messages: [user, incomplete], runs: [{ ...run, status: 'FAILED' }] });
api.listMessages = async () => [user, incomplete];
api.listRuns = async () => [{ ...done, status: 'FAILED' }];
store.getState().applyRuntimeEvent(event('run_failed', { run: { ...done, status: 'FAILED' } }));
await store.getState().refreshCurrent();
assert.equal(store.getState().messages.at(-1).metadata.incomplete, true);

reset();
const late = deferred();
api.retryRun = () => late.promise;
const retry = store.getState().retryRun('r');
const other = { ...session, session_id: 'other' };
api.getSession = async (id) => id === 's' ? session : other;
api.listMessages = async () => [];
api.listRuns = async () => [];
store.setState({ sessions: [session, other] });
await store.getState().selectSession('other');
await store.getState().selectSession('s');
late.resolve({ success: true, session, run: { ...done, run_id: 'old-response' }, messages: [answer], ...change });
await retry;
assert.deepEqual(store.getState().messages, []);
assert.deepEqual(store.getState().runs, []);
assert.deepEqual(store.getState().deletedRunIds, []);
store.getState().setSettings({ show_full_processing: true });
assert.equal(store.getState().settings.show_full_processing, true);

const resources = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale,
  Object.fromEntries(['runs', 'personas'].map((namespace) => [namespace,
    JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'))])),
]));
const i18n = i18next.createInstance();
await i18n.init({ resources, lng: 'en', fallbackLng: 'en', interpolation: { escapeValue: false } });
let viewState = { ...store.getState(), currentSession: session, runs: [run], messages: [calls], stepsByRunId: {}, resolvingApprovals: [] };
const views = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
  [sourceUrl('store/useWorkbenchStore.ts')]: mockModule({ useWorkbenchStore: (selector) => selector(viewState) }),
});
const { RunReply } = (await views('../src/components/messages/RunReply.tsx')).exports;
const render = (reply, showFullProcessing) => renderToStaticMarkup(React.createElement(RunReply, { reply, showFullProcessing }));
const approvalStep = { step_id: 'approval', kind: 'approval', status: 'running', run_id: 'r', metadata: { tool_call_id: 'a', risk: 'file' } };
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const active = buildReply(run, [calls, output, answer], []);
  const hidden = render(active, false);
  assert.doesNotMatch(hidden, /first reasoning|base64_encode|processing-timeline/);
  assert.match(hidden, /final answer/);
  const shown = render(active, true);
  assert.match(shown, /first reasoning/);
  assert.doesNotMatch(shown, /aGk=|tool-command-details/);
  assert.equal((shown.match(/class="message-avatar"/g) || []).length, 1);
  assert.equal((shown.match(/class="message-row/g) || []).length, 1);
  const completed = render(reply, true);
  assert.doesNotMatch(completed, /first reasoning|processing-timeline/);
  assert.match(completed, /final answer/);
  assert.equal((completed.match(/reply-actions/g) || []).length, 1);
  const waiting = render(buildReply({ ...run, status: 'WAITING_FOR_USER' }, [calls], [approvalStep]), false);
  assert.match(waiting, /aGk=/);
  assert.match(waiting, /base64_encode/);
  assert.doesNotMatch(waiting, /first reasoning/);
  assert.ok(waiting.includes(i18n.t('runs:approve')));
  assert.ok(waiting.includes(i18n.t('runs:reject')));
  assert.match(render(buildReply(failedEmpty, [], []), false), /MODEL_NOT_CONFIGURED/);
}
console.log('reply projection, reasoning deltas, history pruning, late responses, approvals and bilingual rendering: ok');
