import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/store/messageStream.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { applyMessageEvent } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));

const message = { message_id: 'm', session_id: 's', role: 'assistant', parts: [], run_id: 'r', created_at: '2026-09-05T00:00:00Z' };
const event = (type, payload) => ({ type, message_id: 'm', session_id: 's', run_id: 'r', payload });
let state = applyMessageEvent([], event('message_started', { message }));
state = applyMessageEvent(state, event('message_delta', { seq: 1, delta: 'hello' }));
assert.equal(state[0].parts[0].text, 'hello');
assert.equal(applyMessageEvent(state, event('message_delta', { seq: 1, delta: 'duplicate' })), state);
assert.equal(applyMessageEvent(state, event('message_delta', { seq: 3, delta: 'gap' })), state);
state = applyMessageEvent(state, event('message_delta', { seq: 2, delta: ' world' }));
assert.equal(state[0].parts[0].text, 'hello world');
const final = { ...message, parts: [{ id: 'text', type: 'text', text: 'final canonical text' }], metadata: { streamed: true } };
state = applyMessageEvent(state, event('message_completed', { message: final }));
assert.deepEqual(state, [final]);
assert.equal(applyMessageEvent(state, event('message_delta', { seq: 3, delta: 'late' })), state);
assert.equal(applyMessageEvent(state, event('message_started', { message })), state);
assert.equal(applyMessageEvent(state, event('message_completed', { message: { ...final, session_id: 'other' } })), state);
assert.deepEqual(applyMessageEvent([], event('message_delta', { seq: 1, delta: 'orphan' })), []);
assert.deepEqual(applyMessageEvent([], event('message_completed', { message: final })), [final]);
console.log('model streaming behavior: ok');

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

const dataModule = (code) => 'data:text/javascript;base64,' + Buffer.from(code).toString('base64');
const mockApi = {};
globalThis.workbenchTestApi = mockApi;
const clientModule = dataModule('export const api = globalThis.workbenchTestApi; export class ApiError extends Error {}');

async function loadStore(path, imports) {
  const source = fs.readFileSync(new URL(path, import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    transformers: { before: [(context) => (root) => {
      function visit(node) {
        if (ts.isImportDeclaration(node) && imports[node.moduleSpecifier.text]) {
          return ts.factory.updateImportDeclaration(node, node.modifiers, node.importClause,
            ts.factory.createStringLiteral(imports[node.moduleSpecifier.text]), node.attributes);
        }
        return ts.visitEachChild(node, visit, context);
      }
      return ts.visitNode(root, visit);
    }] },
  }).outputText;
  const url = dataModule(compiled);
  return { url, exports: await import(url) };
}

const commonImports = { zustand: import.meta.resolve('zustand'), '../api/client': clientModule };
const modelsModule = await loadStore('../src/store/useModelsStore.ts', commonImports);
const modelsStore = modelsModule.exports.useModelsStore;
const idle = { state: 'ready', residency: 'unknown', unload_supported: false, active: 0, queued: 0 };
mockApi.listProviderProfiles = async () => [];
mockApi.getModelSettings = async () => ({ default_model_profile_id: null });
mockApi.getModelStatus = async () => idle;
const oldProfiles = deferred();
let profileReads = 0;
mockApi.listModelProfiles = () => ++profileReads === 1 ? oldProfiles.promise : Promise.resolve([{ id: 'new' }]);
const firstReload = modelsStore.getState().reload();
await modelsStore.getState().reload();
oldProfiles.resolve([{ id: 'old' }]);
await firstReload;
assert.equal(modelsStore.getState().profiles[0].id, 'new');

const statusRead = deferred();
const statusStarted = deferred();
mockApi.getModelStatus = () => { statusStarted.resolve(); return statusRead.promise; };
const statusReload = modelsStore.getState().reload();
await statusStarted.promise;
modelsStore.getState().setStatus('new', { ...idle, active: 2 });
statusRead.resolve(idle);
await statusReload;
assert.equal(modelsStore.getState().statuses.new.active, 2);

mockApi.runtimeCatalog = async () => [{ runtime_id: 'python-worker', variant: 'torch-cpu' }];
mockApi.runtimeInstallations = async () => [{ id: 'python-worker/torch-cpu', state: 'not_installed' }];
const jobsRead = deferred();
mockApi.runtimeJobs = () => jobsRead.promise;
const runtimeReload = modelsStore.getState().reloadRuntimes();
const job = { id: 'job', runtime_id: 'python-worker', variant: 'torch-cpu', state: 'running', stage: 'installing_packages', created_at: '2026-09-05T00:00:00Z', revision: 2 };
modelsStore.getState().applyModelEvent({ type: 'runtime_job_updated', session_id: '', payload: { job } });
modelsStore.getState().applyModelEvent({ type: 'runtime_status', session_id: '', payload: { installation: { id: 'python-worker/torch-cpu', state: 'installing' } } });
jobsRead.resolve([{ ...job, state: 'queued', revision: 1 }]);
await runtimeReload;
assert.equal(modelsStore.getState().jobs[0].state, 'running');
assert.equal(modelsStore.getState().installations[0].state, 'installing');
modelsStore.getState().setJob({ ...job, state: 'cancelled', revision: 3 });
modelsStore.getState().setJob(job);
assert.equal(modelsStore.getState().jobs[0].state, 'cancelled');
modelsStore.getState().setJob({ ...job, id: 'retry', revision: 1, created_at: '2026-09-05T00:01:00Z' });
assert.equal(modelsStore.getState().jobs[0].id, 'retry');
modelsStore.getState().applyModelEvent({ type: 'model_status', session_id: '', payload: { model_profile_id: 'new', status: { ...idle, active: 1 } } });
assert.equal(modelsStore.getState().statuses.new.active, 1);
console.log('runtime progress, stale reads, cancellation, retry history and global events: ok');

const workbenchModule = await loadStore('../src/store/useWorkbenchStore.ts', {
  ...commonImports, './useModelsStore': modelsModule.url, './messageStream': dataModule(compiled),
});
const workbench = workbenchModule.exports.useWorkbenchStore;
const session = { session_id: 's', title: '', model_profile_id: null };
workbench.setState({ currentSession: session, sessions: [session], messages: [], runs: [] });
mockApi.getSession = async () => session;
const historyRead = deferred();
mockApi.listMessages = () => historyRead.promise;
mockApi.listRuns = async () => [{ run_id: 'r', session_id: 's', status: 'RUNNING' }];
const historyRefresh = workbench.getState().refreshCurrent();
workbench.getState().applyRuntimeEvent(event('message_started', { message }));
workbench.getState().applyRuntimeEvent(event('message_delta', { seq: 1, delta: 'live' }));
historyRead.resolve([]);
await historyRefresh;
assert.equal(workbench.getState().messages[0].parts[0].text, 'live');
workbench.getState().applyRuntimeEvent(event('message_completed', { message: final }));
workbench.getState().applyRuntimeEvent(event('message_delta', { seq: 2, delta: 'late' }));
assert.deepEqual(workbench.getState().messages, [final]);

const previousSessionRead = deferred();
mockApi.listMessages = () => previousSessionRead.promise;
const oldSessionRefresh = workbench.getState().refreshCurrent();
workbench.setState({ currentSession: { session_id: 'other' }, messages: [] });
previousSessionRead.resolve([final]);
await oldSessionRefresh;
assert.deepEqual(workbench.getState().messages, []);
assert.equal(workbench.getState().currentSession.session_id, 'other');
delete globalThis.workbenchTestApi;
console.log('model reload, live status, chat refresh and session isolation: ok');
