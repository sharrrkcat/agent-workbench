import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const moduleUrl = (source) => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }
async function load(relative, imports) {
  const source = fs.readFileSync(new URL(relative, import.meta.url), 'utf8');
  let output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  for (const [name, url] of Object.entries({ ...imports, 'react/jsx-runtime': import.meta.resolve('react/jsx-runtime') })) {
    output = output.replaceAll('from ' + JSON.stringify(name), 'from ' + JSON.stringify(url)).replaceAll("from '" + name + "'", 'from ' + JSON.stringify(url));
  }
  const url = moduleUrl(output);
  return { url, exports: await import(url) };
}
const api = {};
globalThis.harnessTestApi = api;
const client = moduleUrl('export const api = globalThis.harnessTestApi; export const API_BASE_URL = ""; export class ApiError extends Error {}');
const stream = await load('../src/store/messageStream.ts', {});
const storeModule = await load('../src/store/useWorkbenchStore.ts', {
  zustand: import.meta.resolve('zustand'), '../api/client': client, './messageStream': stream.url,
  './useModelsStore': moduleUrl('export const useModelsStore = { getState: () => ({ reload: async () => {} }) };'),
});
const store = storeModule.exports.useWorkbenchStore;
const at = (microseconds) => '2026-09-07T00:00:00.' + microseconds.padStart(6, '0') + 'Z';
const session = { session_id: 's', title: 'Chat', updated_at: at('0'), waiting_run_id: null, effective: { tools_allowed: ['read_file'] } };
const run = { run_id: 'r', session_id: 's', kind: 'tool', status: 'RUNNING', created_at: at('0'), updated_at: at('1') };
const waiting = { ...run, status: 'WAITING_FOR_USER', updated_at: at('2') };
const resumed = { ...run, updated_at: at('3') };
const done = { ...run, status: 'DONE', updated_at: at('4') };
const part = { id: 'call', type: 'tool_call', tool_call_id: 'call_1', tool_name: 'read_file', arguments: { path: 'data/knowledge/note.txt' } };
const call = { message_id: 'call-message', session_id: 's', role: 'assistant', run_id: 'r', parts: [part], created_at: at('1') };
const result = { ...call, message_id: 'result-message', role: 'tool', parts: [{ ...part, type: 'tool_result', status: 'success', data: { text: 'result' } }] };
const step = { step_id: 'approval', run_id: 'r', kind: 'approval', status: 'running', order: 1, updated_at: at('2'), metadata: { tool_call_id: 'call_1', risk: 'file' } };
const event = (type, payload, messageId) => ({ type, session_id: 's', run_id: 'r', message_id: messageId, payload });
store.setState({ currentSession: session, sessions: [session], messages: [], runs: [run], stepsByRunId: {}, resolvingApprovals: [] });
const pendingRefresh = deferred();
api.getSession = async () => session;
api.listMessages = () => pendingRefresh.promise;
api.listRuns = async () => [run];
const refresh = store.getState().refreshCurrent();
store.getState().applyRuntimeEvent(event('tool_call_created', { message: call }, call.message_id));
store.getState().applyRuntimeEvent(event('tool_call_created', { message: call }, call.message_id));
store.getState().applyRuntimeEvent(event('run_step_created', { step }));
store.getState().applyRuntimeEvent(event('approval_requested', { run: waiting }));
pendingRefresh.resolve([]);
await refresh;
assert.equal(store.getState().messages.length, 1);
assert.equal(store.getState().currentSession.waiting_run_id, 'r');
assert.equal(store.getState().runs[0].status, 'WAITING_FOR_USER');
assert.equal(store.getState().stepsByRunId.r[0].status, 'running');

store.getState().applyRuntimeEvent(event('approval_resolved', { run: resumed }));
store.getState().applyRuntimeEvent(event('run_step_updated', { step: { ...step, status: 'completed', updated_at: at('3') } }));
store.getState().applyRuntimeEvent(event('approval_requested', { run: waiting }));
store.getState().applyRuntimeEvent(event('run_step_created', { step }));
assert.equal(store.getState().currentSession.waiting_run_id, null);
assert.equal(store.getState().runs[0].status, 'RUNNING');
assert.equal(store.getState().stepsByRunId.r[0].status, 'completed');
store.getState().applyRuntimeEvent(event('tool_result_created', { message: result }, result.message_id));
store.getState().applyRuntimeEvent(event('tool_result_created', { message: result }, result.message_id));
store.getState().applyRuntimeEvent(event('message_delta', { delta: 'late', seq: 1 }, result.message_id));
assert.equal(store.getState().messages.length, 2);
assert.equal(store.getState().messages[1].parts[0].data.text, 'result');
api.listMessages = async () => [call, result];
api.listRuns = async () => [done];
store.getState().applyRuntimeEvent(event('run_completed', { run: done }));
store.getState().applyRuntimeEvent(event('approval_requested', { run: { ...waiting, updated_at: at('5') } }));
assert.equal(store.getState().runs[0].status, 'DONE');
assert.equal(store.getState().currentSession.waiting_run_id, null);
await new Promise((resolve) => setTimeout(resolve, 0));

const approvalResponse = deferred();
let approvalCalls = 0;
api.resolveToolApproval = () => { approvalCalls += 1; return approvalResponse.promise; };
store.setState({ currentSession: { ...session, waiting_run_id: 'r' }, runs: [waiting], messages: [call] });
const approval = store.getState().resolveApproval('r', 'approve');
await store.getState().resolveApproval('r', 'approve');
assert.equal(approvalCalls, 1);
assert.deepEqual(store.getState().resolvingApprovals, ['r']);
const other = { ...session, session_id: 'other' };
store.setState({ currentSession: other, messages: [], runs: [], stepsByRunId: {} });
approvalResponse.resolve({ run: done, messages: [call, result], session });
await approval;
assert.deepEqual(store.getState().messages, []);
assert.deepEqual(store.getState().runs, []);
assert.equal(store.getState().currentSession.session_id, 'other');
assert.deepEqual(store.getState().resolvingApprovals, []);

store.setState({ currentSession: session, sessions: [session], messages: [], runs: [], stepsByRunId: {} });
api.callTool = async () => ({ run: { ...waiting, steps: [step] }, messages: [call], session: { ...session, waiting_run_id: 'r' } });
await store.getState().callTool('read_file', part.arguments);
assert.equal(store.getState().messages[0].parts[0].tool_name, 'read_file');
assert.equal(store.getState().currentSession.waiting_run_id, 'r');
assert.equal(store.getState().sending, false);
console.log('harness events, stale refresh, microsecond ordering, approvals and session isolation: ok');

const locale = JSON.parse(fs.readFileSync(new URL('../src/i18n/resources/en/runs.json', import.meta.url), 'utf8'));
globalThis.harnessTestTranslate = (key) => key.split('.').reduce((value, name) => value?.[name], locale) || key;
globalThis.harnessTestState = { ...store.getState(), messages: [call], stepsByRunId: { r: [step] } };
const translation = moduleUrl('export function useTranslation() { return { t: globalThis.harnessTestTranslate }; }');
const stateModule = moduleUrl('export const useWorkbenchStore = (select) => select(globalThis.harnessTestState);');
const imports = { react: import.meta.resolve('react'), 'react-i18next': translation, 'lucide-react': import.meta.resolve('lucide-react'), '../store/useWorkbenchStore': stateModule };
const panel = (await load('../src/components/RunPanel.tsx', imports)).exports.RunPanel;
const html = renderToStaticMarkup(React.createElement(panel, { run: waiting }));
assert.match(html, /Approve/);
assert.match(html, /Reject/);
assert.match(html, /data\/knowledge\/note.txt/);
assert.match(html, /aria-label="Cancel"/);
globalThis.harnessTestState.resolvingApprovals = ['r'];
const busy = renderToStaticMarkup(React.createElement(panel, { run: waiting }));
assert.match(busy, /Resuming/);
assert.equal((busy.match(/disabled=""/g) || []).length, 2);
const messageParts = (await load('../src/components/MessageBubble.tsx', {
  ...imports, 'react-markdown': import.meta.resolve('react-markdown'), 'remark-gfm': import.meta.resolve('remark-gfm'),
  '../api/client': client, '../api/url': moduleUrl('export const resolveAttachmentUrlFromBase = (_base, url) => url;'),
})).exports.MessageParts;
const rendered = renderToStaticMarkup(React.createElement(messageParts, { parts: [{
  id: 'result', type: 'tool_result', tool_name: 'read_file', tool_call_id: 'call_1', status: 'error',
  data: { text: '<script>window.invalid=true</script>' }, error_code: 'TOOL_ERROR', error_message: 'failed', truncated: true,
}] }));
assert.doesNotMatch(rendered, /<script>/);
assert.match(rendered, /&lt;script&gt;/);
assert.match(rendered, /Output truncated/);
assert.match(rendered, /TOOL_ERROR/);
assert.match(rendered, /Failed/);
console.log('tool data rendering, approval details, disabled controls and translated labels: ok');
delete globalThis.harnessTestApi;
delete globalThis.harnessTestState;
delete globalThis.harnessTestTranslate;
