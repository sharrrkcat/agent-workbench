import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { createModuleLoader, mockModule } from './module-loader.mjs';

const i18n = i18next.createInstance();
const resources = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale, Object.fromEntries(['settings', 'common', 'knowledge', 'worldbook'].map((ns) => [ns,
  JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/${ns}.json`, import.meta.url), 'utf8'))]))]));
await i18n.init({ resources, lng: 'en', fallbackLng: 'en', interpolation: { escapeValue: false } });
const load = createModuleLoader({ 'react-i18next': mockModule({ useTranslation: (ns) => ({ t: i18n.getFixedT(null, ns), i18n }) }) });
const { worldbookSettingsInput } = (await load('../src/components/settings/worldbook/WorldbookDefaults.tsx')).exports;
const { knowledgeSettingsInput } = (await load('../src/components/settings/knowledge/KnowledgeDefaults.tsx')).exports;
const { knowledgeBaseInput } = (await load('../src/components/settings/knowledge/KnowledgeDetail.tsx')).exports;
const { entryInput } = (await load('../src/components/settings/worldbook/WorldbookEntries.tsx')).exports;
const { KnowledgeModelSelect } = (await load('../src/components/settings/knowledge/KnowledgeModelSelect.tsx')).exports;
const { WorldbookEntryCard } = (await load('../src/components/settings/worldbook/WorldbookEntryCard.tsx')).exports;
const { worldbookApi } = (await load('../src/api/worldbook.ts')).exports;
const { knowledgeApi } = (await load('../src/api/knowledge.ts')).exports;

const editable = { worldbook_enabled: true, worldbook_max_entries_per_call: 20, worldbook_max_context_chars: 8000,
  worldbook_case_sensitive: true, worldbook_regex_case_insensitive: false, worldbook_whole_words: true, worldbook_recursion_depth: 2 };
assert.deepEqual(worldbookSettingsInput({ ...editable, id: 1, created_at: 'time', updated_at: 'time' }), editable);
assert.deepEqual(knowledgeSettingsInput({ id: 1, default_min_score: null, min_score_threshold: 0.2 }), { default_min_score: null, min_score_threshold: 0.2 });
const base = knowledgeBaseInput({ id: 'base', name: 'Facts', embedding_model_profile_id: 'embedding', final_top_k_override: null, index_status: 'ready' });
assert.equal('id' in base, false); assert.equal('index_status' in base, false); assert.equal(base.final_top_k_override, null);
const draft = entryInput({ id: 'entry', name: 'Alpha', keywords_text: 'alpha', content: 'Saved content', activation_mode: 'keyword', enabled: true, sort_order: 10 });
assert.equal('sort_order' in draft, false);

const requests = [];
globalThis.fetch = async (url, options = {}) => {
  requests.push({ url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : undefined });
  return new Response(JSON.stringify({ source_id: 'source', chunks: 3, status: 'indexed' }), { status: 200 });
};
await worldbookApi.updateWorldbookSettings(worldbookSettingsInput({ ...editable, id: 1 }));
assert.deepEqual(requests.at(-1).body, editable);
await worldbookApi.reorderWorldbookEntries('book/1', ['b', 'a']);
assert.deepEqual(requests.at(-1), { url: '/api/worldbooks/book%2F1/entries/reorder', method: 'PATCH', body: { entry_ids: ['b', 'a'] } });
await worldbookApi.matchWorldbooks({ text: 'alpha', worldbook_ids: ['book'] });
assert.equal(requests.at(-1).url, '/api/worldbooks/match-test');
const result = await knowledgeApi.createAttachmentKnowledgeSource('base/1', 'file.txt', 'File');
assert.equal(result.source_id, 'source');
assert.deepEqual(requests.at(-1).body, { source_type: 'attachment_text', attachment_id: 'file.txt', title: 'File' });
await knowledgeApi.listKnowledgeSourceChunks('source/1');
assert.equal(requests.at(-1).url, '/api/knowledge/sources/source%2F1/chunks');

for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const props = { id: 'entry', draft, expanded: true, dirty: true, busy: '', locked: false, dragging: false,
    onToggle() {}, onUpdate() {}, onEnabled() {}, onSave() {}, onReset() {}, onDelete() {} };
  const html = renderToStaticMarkup(React.createElement(WorldbookEntryCard, props));
  assert.match(html, /role="switch"/); assert.match(html, /aria-expanded="true"/);
  assert.ok(html.includes(i18n.t('content', { ns: 'worldbook' })));
  assert.ok(html.includes('Saved content'));
  assert.ok(html.indexOf('drag-handle') < html.indexOf('worldbook-entry-toggle-cell'));
  assert.ok(html.indexOf('worldbook-entry-form-row') < html.indexOf('textarea'));
  const missing = renderToStaticMarkup(React.createElement(KnowledgeModelSelect, { kind: 'embedding', value: 'missing', models: [], onChange() {} }));
  assert.match(missing, /value="missing" disabled="" selected=""/);
  assert.ok(missing.includes(i18n.t('missingModel', { ns: 'knowledge' })));
}
console.log('resource input contracts, API methods, entry structure and bilingual model states: ok');
