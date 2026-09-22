import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { apiMocks, createModuleLoader } from './module-loader.mjs';

const load = createModuleLoader();
for (const filename of ['lib/utils.ts', 'components/ui/button.tsx', 'i18n/resources/en/common.json']) {
  const alias = await load(`@/${filename}`);
  const relative = await load(`../src/${filename}`);
  assert.equal(alias.url, relative.url);
  assert.equal(alias.exports, relative.exports);
}

const { cn } = (await load('@/lib/utils')).exports;
assert.equal(cn('h-7', false, { 'h-8': true }), 'h-8');
const { Button } = (await load('@/components/ui/button')).exports;
const { default: common } = (await load('@/i18n/resources/en/common.json')).exports;
assert.equal(common.save, 'Save');
assert.match(renderToStaticMarkup(React.createElement(Button, null, common.save)), /^<button\b[^>]*>Save<\/button>$/);

let calls = 0;
const api = { listSessions: async () => { calls += 1; return [{ session_id: 'aliased' }]; } };
const mocked = createModuleLoader(apiMocks(api));
const alias = await mocked('@/api/chat');
const relative = await mocked('../src/api/chat.ts');
assert.equal(alias.url, relative.url);
assert.equal(alias.exports.chatApi, api);
assert.equal(relative.exports.chatApi, api);
const graph = (await mocked('./fixtures/module-aliases.ts')).exports;
assert.equal(graph.cn, cn);
assert.equal(graph.Button, Button);
assert.deepEqual(graph.common, common);
assert.equal(graph.aliasApi, api);
assert.equal(graph.relativeApi, api);
assert.deepEqual(await graph.aliasApi.listSessions(), [{ session_id: 'aliased' }]);
assert.deepEqual(await graph.relativeApi.listSessions(), [{ session_id: 'aliased' }]);
assert.equal(calls, 2);

console.log('[OK] Module aliases load TS, TSX and JSON and share API mocks');
