import assert from 'node:assert/strict';
import { createModuleLoader } from './module-loader.mjs';

const load = createModuleLoader();
const { contextPresentation } = (await load('../src/components/messages/contextPresentation.ts')).exports;
const source = (id, kind, parent_id) => ({ id, kind, parent_id, text: 'hello', char_count: 5 });
const detail = { sources: [source('sys', 'system'), source('character', 'character', 'sys'), source('current', 'current_input')],
  exclusions: [{ kind: 'persona', reason: 'empty', reference_id: 'user' }, { kind: 'history', reason: 'message_limit' }] };
const original = JSON.stringify(detail);
let view = contextPresentation(detail);
assert.deepEqual(view.byParent.get('sys').map((item) => item.kind), ['character', 'persona']);
assert.equal(view.exclusions.length, 1);
const instructed = contextPresentation({ ...detail, sources: [...detail.sources, source('instruction', 'instruction', 'sys')] });
assert.deepEqual(instructed.byParent.get('sys').map((item) => item.kind), ['instruction', 'character', 'persona']);
assert.equal(view.sources.find((item) => item.kind === 'persona').reference_id, 'user');
assert.equal(JSON.stringify(detail), original);
view = contextPresentation({ sources: [], exclusions: ['persona', 'character'].map((kind) => ({ kind, reason: 'empty' })) });
assert.deepEqual(view.byParent.get('empty:system').map((item) => item.kind), ['character', 'persona']);
assert.equal(view.sources[0].message_index, undefined);
assert.ok(view.sources.every((item) => item.empty && item.char_count === 0));
assert.equal(view.exclusions.length, 0);
view = contextPresentation({ sources: [source('sys', 'system'), source('qq', 'qq_runtime', 'sys'),
  source('character', 'character', 'sys'), source('input', 'current_input')], exclusions: [] });
assert.deepEqual(view.byParent.get('sys').map((item) => item.kind), ['character', 'qq_runtime']);

// Actual offsets own ordering; the two instruction blocks occupy different positions.
const positioned = (id, kind, start, parent_id = 'sys') => ({ ...source(id, kind, parent_id), message_index: 0, start, end: start + 5 });
view = contextPresentation({ sources: [source('sys', 'system'), positioned('memory-index', 'memory_index', 200),
  positioned('history-instruction', 'instruction', 300), positioned('instruction', 'instruction', 0),
  positioned('memory-instruction', 'memory_instruction', 100), positioned('character', 'character', 40),
  positioned('general', 'durable_memory', 250, 'memory-index'), positioned('own', 'durable_memory', 220, 'memory-index')],
  exclusions: [{ kind: 'persona', reason: 'empty' }] });
assert.deepEqual(view.byParent.get('sys').map((item) => item.id), ['instruction', 'character', 'empty:persona',
  'memory-instruction', 'memory-index', 'history-instruction']);
assert.deepEqual(view.byParent.get('memory-index').map((item) => item.id), ['own', 'general']);

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
