import assert from 'node:assert/strict';
import { createModuleLoader } from './module-loader.mjs';

const load = createModuleLoader();
const { contextPresentation } = (await load('../src/components/messages/contextPresentation.ts')).exports;
const source = (id, kind, parent_id) => ({ id, kind, parent_id, text: 'hello', char_count: 5 });
const detail = { sources: [source('sys', 'system'), source('agent', 'agent_persona', 'sys'), source('current', 'current_input')],
  exclusions: [{ kind: 'knowledge', reason: 'no_bindings' }, { kind: 'cogita_persona', reason: 'empty', reference_id: 'cogita' },
    { kind: 'history', reason: 'message_limit' }] };
const original = JSON.stringify(detail);
let view = contextPresentation(detail);
assert.deepEqual(view.byParent.get('sys').map((item) => item.kind), ['agent_persona', 'cogita_persona', 'knowledge']);
assert.equal(view.sources.find((item) => item.kind === 'project_prompt'), undefined);
assert.equal(view.exclusions.length, 1);
assert.equal(view.sources.find((item) => item.kind === 'cogita_persona').reference_id, 'cogita');
assert.equal(JSON.stringify(detail), original);
view = contextPresentation({ sources: [], exclusions: ['knowledge', 'cogita_persona', 'project_prompt', 'agent_persona']
  .map((kind) => ({ kind, reason: 'empty' })) });
assert.deepEqual(view.byParent.get('empty:system').map((item) => item.kind), ['agent_persona', 'project_prompt', 'cogita_persona', 'knowledge']);
assert.equal(view.sources[0].message_index, undefined);
assert.ok(view.sources.every((item) => item.empty && item.char_count === 0));
assert.equal(view.exclusions.length, 0);
assert.equal(contextPresentation({ sources: [], exclusions: [{ kind: 'knowledge', reason: 'retrieval_failed' }] }).sources.length, 0);

let response;
globalThis.self = { postMessage: (value) => { response = value; } };
await load('../src/components/messages/contextTokens.worker.ts');
self.onmessage({ data: { key: 'run:step', sources: [
  { id: 'empty', text: '' }, { id: 'english', text: 'Hello, world!' }, { id: 'chinese', text: '你好，世界！' },
  { id: 'code', text: 'const x = 42;\n' }, { id: 'emoji', text: '😀🚀' }, { id: 'special', text: '<|endoftext|>' },
] } });
assert.equal(response.key, 'run:step');
assert.deepEqual(response.counts, { empty: 0, english: 4, chinese: 4, code: 6, emoji: 3, special: 7 });
delete globalThis.self;
console.log('Context empty-source projection, immutable inputs, source order and multilingual reference tokenization passed.');
