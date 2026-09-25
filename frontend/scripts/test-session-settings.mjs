import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const resources = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale,
  Object.fromEntries(['personas', 'settings', 'llm', 'common'].map((namespace) => [namespace,
    JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'))])),
]));
const i18n = i18next.createInstance();
await i18n.init({ resources, lng: 'en', fallbackLng: 'en', interpolation: { escapeValue: false } });
const load = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
});
const { ToolsField, ContextFields, GenerationFields, ModelField, ModelSelect } = (
  await load('../src/components/personas/ConfigurationFields.tsx')
).exports;
const { Checkbox } = (await load('../src/components/ui/checkbox.tsx')).exports;
const { Switch } = (await load('../src/components/ui/switch.tsx')).exports;
const { SelectItem } = (await load('../src/components/ui/select.tsx')).exports;
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
let toggles = descendants(renderTools()).filter((node) => node.type === Checkbox);
assert.equal(toggles.length, 3);
assert.ok(toggles.every((node) => node.props.checked));
toggles[1].props.onCheckedChange(false);
assert.deepEqual(selected, ['base64_encode', 'web_search']);
toggles = descendants(renderTools()).filter((node) => node.type === Checkbox);
assert.equal(toggles[1].props.checked, false);
toggles[1].props.onCheckedChange(true);
assert.deepEqual(selected, ['base64_encode', 'read_file', 'web_search']);
for (const name of [...selected])
  descendants(renderTools()).filter((node) => node.type === Checkbox)[tools.findIndex((tool) => tool.name === name)].props.onCheckedChange(false);
assert.deepEqual(selected, []);
assert.ok(descendants(renderTools()).filter((node) => node.type === Checkbox).every((node) => !node.props.checked));

const policy = { mode: 'session', max_messages: null, max_chars: null, include_attachments: 'explicit' };
let changedPolicy;
const fields = ContextFields({ value: policy, onChange: (value) => { changedPolicy = value; } });
const policySwitches = descendants(fields).filter((node) => node.type === Switch);
assert.equal(policySwitches.length, 1);
policySwitches[0].props.onCheckedChange(false);
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
const modelOptions = descendants(modelSelect).filter((node) => node.type === SelectItem);
assert.deepEqual(modelOptions.map((node) => node.props.value), ['disabled', 'first', 'preferred']);
assert.equal(modelOptions[0].props.disabled, true);
modelSelect.props.onValueChange('first');
assert.equal(modelChoice, 'first');
const unavailable = ModelSelect({ profiles, value: 'missing', onChange: () => assert.fail('Rendering must not change the selected model') });
assert.equal(unavailable.props.value, 'missing');
assert.equal(descendants(unavailable).find((node) => node.type === SelectItem && node.props.value === 'missing').props.disabled, true);
const noModels = ModelSelect({ profiles: profiles.slice(0, 2), value: null, onChange: () => {} });
assert.equal(noModels.props.disabled, true);
assert.ok(descendants(noModels).filter((node) => node.type === SelectItem).every((node) => node.props.disabled));
const unselected = ModelSelect({ profiles, value: null, onChange: () => {} });
assert.equal(unselected.props.value, '');
assert.equal(descendants(unselected).find((node) => node.type === SelectItem && node.props.value === '').props.disabled, true);

let headerSession = { kind: 'ordinary', model_profile_id: 'preferred', persona_id: 'cogita', effective: { model_profile_id: 'preferred' } };
const headerLoad = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
  [sourceUrl('store/useModelsStore.ts')]: mockModule({ useModelsStore: (selector) => selector({ profiles }) }),
  [sourceUrl('store/useCogitaStore.ts')]: mockModule({ useCogitaStore: (selector) => selector({ currentSession: headerSession, updateSession: () => {} }) }),
});
const { ChatHeader } = (await headerLoad('../src/components/ChatHeader.tsx')).exports;
const { SidebarProvider } = (await headerLoad('../src/components/ui/sidebar.tsx')).exports;
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
  assert.equal((html.match(/aria-checked="true"/g) || []).length, 2);
  for (const modelId of ['preferred', 'first']) {
    headerSession = { ...headerSession, model_profile_id: modelId, effective: { model_profile_id: modelId } };
    const header = renderToStaticMarkup(React.createElement(SidebarProvider, null,
      React.createElement(ChatHeader, { onOpenSettings: () => {} })));
    const settings = renderToStaticMarkup(React.createElement(ModelField, { profiles, value: modelId, onChange: () => {} }));
    for (const rendered of [header, settings]) {
      assert.ok(rendered.includes(profiles.find((profile) => profile.id === modelId).name));
      assert.match(rendered, new RegExp(`<input[^>]*value="${modelId}"`));
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
assert.equal('updateSessionWorldbooks' in worldbookApi, false);
await worldbookApi.matchWorldbooks({ text: 'lore', worldbook_ids: ['book'] });
assert.deepEqual(requests.at(-1).body, { text: 'lore', worldbook_ids: ['book'] });
await chatApi.createSession();
assert.deepEqual(requests.at(-1).body, {});
await chatApi.updateSession('s', { harness_enabled: false, tools_allowed: [] });
assert.deepEqual(requests.at(-1).body, { harness_enabled: false, tools_allowed: [] });
await chatApi.updateSession('s', { model_profile_id: modelChoice });
assert.deepEqual(requests.at(-1).body, { model_profile_id: 'first' });
let generation = {};
const { Input } = (await load('../src/components/ui/input.tsx')).exports;
let generationElement;
function CaptureGeneration() {
  generationElement = GenerationFields({ value: generation, onChange: (value) => { generation = value; } });
  return generationElement;
}
renderToStaticMarkup(React.createElement(CaptureGeneration));
const generationNodes = descendants(generationElement);
const temperature = generationNodes.find((node) => node.type === Input);
assert.equal(generationNodes.filter((node) => node.type === Input).length, 1);
temperature.props.onChange({ currentTarget: { value: '0' } });
assert.deepEqual(generation, { temperature: 0 });
temperature.props.onChange({ currentTarget: { value: '' } });
assert.deepEqual(generation, { temperature: null });
await chatApi.listPersonas('character');
assert.equal(requests.at(-1).url, '/api/personas?collection=character');
await chatApi.createPersona({ collection: 'character', name: 'Role', avatar_attachment_id: null, system_prompt: '' });
assert.equal(requests.at(-1).body.collection, 'character');
console.log('Session configuration fields, concrete model selection, tool switches, locales and API requests passed.');
