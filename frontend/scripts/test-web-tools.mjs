import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createModuleLoader } from './module-loader.mjs';

const load = createModuleLoader();
const { default: i18n } = (await load('../src/i18n/index.ts')).exports;
const { webSourcesForReply, citedWebSources, copyWebAnswer, readWebToolOutput } = (await load('../src/components/messages/webSources.ts')).exports;
const { MessageParts } = (await load('../src/components/messages/MessageParts.tsx')).exports;
const result = (tool_name, data, status = 'success') => ({ id: tool_name, type: 'tool_result', tool_name, status, data });
const one = { source_id: 'W1', url: 'https://example.com/article', title: 'First article', snippet: 'Summary' };
const two = { source_id: 'W2', url: 'https://example.org/', title: '' };
const results = result('web_search', { provider: 'anysearch', query: 'test', results: [one, two] });
const fetched = result('web_fetch', { ...one, title: 'Fetched article', content: '<script>Not executed</script>\nEvidence' });
const sources = webSourcesForReply([{ parts: [results, fetched] }]);
assert.deepEqual([...sources.keys()], ['W1', 'W2']);
assert.equal(sources.get('W1').title, 'Fetched article');
assert.deepEqual(webSourcesForReply([{ parts: [result('web_search', results.data, 'error')] }]), new Map());
assert.equal(readWebToolOutput(result('web_search', { results: [{ ...one, url: 'javascript:alert(1)' }] })), null);
assert.equal(readWebToolOutput(result('web_search', { results: [{ ...one, url: 'https://name:secret@example.com/' }] })), null);
assert.equal(readWebToolOutput(result('web_fetch', { ...one, content: 12 })), null);
assert.deepEqual(readWebToolOutput(result('web_search', { results: [] })), { pages: [] });
assert.equal(readWebToolOutput(fetched).content, fetched.data.content);

const part = (text, format = 'markdown') => ({ id: 'body', type: 'text', format, text });
const markdown = 'Second [W2], first [W1], repeated [W2]. Unknown [W99] and Knowledge [K1].\n\n' +
  'Code `[W1]` and [ordinary [W1]](https://elsewhere.test). Escaped \\[W1].\n\n```md\n[W1]\n```';
assert.deepEqual(citedWebSources([part(markdown)], sources).map((source) => source.source_id), ['W2', 'W1']);
const html = renderToStaticMarkup(React.createElement(MessageParts, { parts: [part(markdown)], webSources: sources }));
assert.equal((html.match(/data-web-citation=/g) || []).length, 3);
assert.match(html, /Unknown \[W99\] and Knowledge \[K1\]/);
assert.match(html, /<code>\[W1\]<\/code>/);
assert.match(html, /ordinary \[W1\]/);
assert.match(html, /Escaped \[W1\]/);
const copied = copyWebAnswer([part(markdown)], sources);
assert.match(copied, /Second \[example.org\]\(<https:\/\/example.org\/?>\)/);
assert.match(copied, /\[Fetched article\]\(<https:\/\/example.com\/article>\)/);
assert.match(copied, /Code `\[W1\]`/);
assert.match(copied, /\\\[W1\]/);
assert.match(copied, /```md\n\[W1\]\n```/);

for (const [text, count] of [['Evidence [', 0], ['Evidence [W', 0], ['Evidence [W1', 0], ['Evidence [W1]', 1]]) {
  const parts = [part(text)];
  const rendered = renderToStaticMarkup(React.createElement(MessageParts, { parts, webSources: sources }));
  assert.equal((rendered.match(/data-web-citation=/g) || []).length, count);
  assert.equal(citedWebSources(parts, sources).length, count);
}
for (const text of ['\\* &amp; [W1] after', '- First line\n  continued [W1] after', '| Col |\n| --- |\n| [W1] after |']) {
  const rendered = renderToStaticMarkup(React.createElement(MessageParts, { parts: [part(text)], webSources: sources }));
  assert.equal((rendered.match(/data-web-citation=/g) || []).length, 1);
  assert.match(rendered, /after/);
  assert.doesNotMatch(rendered, />\[W1\]</);
}
const plain = [part('Plain [W1] and `literal [W2]`.', 'plain')];
assert.equal(citedWebSources(plain, sources).length, 2);
assert.equal((renderToStaticMarkup(React.createElement(MessageParts, { parts: plain, webSources: sources })).match(/data-web-citation=/g) || []).length, 2);
assert.equal(citedWebSources([part('[W1]: https://elsewhere.test\n\nReference [W1].')], sources).length, 0);
const duplicate = new Map([...sources, ['W3', { ...one, source_id: 'W3' }]]);
assert.equal(citedWebSources([part('[W1] [W3]')], duplicate).length, 1);
assert.equal(citedWebSources([part('[W1]')], new Map()).length, 0);
const { request } = (await load('../src/api/http.ts')).exports;
const { toolsApi } = (await load('../src/api/tools.ts')).exports;
const originalFetch = globalThis.fetch;
const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url, options });
  return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
};
try {
  await i18n.changeLanguage('zh-CN');
  await request('/api/sessions/test/messages', { method: 'POST', body: '{}' });
  assert.equal(calls.at(-1).options.headers.get('X-UI-Language'), 'zh-CN');
  await i18n.changeLanguage('en');
  await request('/api/runs/test/retry', { method: 'POST' });
  assert.equal(calls.at(-1).options.headers.get('X-UI-Language'), 'en');
  await toolsApi.patchWebSettings({ max_results: 3, zone: 'intl', language: null });
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), { max_results: 3, zone: 'intl', language: null });
} finally { globalThis.fetch = originalFetch; }
console.log('Web settings, UI language headers, citation rendering, streaming, Markdown and copy checks passed.');
