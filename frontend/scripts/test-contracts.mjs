import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { createModuleLoader, mockModule } from './module-loader.mjs';

const resources = Object.fromEntries(
  ['en', 'zh-CN'].map((locale) => [
    locale,
    Object.fromEntries(
      ['common', 'settings', 'knowledge', 'worldbook', 'personas', 'runs', 'renderers'].map((namespace) => [
        namespace,
        JSON.parse(
          fs.readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'),
        ),
      ]),
    ),
  ]),
);
const i18n = i18next.createInstance();
await i18n.init({ resources, lng: 'en', fallbackLng: 'en', interpolation: { escapeValue: false } });
const load = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
});
const { settingsSections, readSettingsSection, settingsSectionUrl } = (
  await load('../src/components/settings/navigation.ts')
).exports;
assert.deepEqual(settingsSections, ['general', 'models', 'personas', 'knowledge', 'worldbook', 'tools']);
for (const section of settingsSections)
  assert.equal(readSettingsSection(new URL(settingsSectionUrl(section), 'http://localhost').search), section);
for (const tab of ['', '?tab=unknown', '?tab=agents', '?tab=capabilities', '?tab=pet'])
  assert.equal(readSettingsSection(tab), 'general');

const { settingsApi } = (await load('../src/api/settings.ts')).exports;
const { modelsApi } = (await load('../src/api/models.ts')).exports;
const { toolsApi } = (await load('../src/api/tools.ts')).exports;
const { ApiError } = (await load('../src/api/http.ts')).exports;
const requests = [];
globalThis.fetch = async (url, options) => {
  requests.push({ url, method: options.method, body: JSON.parse(options.body) });
  return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
};
await settingsApi.updatePetSettings({ position: { x: 12 } });
assert.deepEqual(requests.at(-1), {
  url: '/api/pets/settings',
  method: 'PATCH',
  body: { values: { position: { x: 12 } } },
});
await modelsApi.patchProviderProfile('provider/1', { name: 'Renamed' });
assert.equal(requests.at(-1).url, '/api/models/providers/provider%2F1');
assert.equal('api_key' in requests.at(-1).body, false);
await modelsApi.patchProviderProfile('provider/1', { api_key: '' });
assert.equal(requests.at(-1).body.api_key, '');
await toolsApi.callTool('read_file', 'session', { path: 'data/knowledge/note.txt' });
assert.deepEqual(requests.at(-1).body, { session_id: 'session', arguments: { path: 'data/knowledge/note.txt' } });
await toolsApi.resolveToolApproval('run/1', 'reject');
assert.equal(requests.at(-1).url, '/api/tools/approvals/run%2F1');
assert.deepEqual(requests.at(-1).body, { decision: 'reject' });
globalThis.fetch = async () =>
  new Response(JSON.stringify({ error: { code: 'MODEL_BUSY', message: 'Busy' } }), { status: 409 });
await assert.rejects(
  modelsApi.modelAction('model', 'load'),
  (error) => error instanceof ApiError && error.code === 'MODEL_BUSY',
);

const { GeneralSettingsForm } = (await load('../src/components/settings/GeneralPanel.tsx')).exports;
const settings = {
  show_full_processing: false,
  core_memory_enabled: true,
  core_memory_content: 'Remember this',
  auto_generate_session_titles: false,
  session_title_max_input_chars: 1234,
  group_transcript_system_instruction: null,
  pet: { position: { mode: 'default', x: null, y: null } },
  max_file_size_mb: 42,
};
function descendants(node) {
  if (Array.isArray(node)) return node.flatMap(descendants);
  if (!React.isValidElement(node)) return [];
  return [node, ...descendants(node.props.children)];
}
let saved;
const form = GeneralSettingsForm({
  settings,
  onChange: () => {},
  onSave: (patch) => {
    saved = patch;
  },
});
descendants(form)
  .find((node) => node.type === 'button')
  .props.onClick();
assert.deepEqual(saved, {
  show_full_processing: false,
  core_memory_enabled: true,
  core_memory_content: 'Remember this',
  auto_generate_session_titles: false,
  session_title_max_input_chars: 1234,
  group_transcript_system_instruction: null,
});
for (const [locale, label] of [
  ['en', 'Save general settings'],
  ['zh-CN', '保存常规设置'],
]) {
  await i18n.changeLanguage(locale);
  const html = renderToStaticMarkup(
    React.createElement(GeneralSettingsForm, { settings, onChange: () => {}, onSave: () => {} }),
  );
  assert.ok(html.includes(label));
  assert.ok(html.includes('Remember this'));
  assert.doesNotMatch(html, /appearance_font|resource_status|generalFields\./);
}

console.log('settings navigation/submission, API boundaries and bilingual rendering: ok');
