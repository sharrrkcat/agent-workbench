import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { apiMocks, createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { buildReply, buildConversation, toolEntryStatus } = (await load('../src/components/messages/turns.ts')).exports;
const { messageNumbers } = (await load('../src/components/messages/messageNumbers.ts')).exports;
const { applyMessageEvent } = (await load('../src/store/messageStream.ts')).exports;
const { useCogitaStore: store } = (await load('../src/store/useCogitaStore.ts')).exports;
const { toolResponseState } = (await load('../src/store/cogita/mergeState.ts')).exports;
const { toolArgumentsSummary } = (await load('../src/components/messages/toolPresentation.ts')).exports;
assert.equal(toolArgumentsSummary({ value: 'ABC' }), 'ABC');
assert.equal(toolArgumentsSummary({ path: 'data/knowledge/note.txt', max_bytes: 2000 }), 'path=data/knowledge/note.txt max_bytes=2000');
assert.equal(toolArgumentsSummary({ options: { enabled: false }, ids: [1, 2] }), 'options={"enabled":false} ids=[1,2]');
assert.equal(toolArgumentsSummary({ value: 'first\n\tsecond' }), 'first second');
assert.equal(toolArgumentsSummary({ value: false }), 'false');
assert.equal(toolArgumentsSummary({ value: 0 }), '0');
assert.equal(toolArgumentsSummary({}), '');
const at = (n) => `2026-09-07T00:00:00.${String(n).padStart(6, '0')}Z`;
const run = { run_id: 'r', session_id: 's', persona_id: 'p', kind: 'chat', status: 'RUNNING',
  created_at: at(2), started_at: at(2), updated_at: at(3), metadata: { input_message_id: 'u', configuration: { persona_name: 'Original speaker' } } };
const user = { message_id: 'u', session_id: 's', role: 'user', created_at: at(1), parts: [{ id: 'input', type: 'text', text: 'encode and decode' }] };
const text = (id, value) => ({ id, type: 'text', text: value });
const reason = (id, value) => ({ id, type: 'reasoning', text: value });
const call = (id, name) => ({ id, type: 'tool_call', tool_call_id: id, tool_name: name, arguments: { value: 'aGk=' } });
const msg = (id, n, parts, extra = {}) => ({ message_id: id, session_id: 's', role: 'assistant', run_id: 'r',
  speaker_id: 'p', speaker_name: 'Original speaker', parent_message_id: 'u', created_at: at(n), parts, ...extra });
const calls = msg('calls', 3, [reason('r1', 'first reasoning'), text('t1', 'working'), call('a', 'test_echo'), call('b', 'test_other')]);
const output = msg('output', 4, [{ id: 'out', type: 'tool_result', tool_call_id: 'a', tool_name: 'test_echo', status: 'success', data: { value: 'aGk=' } }], { role: 'tool' });
const moreCalls = msg('more', 5, [reason('empty', ' '), call('c', 'test_other')]);
const answer = msg('answer', 6, [reason('r2', 'final reasoning'), text('t2', 'final answer')]);
const done = { ...run, status: 'DONE', updated_at: at(8), finished_at: '2026-09-07T00:00:12.000002Z' };

const reply = buildReply(done, [answer, output, moreCalls, calls], []);
assert.equal(reply.answer.message_id, 'answer');
assert.deepEqual(reply.answerParts.map((p) => p.text), ['final answer']);
assert.deepEqual(reply.process.map((p) => p.kind), ['content', 'content', 'tool', 'tool', 'tool', 'content']);
assert.deepEqual(reply.process.filter((p) => p.kind === 'tool').map((p) => p.entry.call.tool_call_id), ['a', 'b', 'c']);
assert.deepEqual(reply.process[2].entry.result, output.parts[0]);
assert.equal(toolEntryStatus(reply.process[2].entry, done), 'success');
const separated = buildReply(run, [calls, { ...moreCalls, parts: [text('separator', 'next step'), call('c', 'test_other')] }, answer], []);
assert.deepEqual(separated.process.map((p) => p.kind), ['content', 'content', 'tool', 'tool', 'content', 'tool', 'content']);
const direct = buildReply({ ...done, kind: 'tool' }, [calls, output], []);
assert.equal(direct.answer, undefined);
const items = buildConversation('s', [user, calls, output, moreCalls, answer, { ...user, session_id: 'other', message_id: 'other' }], [done], {});
assert.deepEqual(items.map((i) => i.kind), ['message', 'reply']);
assert.equal(items[1].reply.messages.length, 4);
const numbers = messageNumbers(items);
assert.equal(numbers.get('u'), 1);
for (const id of ['r', 'calls', 'output', 'more', 'answer']) assert.equal(numbers.get(id), 2);
assert.equal(numbers.has('other'), false);
const nextUser = { ...user, message_id: 'next', created_at: at(10) };
for (const status of ['PENDING', 'RUNNING', 'WAITING_FOR_USER', 'DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED']) {
  const conversation = buildConversation('s', [user, nextUser], [{ ...run, status }], {});
  assert.deepEqual([...messageNumbers(conversation)], [['u', 1], ['r', 2], ['next', 3]]);
}
assert.deepEqual([...messageNumbers(buildConversation('s', [user, nextUser], [], {}))], [['u', 1], ['next', 2]]);
assert.deepEqual([...messageNumbers(buildConversation('s', [user], [{ ...run, run_id: 'retry' }], {}))], [['u', 1], ['retry', 2]]);
assert.deepEqual([...messageNumbers(buildConversation('s', [user, nextUser], [{ ...done, kind: 'tool' }], {}))], [['u', 1], ['r', 2], ['next', 3]]);
assert.deepEqual([...messageNumbers(buildConversation('s', [user, answer, calls, moreCalls, output], [done], {}))], [...numbers]);
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
for (const duration_ms of [-1, 1.5, '1000', false]) {
  assert.equal(applyMessageEvent(messages, event('message_delta', { seq: 4, part_id: 'reason', part_type: 'reasoning', delta: '', duration_ms })), messages);
}
assert.equal(applyMessageEvent(messages, event('message_delta', { seq: 4, part_id: 'body', part_type: 'text', delta: '', duration_ms: 10 })), messages);
assert.equal(applyMessageEvent(messages, event('message_delta', { seq: 4, part_id: 'missing', part_type: 'reasoning', delta: '', duration_ms: 10 })), messages);
const timing = event('message_delta', { seq: 4, part_id: 'reason', part_type: 'reasoning', delta: '', duration_ms: 0 });
const timed = applyMessageEvent(messages, timing);
assert.equal(timed[0].parts[0].text, 'think more');
assert.equal(timed[0].parts[0].duration_ms, 0);
assert.equal(timed[0].metadata.stream_seq, 4);
assert.equal(applyMessageEvent(timed, timing), timed);
assert.equal(applyMessageEvent(timed, delta(5, 'reason', 'reasoning', 'late')), timed);
const withBody = applyMessageEvent(timed, delta(5, 'body', 'text', ' after reasoning'));
assert.equal(withBody[0].parts[0].duration_ms, 0);
assert.equal(withBody[0].parts[1].text, 'body after reasoning');
const incomplete = { ...draft, parts: [reason('reason', 'think more'), text('body', 'body')], metadata: { incomplete: true } };
messages = applyMessageEvent(messages, event('message_completed', { message: incomplete }));
assert.deepEqual(messages, [incomplete]);
assert.equal(applyMessageEvent(messages, delta(4, 'body', 'text', 'late')), messages);
const source = msg('progress', 7, [text('provisional', 'working live')], { metadata: { streaming: true } });
assert.equal(buildReply(run, [calls, source], []).answer.message_id, 'progress');
const classified = buildReply(run, [calls, { ...source, parts: [...source.parts, call('d', 'test_echo')], metadata: {} }], []);
assert.equal(classified.answer, undefined);
assert.ok(classified.process.some((i) => i.kind === 'content' && i.part.text === 'working live'));

function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { resolve, promise }; }
const session = { session_id: 's', kind: 'ordinary', project_id: null, title: 'Session', updated_at: at(1), waiting_run_id: null, effective: { context_policy: {} } };
function reset() {
  store.setState({ historyWindow: null, historyFollowing: true, historyLoading: false, historyAnchor: null, currentSession: session, sessions: [session], messages: [user, calls, output, answer], runs: [done], stepsByRunId: {},
    deletedMessageIds: [], deletedRunIds: [], resolvingApprovals: [], sending: false, mutatingHistory: false,
    messageVersion: 0, runVersion: 0, sessionVersion: 0, sessionEpoch: 0 });
}
reset();
const oldRead = deferred();
api.getSession = async () => session;
api.messageRows = () => oldRead.promise;
api.runRows = async () => [done];
const refresh = store.getState().refreshCurrent();
const change = { deleted_message_ids: ['calls', 'output', 'answer'], deleted_run_ids: ['r'] };
store.getState().applyRuntimeEvent(event('history_pruned', change, undefined));
oldRead.resolve([user, calls, output, answer]);
await refresh;
assert.deepEqual(store.getState().messages, [user]);
assert.deepEqual(store.getState().runs, []);
for (const e of [event('message_completed', { message: answer }, 'answer'), event('tool_call_created', { message: calls }, 'calls'),
  event('run_completed', { run: done }), event('run_step_created', { step: { step_id: 'step', run_id: 'r' } })]) store.getState().applyRuntimeEvent(e);
store.setState(toolResponseState(store.getState(), { session, run: done, messages: [calls, answer] }));
assert.deepEqual(store.getState().messages, [user]);
assert.deepEqual(store.getState().stepsByRunId, {});
api.messageRows = async () => [user];
api.runRows = async () => [];
await store.getState().refreshCurrent();
assert.deepEqual(store.getState().runs, []);

reset();
store.setState({ messages: [user, { ...draft, metadata: { streaming: true }, parts: [text('body', 'still visible')] }], runs: [{ ...run, status: 'CANCELLING' }] });
api.messageRows = async () => [user];
api.runRows = async () => [{ ...run, status: 'CANCELLING' }];
await store.getState().refreshCurrent();
assert.equal(store.getState().messages.at(-1).parts[0].text, 'still visible');

reset();
store.setState({ messages: [user, incomplete], runs: [{ ...run, status: 'FAILED' }] });
api.messageRows = async () => [user, incomplete];
api.runRows = async () => [{ ...done, status: 'FAILED' }];
store.getState().applyRuntimeEvent(event('run_failed', { run: { ...done, status: 'FAILED' } }));
await store.getState().refreshCurrent();
assert.equal(store.getState().messages.at(-1).metadata.incomplete, true);

reset();
const late = deferred();
api.retryRun = () => late.promise;
const retry = store.getState().retryRun('r');
const other = { ...session, session_id: 'other' };
api.getSession = async (id) => id === 's' ? session : other;
api.messageRows = async () => [];
api.runRows = async () => [];
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
  Object.fromEntries(['runs', 'personas', 'chat'].map((namespace) => [namespace,
    JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'))])),
]));
const i18n = i18next.createInstance();
await i18n.init({ resources, lng: 'en', fallbackLng: 'en', interpolation: { escapeValue: false } });
let viewState = { ...store.getState(), currentSession: session, runs: [run], messages: [calls], stepsByRunId: {}, resolvingApprovals: [] };
const personaState = { personas: [{ id: 'p', name: 'Current agent', avatar_attachment_id: null }], loaded: true, loading: false, error: null };
const views = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace), i18n }) }),
  [sourceUrl('store/useCogitaStore.ts')]: mockModule({ useCogitaStore: (selector) => selector(viewState) }),
  [sourceUrl('store/usePersonasStore.ts')]: mockModule({ usePersonasStore: () => personaState }),
});
const { RunReply } = (await views('../src/components/messages/RunReply.tsx')).exports;
const { ReasoningBlock } = (await views('../src/components/messages/ReasoningBlock.tsx')).exports;
const { ToolResultBody } = (await views('../src/components/messages/ToolResultBody.tsx')).exports;
const { MessageScrollerProvider } = (await views('../src/components/ui/message-scroller.tsx')).exports;
const { MessageBubble } = (await views('../src/components/MessageBubble.tsx')).exports;
const { ChatAttachments, attachmentSize } = (await views('../src/components/messages/ChatAttachments.tsx')).exports;
const { messagePreview } = (await views('../src/components/messages/messageContent.ts')).exports;
const imageOnly = { ...user, parts: [], metadata: { attachments: [
  { id: 'image', type: 'image', name: 'photo.png', size: 1126, uri: 'local://attachments/aaaa.png' },
] } };
assert.equal(messagePreview(imageOnly), 'photo.png');
assert.equal(attachmentSize(0, 'en'), '0 B');
assert.equal(attachmentSize(820 * 1024, 'en'), '820 KB');
assert.equal(attachmentSize(1153434, 'zh-CN'), '1.1 MB');
const textFile = { id: 'file', type: 'file', name: 'notes.txt', size: 12, mime_type: 'text/plain' };
const fileOnly = { ...user, parts: [], metadata: { attachments: [textFile] } };
assert.equal(messagePreview(fileOnly), 'notes.txt');
const render = (reply, showFullProcessing, readOnly = false) => renderToStaticMarkup(
  React.createElement(MessageScrollerProvider, { autoScroll: true }, React.createElement(RunReply, { reply, showFullProcessing, readOnly })));
const approvalStep = { step_id: 'approval', kind: 'approval', status: 'running', run_id: 'r', metadata: { tool_call_id: 'a', risk: 'file' } };
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  for (const code of ['reasoning_enabled', 'reasoning_disabled']) {
    const warning = renderToStaticMarkup(React.createElement(MessageBubble, {
      message: { ...user, metadata: { request_warnings: { run_id: 'r', codes: [code] } } },
    }));
    assert.ok(warning.includes(i18n.t(`chat:requestWarnings.${code}`)));
    assert.match(warning, /message-request-warning/);
  }
  const active = buildReply(run, [calls, output, answer], []);
  const hidden = render(active, false);
  assert.match(hidden, /Current agent/);
  assert.doesNotMatch(hidden, /Original speaker/);
  assert.doesNotMatch(hidden, /first reasoning|test_echo|processing-list/);
  assert.match(hidden, /final answer/);
  const shown = render(active, true);
  assert.doesNotMatch(shown, /first reasoning|data-slot="code-block"/);
  assert.match(shown, /aGk=/);
  assert.equal((shown.match(/data-tool-call-id=/g) || []).length, 2);
  assert.ok(shown.includes(i18n.t('runs:thought')));
  assert.equal((shown.match(/data-slot="message-avatar"/g) || []).length, 1);
  assert.equal((shown.match(/data-slot="message"/g) || []).length, 1);
  const readOnly = render(reply, true, true);
  assert.ok(readOnly.includes(i18n.t('runs:copyAnswer')));
  assert.ok(!readOnly.includes(i18n.t('runs:retryReply')));
  assert.ok(!readOnly.includes(i18n.t('runs:deleteReply')));
  const completed = render(reply, true);
  assert.doesNotMatch(completed, /first reasoning|processing-list/);
  assert.match(completed, /final answer/);
  assert.equal((completed.match(/reply-actions/g) || []).length, 1);
  const waiting = render(buildReply({ ...run, status: 'WAITING_FOR_USER' }, [calls], [approvalStep]), false);
  assert.match(waiting, /Current agent/);
  assert.match(waiting, /aGk=/);
  assert.match(waiting, /test_echo/);
  assert.doesNotMatch(waiting, /first reasoning/);
  assert.ok(waiting.includes(i18n.t('runs:approve')));
  assert.ok(waiting.includes(i18n.t('runs:reject')));
  assert.doesNotMatch(waiting, /role="switch"/, 'Approval is one button without a nested switch');
  assert.match(waiting, /data-slot="item"/);
  for (const [duration_ms, seconds] of [[0, 0], [1, 1], [2001, 3]]) {
    const reasoning = renderToStaticMarkup(React.createElement(MessageScrollerProvider, {},
      React.createElement(ReasoningBlock, { part: { ...reason('timed', 'Private expanded content'), duration_ms }, streaming: false })));
    assert.ok(reasoning.includes(i18n.t('runs:thoughtDuration', { seconds })));
    assert.doesNotMatch(reasoning, /Private expanded content|data-slot="shimmer"/);
  }
  for (const value of [false, 0, '']) {
    const result = renderToStaticMarkup(React.createElement(ToolResultBody, { part: { ...output.parts[0], data: value } }));
    assert.ok(result.includes(value === '' ? '&quot;&quot;' : JSON.stringify(value)));
  }
  assert.match(render(buildReply(failedEmpty, [], []), false), /MODEL_NOT_CONFIGURED/);
  assert.match(render(buildReply(failedEmpty, [], []), false), /Current agent/);
  personaState.personas[0].name = 'Changed agent';
  assert.match(render(reply, false), /Changed agent/);
  assert.match(renderToStaticMarkup(React.createElement(MessageBubble, { message: answer })), /Changed agent/);
  personaState.personas = [];
  assert.ok(render(reply, false).includes(i18n.t('personas:deletedPersona')));
  assert.ok(renderToStaticMarkup(React.createElement(MessageBubble, { message: answer })).includes(i18n.t('personas:deletedPersona')));
  personaState.personas = [{ id: 'p', name: 'Current agent', avatar_attachment_id: null }];
  viewState = { ...viewState, currentSession: { ...session, user_persona: { id: 'user', name: 'Current user', avatar_attachment_id: null } } };
  const imageHtml = renderToStaticMarkup(React.createElement(MessageBubble, { message: imageOnly }));
  assert.match(imageHtml, /Current user/);
  viewState.currentSession.user_persona.name = 'Updated user';
  const renamedUser = renderToStaticMarkup(React.createElement(MessageBubble, { message: imageOnly }));
  assert.match(renamedUser, /Updated user/);
  assert.doesNotMatch(renamedUser, /Current user/);
  assert.match(imageHtml, /attachments\/aaaa.png/);
  assert.equal((imageHtml.match(/<img /g) || []).length, 1);
  assert.doesNotMatch(imageHtml, /base64/);
  assert.doesNotMatch(imageHtml, /data-slot="bubble"|data-slot="attachment-title"|data-slot="attachment-description"/);
  const fileHtml = renderToStaticMarkup(React.createElement(MessageBubble, { message: fileOnly }));
  assert.match(fileHtml, /notes.txt/);
  assert.match(fileHtml, /TXT · 12 B/);
  assert.doesNotMatch(fileHtml, /data-slot="bubble"/);
  const mixedHtml = renderToStaticMarkup(React.createElement(MessageBubble, { message: { ...user,
    metadata: { attachments: [...imageOnly.metadata.attachments, textFile] } } }));
  assert.ok(mixedHtml.indexOf('message-attachments') < mixedHtml.indexOf('data-slot="bubble"'));
  assert.ok(mixedHtml.lastIndexOf('message-attachments') > mixedHtml.indexOf('data-slot="bubble-content"'));
  assert.ok(mixedHtml.indexOf('notes.txt') < mixedHtml.indexOf('data-slot="bubble"'));
  assert.ok(mixedHtml.indexOf('alt="photo.png"') > mixedHtml.indexOf('data-slot="bubble-content"'));
  const composerHtml = renderToStaticMarkup(React.createElement(ChatAttachments, { composer: true,
    items: [...imageOnly.metadata.attachments, textFile], onRemove: () => {} }));
  assert.match(composerHtml, /data-orientation="vertical"/);
  assert.match(composerHtml, /data-orientation="horizontal"/);
  assert.match(composerHtml, /PNG · 1.1 KB/);
  assert.equal((composerHtml.match(/data-slot="attachment-action"/g) || []).length, 2);
  const warned = { ...imageOnly, metadata: { ...imageOnly.metadata,
    request_warnings: { run_id: 'r', codes: ['images_ignored', 'tools_ignored'] } } };
  const warningHtml = renderToStaticMarkup(React.createElement(MessageBubble, { message: warned }));
  assert.equal((warningHtml.match(/class="message-request-warning"/g) || []).length, 2);
  for (const code of warned.metadata.request_warnings.codes)
    assert.ok(warningHtml.includes(i18n.t(`chat:requestWarnings.${code}`)));
  assert.ok(warningHtml.indexOf('message-request-warning') > warningHtml.indexOf('message-attachments'));
  assert.equal(messagePreview(warned), messagePreview(imageOnly));
  const oversized = { ...failedEmpty, error_code: 'REQUEST_TOO_LARGE', error: 'Local chat request is too large.' };
  assert.ok(render(buildReply(oversized, [], []), false).includes(i18n.t('personas:imageErrors.tooLarge')));
}
console.log('reply projection, reasoning deltas, history pruning, late responses, approvals and bilingual rendering: ok');
