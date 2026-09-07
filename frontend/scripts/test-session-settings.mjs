import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const resources = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale,
  Object.fromEntries(['personas', 'settings', 'llm'].map((namespace) => [namespace,
    JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'))])),
]));
const i18n = i18next.createInstance();
await i18n.init({ resources, lng: 'en', fallbackLng: 'en', interpolation: { escapeValue: false } });
const load = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
});
const { ToolsField, ContextFields, GenerationFields, ModelField, ModelSelect, Check } = (
  await load('../src/components/personas/ConfigurationFields.tsx')
).exports;
function descendants(node) {
  if (Array.isArray(node)) return node.flatMap(descendants);
  if (!React.isValidElement(node)) return [];
  return [node, ...descendants(node.props.children)];
}
const tools = [
  { name: 'base64_encode', risk: 'safe', requires_approval: false },
  { name: 'read_file', risk: 'file', requires_approval: true },
  { name: 'web_search', risk: 'network', requires_approval: true },
];
let selected = tools.map((tool) => tool.name);
const renderTools = () => ToolsField({ tools, value: selected, onChange: (value) => { selected = value; } });
let toggles = descendants(renderTools()).filter((node) => node.type === Check);
assert.equal(toggles.length, 3);
assert.ok(toggles.every((node) => node.props.checked));
toggles.find((node) => node.props.label === 'read_file').props.onChange(false);
assert.deepEqual(selected, ['base64_encode', 'web_search']);
toggles = descendants(renderTools()).filter((node) => node.type === Check);
assert.equal(toggles.find((node) => node.props.label === 'read_file').props.checked, false);
toggles.find((node) => node.props.label === 'read_file').props.onChange(true);
assert.deepEqual(selected, ['base64_encode', 'read_file', 'web_search']);
for (const name of [...selected])
  descendants(renderTools()).find((node) => node.type === Check && node.props.label === name).props.onChange(false);
assert.deepEqual(selected, []);
assert.ok(descendants(renderTools()).filter((node) => node.type === Check).every((node) => !node.props.checked));

const policy = { mode: 'session', max_messages: null, max_chars: null, include_attachments: 'explicit' };
let changedPolicy;
const fields = ContextFields({ value: policy, onChange: (value) => { changedPolicy = value; } });
const policySwitches = descendants(fields).filter((node) => node.type === Check);
assert.equal(policySwitches.length, 1);
policySwitches[0].props.onChange(false);
assert.deepEqual(changedPolicy, { ...policy, include_attachments: 'none' });

const profiles = [
  { id: 'embedding', name: 'Embedding', kind: 'embedding', enabled: true },
  { id: 'disabled', name: 'Disabled model', kind: 'llm', enabled: false },
  { id: 'first', name: 'First model', kind: 'llm', enabled: true },
  { id: 'preferred', name: 'Preferred model', kind: 'llm', enabled: true },
];
let modelChoice;
const modelSelect = ModelSelect({ profiles, value: 'preferred', onChange: (id) => { modelChoice = id; } });
assert.equal(modelSelect.props.value, 'preferred');
assert.equal(modelSelect.props.disabled, false);
const modelOptions = descendants(modelSelect).filter((node) => node.type === 'option');
assert.deepEqual(modelOptions.map((node) => node.props.value), ['disabled', 'first', 'preferred']);
assert.equal(modelOptions[0].props.disabled, true);
modelSelect.props.onChange({ target: { value: 'first' } });
assert.equal(modelChoice, 'first');
const unavailable = ModelSelect({ profiles, value: 'missing', onChange: () => assert.fail('Rendering must not change the selected model') });
assert.equal(unavailable.props.value, 'missing');
assert.equal(descendants(unavailable).find((node) => node.type === 'option' && node.props.value === 'missing').props.disabled, true);
const noModels = ModelSelect({ profiles: profiles.slice(0, 2), value: null, onChange: () => {} });
assert.equal(noModels.props.disabled, true);
assert.ok(descendants(noModels).filter((node) => node.type === 'option').every((node) => node.props.disabled));
const unselected = ModelSelect({ profiles, value: null, onChange: () => {} });
assert.equal(unselected.props.value, '');
assert.equal(descendants(unselected).find((node) => node.type === 'option' && node.props.value === '').props.disabled, true);

let headerSession = { model_profile_id: 'preferred', current_persona_id: 'chat', personas: [], effective: {} };
const headerLoad = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
  [sourceUrl('store/useModelsStore.ts')]: mockModule({ useModelsStore: (selector) => selector({ profiles }) }),
  [sourceUrl('store/useWorkbenchStore.ts')]: mockModule({ useWorkbenchStore: (selector) => selector({ currentSession: headerSession, updateSession: () => {} }) }),
});
const { ChatHeader } = (await headerLoad('../src/components/ChatHeader.tsx')).exports;
for (const [locale, labels] of [
  ['en', ['Tools', 'Approval required', 'No models available']],
  ['zh-CN', ['工具', '需要确认', '暂无可用模型']],
]) {
  await i18n.changeLanguage(locale);
  const html = renderToStaticMarkup(React.createElement(React.Fragment, null,
    React.createElement(ToolsField, { tools, value: ['read_file'], onChange: () => {} }),
    React.createElement(ContextFields, { value: policy, onChange: () => {} }),
    React.createElement(GenerationFields, { value: {}, onChange: () => {} }),
    React.createElement(ModelField, { profiles: [], value: null, onChange: () => {} }),
  ));
  for (const label of labels) assert.ok(html.includes(label), label);
  assert.doesNotMatch(html, /include_system_prompt|inheritPersona|overrideHarness|toolRisk\.|Global default|全局默认/);
  assert.equal((html.match(/checked=""/g) || []).length, 2);
  for (const modelId of ['preferred', 'first']) {
    headerSession = { ...headerSession, model_profile_id: modelId };
    const header = renderToStaticMarkup(React.createElement(ChatHeader, { onOpenSettings: () => {}, onToggleSidebar: () => {} }));
    const settings = renderToStaticMarkup(React.createElement(ModelField, { profiles, value: modelId, onChange: () => {} }));
    for (const rendered of [header, settings]) {
      assert.match(rendered, new RegExp(`<option value="${modelId}"[^>]*selected=""`));
      assert.doesNotMatch(rendered, /Global default|全局默认|<option value=""/);
    }
  }
}

const requests = [];
globalThis.fetch = async (url, options) => {
  requests.push({ url, method: options.method, body: options.body ? JSON.parse(options.body) : null });
  return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
};
const { knowledgeApi } = (await load('../src/api/knowledge.ts')).exports;
const { worldbookApi } = (await load('../src/api/worldbook.ts')).exports;
const { chatApi } = (await load('../src/api/chat.ts')).exports;
await knowledgeApi.updateSessionKnowledgeBases('session/1', ['extra']);
assert.deepEqual(requests.at(-1), { url: '/api/sessions/session%2F1/knowledge-bases', method: 'PATCH', body: { knowledge_base_ids: ['extra'] } });
await worldbookApi.updateSessionWorldbooks('session/1', []);
assert.deepEqual(requests.at(-1).body, { worldbook_ids: [] });
await chatApi.createSession();
assert.deepEqual(requests.at(-1).body, {});
await chatApi.updateSession('s', { harness_enabled: false, tools_allowed: [] });
assert.deepEqual(requests.at(-1).body, { harness_enabled: false, tools_allowed: [] });
await chatApi.updateSession('s', { model_profile_id: modelChoice });
assert.deepEqual(requests.at(-1).body, { model_profile_id: 'first' });
console.log('Session configuration fields, concrete model selection, tool switches, locales and API requests passed.');
