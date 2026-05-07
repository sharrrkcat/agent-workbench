import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/api/url.ts', import.meta.url), 'utf8');
const transformed = source
  .replace("export const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api';", "const rawApiBaseUrl = '/api';")
  .replace(/\bexport /g, '')
  .replace(/: string \| null \| undefined/g, '')
  .replace(/: string/g, '')
  .replace(/`\/\$\{withoutApiPrefix\}`/g, '`/${withoutApiPrefix}`')
  .concat('\nexports.joinApiUrl = joinApiUrl;')
  .concat('\nexports.createWebSocketUrlFromBase = createWebSocketUrlFromBase;')
  .concat('\nexports.resolveAttachmentUrlFromBase = resolveAttachmentUrlFromBase;')
  .concat('\nexports.resolveAvatarUrlFromBase = resolveAvatarUrlFromBase;');

const context = { exports: {}, URL };
vm.runInNewContext(transformed, context, { filename: 'url.ts' });

const {
  joinApiUrl,
  createWebSocketUrlFromBase,
  resolveAttachmentUrlFromBase,
  resolveAvatarUrlFromBase,
} = context.exports;

assert.equal(joinApiUrl('/api', '/attachments/x'), '/api/attachments/x');
assert.equal(joinApiUrl('/api', '/api/attachments/x'), '/api/attachments/x');
assert.equal(joinApiUrl('http://127.0.0.1:8000/api', '/attachments/x'), 'http://127.0.0.1:8000/api/attachments/x');
assert.equal(joinApiUrl('http://127.0.0.1:8000/api', '/api/attachments/x'), 'http://127.0.0.1:8000/api/attachments/x');

assert.equal(resolveAttachmentUrlFromBase('/api', 'local://attachments/x.md'), '/api/attachments/x.md');
assert.equal(resolveAttachmentUrlFromBase('/api', '/api/attachments/x.md'), '/api/attachments/x.md');
assert.equal(resolveAttachmentUrlFromBase('/api', 'data:image/png;base64,aaaa'), 'data:image/png;base64,aaaa');
assert.equal(resolveAttachmentUrlFromBase('/api', 'data:text/html;base64,aaaa'), '');
assert.equal(resolveAttachmentUrlFromBase('/api', 'javascript:alert(1)'), '');
assert.equal(resolveAttachmentUrlFromBase('/api', 'file:///tmp/x.png'), '');

assert.equal(resolveAvatarUrlFromBase('/api', '/api/agents/chat/avatar'), '/api/agents/chat/avatar');
assert.equal(resolveAvatarUrlFromBase('http://127.0.0.1:8000/api', '/api/agents/chat/avatar'), 'http://127.0.0.1:8000/api/agents/chat/avatar');
assert.equal(resolveAvatarUrlFromBase('/api', 'javascript:alert(1)'), '');

assert.equal(createWebSocketUrlFromBase('/api', 'session-1', 'http://127.0.0.1:8765'), 'ws://127.0.0.1:8765/api/ws/session-1');
assert.equal(createWebSocketUrlFromBase('http://127.0.0.1:8000/api', 'session-1', 'http://127.0.0.1:5173'), 'ws://127.0.0.1:8000/api/ws/session-1');

console.log('[OK] URL helper tests passed');
