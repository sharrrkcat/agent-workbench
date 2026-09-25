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
const { settingsSections, settingsGroups, readSettingsRoute, settingsRouteUrl } = (
  await load('../src/components/settings/navigation.ts')
).exports;
assert.deepEqual(settingsSections, ['general', 'models', 'personas', 'knowledge', 'worldbook', 'tools']);
const settingsPages = settingsGroups.flatMap((group) => group.menus.flatMap((menu) => menu.pages));
assert.equal(settingsPages.length, 14);
for (const route of settingsPages)
  assert.deepEqual(readSettingsRoute(new URL(settingsRouteUrl(route), 'http://localhost').search), route);
for (const tab of ['', '?tab=unknown', '?tab=agents', '?tab=capabilities', '?tab=pet'])
  assert.deepEqual(readSettingsRoute(tab), { section: 'general' });
assert.deepEqual(readSettingsRoute('?tab=personas'), { section: 'personas', view: 'user' });
assert.deepEqual(readSettingsRoute('?tab=personas&view=unknown'), { section: 'personas', view: 'user' });
assert.equal(new Set(settingsGroups.flatMap((g) => g.menus.map((m) => m.id))).size, 7);
assert.deepEqual(readSettingsRoute('?tab=models'), { section: 'models', view: 'profiles' });
assert.deepEqual(readSettingsRoute('?tab=models&view=settings'), { section: 'models', view: 'profiles' });
assert.deepEqual(readSettingsRoute('?tab=knowledge&view=providers'), { section: 'knowledge', view: 'list' });
assert.deepEqual(readSettingsRoute('?tab=worldbook&view=settings'), { section: 'worldbook', view: 'settings' });
assert.deepEqual(readSettingsRoute('?tab=general&view=providers'), { section: 'general' });

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
await modelsApi.patchProviderProfile('backend/1', { name: 'Renamed' });
assert.equal(requests.at(-1).url, '/api/models/providers/backend%2F1');
assert.equal('connection' in requests.at(-1).body, false);
await modelsApi.patchProviderProfile('backend/1', { connection: { api_key: '' } });
assert.deepEqual(requests.at(-1).body.connection, { api_key: '' });
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
const { Button } = (await load('../src/components/ui/button.tsx')).exports;
const settings = {
  show_full_processing: false,
  auto_generate_session_titles: false,
  session_title_max_input_chars: 1234,
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
  .find((node) => node.type === Button)
  .props.onClick();
assert.deepEqual(saved, {
  show_full_processing: false,
  auto_generate_session_titles: false,
  session_title_max_input_chars: 1234,
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
  assert.doesNotMatch(html, /Core memory|核心记忆|Group transcript|群聊/);
  assert.doesNotMatch(html, /appearance_font|resource_status|generalFields\./);
}

console.log('settings navigation/submission, API boundaries and bilingual rendering: ok');
