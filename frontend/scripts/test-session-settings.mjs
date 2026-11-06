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
  'react': mockModule({ ...React, default: React, useId: () => 'context-test' }),
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
});
const { ToolsField, ContextFields, GenerationFields, ModelField, ModelSelect } = (
  await load('../src/components/personas/ConfigurationFields.tsx')
).exports;
const { Checkbox } = (await load('../src/components/ui/checkbox.tsx')).exports;
const { Switch } = (await load('../src/components/ui/switch.tsx')).exports;
const { Select, SelectItem } = (await load('../src/components/ui/select.tsx')).exports;
function descendants(node) {
  if (Array.isArray(node)) return node.flatMap(descendants);
  if (!React.isValidElement(node)) return [];
  return [node, ...descendants(node.props.children)];
}
const tools = [
  { name: 'test_echo', scope: 'general', risk: 'safe', requires_approval: false },
  { name: 'test_approval', scope: 'general', risk: 'safe', requires_approval: true },
  { name: 'test_other', scope: 'general', risk: 'safe', requires_approval: false },
];
let selected = tools.map((tool) => tool.name);
const renderTools = () => ToolsField({ tools, value: selected, onChange: (value) => { selected = value; } });
let toggles = descendants(renderTools()).filter((node) => node.type === Checkbox);
assert.equal(toggles.length, 3);
assert.ok(toggles.every((node) => node.props.checked));
toggles[1].props.onCheckedChange(false);
assert.deepEqual(selected, ['test_echo', 'test_other']);
toggles = descendants(renderTools()).filter((node) => node.type === Checkbox);
assert.equal(toggles[1].props.checked, false);
toggles[1].props.onCheckedChange(true);
assert.deepEqual(selected, ['test_echo', 'test_approval', 'test_other']);
for (const name of [...selected])
  descendants(renderTools()).filter((node) => node.type === Checkbox)[tools.findIndex((tool) => tool.name === name)].props.onCheckedChange(false);
assert.deepEqual(selected, []);
assert.ok(descendants(renderTools()).filter((node) => node.type === Checkbox).every((node) => !node.props.checked));

const policy = { history_enabled: true, strategy: 'token_budget', message_window: { max_messages: 100 }, include_attachments: 'explicit', compaction: {
  enabled: true, trigger_percent: 80, target_percent: 55, max_summary_tokens: null } };
let changedPolicy;
const fields = ContextFields({ value: policy, onChange: (value) => { changedPolicy = value; } });
const policySwitches = descendants(fields).filter((node) => node.type === Switch);
assert.equal(policySwitches.length, 3);
policySwitches[0].props.onCheckedChange(false);
assert.equal(changedPolicy.history_enabled, false);
policySwitches[1].props.onCheckedChange(false);
assert.equal(changedPolicy.compaction.enabled, false);
policySwitches[2].props.onCheckedChange(false);
assert.equal(changedPolicy.include_attachments, 'none');
const historyOff = descendants(ContextFields({ value: { ...policy, history_enabled: false }, showAttachments: false, onChange() {} }));
assert.equal(historyOff.filter((node) => node.type === Switch).length, 2);
assert.ok(historyOff.filter((node) => node.type === Switch).every((node) => !node.props.disabled));
const { Input: ContextInput } = (await load('../src/components/ui/input.tsx')).exports;
const inputs = descendants(fields).filter((node) => node.type === ContextInput);
assert.equal(inputs.length, 3);
inputs[0].props.onChange({ currentTarget: { value: '90' } });
assert.deepEqual(changedPolicy.compaction, { ...policy.compaction, trigger_percent: 90 });
inputs[2].props.onChange({ currentTarget: { value: '256' } });
assert.equal(changedPolicy.compaction.max_summary_tokens, 256);
inputs[2].props.onChange({ currentTarget: { value: '' } });
assert.equal(changedPolicy.compaction.max_summary_tokens, null);
const disabledFields = ContextFields({ value: { ...policy, history_enabled: false }, onChange: () => {} });
assert.ok(descendants(disabledFields).filter((node) => node.type === ContextInput).every((node) => !node.props.disabled));
const { ToggleGroup } = (await load('../src/components/ui/toggle-group.tsx')).exports;
const strategy = descendants(fields).find((node) => node.type === ToggleGroup);
strategy.props.onValueChange(['message_window']);
assert.equal(changedPolicy.strategy, 'message_window');
assert.deepEqual(changedPolicy.compaction, policy.compaction);
const windowFields = ContextFields({ value: changedPolicy, onChange: (value) => { changedPolicy = value; } });
const windowInputs = descendants(windowFields).filter((node) => node.type === ContextInput);
assert.equal(windowInputs.length, 1);
assert.equal(descendants(windowFields).filter((node) => node.type === Switch).length, 2);
windowInputs[0].props.onChange({ currentTarget: { value: '20' } });
assert.equal(changedPolicy.message_window.max_messages, 20);
const invalidWindow = ContextFields({ value: { ...changedPolicy, message_window: { max_messages: 0 } }, onChange: () => {} });
assert.equal(descendants(invalidWindow).find((node) => node.type === ContextInput).props['aria-invalid'], true);
const disabledWindow = ContextFields({ value: { ...changedPolicy, history_enabled: false }, onChange: () => {} });
assert.equal(descendants(disabledWindow).find((node) => node.type === ContextInput).props.disabled, true);

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

let headerSession = { kind: 'normal', title: 'Configuration fixture', model_profile_id: 'preferred', persona_id: 'cogita', effective: { model_profile_id: 'preferred' } };
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
    React.createElement(ToolsField, { tools, value: ['test_approval'], onChange: () => {} }),
    React.createElement(ContextFields, { value: policy, onChange: () => {} }),
    React.createElement(GenerationFields, { value: {}, onChange: () => {} }),
    React.createElement(ModelField, { profiles: [], value: null, onChange: () => {} }),
  ));
  for (const label of labels) assert.ok(html.includes(label), label);
  assert.ok(html.includes(resources[locale].personas.historyEnabled));
  assert.doesNotMatch(html, /include_system_prompt|inheritPersona|overrideHarness|toolRisk\.|Global default|全局默认/);
  assert.equal((html.match(/aria-checked="true"/g) || []).length, 4);
  for (const modelId of ['preferred', 'first']) {
    headerSession = { ...headerSession, model_profile_id: modelId, effective: { model_profile_id: modelId } };
    const header = renderToStaticMarkup(React.createElement(SidebarProvider, null,
      React.createElement(ChatHeader, { onOpenSettings: () => {} })));
    const settings = renderToStaticMarkup(React.createElement(ModelField, { profiles, value: modelId, onChange: () => {} }));
    assert.doesNotMatch(header, /role="combobox"|chat-model-select/);
    assert.ok(settings.includes(profiles.find((profile) => profile.id === modelId).name));
    assert.match(settings, new RegExp(`<input[^>]*value="${modelId}"`));
    assert.doesNotMatch(settings, /Global default|全局默认|<option value=""/);
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
await chatApi.updateSession('session/1', { overrides: { knowledge_base_ids: ['extra'], worldbook_ids: [] } });
assert.deepEqual(requests.at(-1), { url: '/api/sessions/session%2F1', method: 'PATCH', body: { overrides: { knowledge_base_ids: ['extra'], worldbook_ids: [] } } });
assert.equal('updateSessionWorldbooks' in worldbookApi, false);
await worldbookApi.matchWorldbooks({ text: 'lore', worldbook_ids: ['book'] });
assert.deepEqual(requests.at(-1).body, { text: 'lore', worldbook_ids: ['book'] });
const { charactersApi } = (await load('../src/api/characters.ts')).exports;
await charactersApi.createSession('character');
assert.deepEqual(requests.at(-1).body, {});
await chatApi.sendMessage('s', 'input', [], 'client');
assert.deepEqual(requests.at(-1).body, { content: 'input', attachments: [], client_message_id: 'client' });
await chatApi.updateSession('s', { overrides: { harness_enabled: false, tools_allowed: [] } });
assert.deepEqual(requests.at(-1).body, { overrides: { harness_enabled: false, tools_allowed: [] } });
await chatApi.updateSession('s', { overrides: { model_profile_id: modelChoice } });
assert.deepEqual(requests.at(-1).body, { overrides: { model_profile_id: 'first' } });
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
await chatApi.listPersonas();
assert.equal(requests.at(-1).url, '/api/personas');
await chatApi.createPersona({ name: 'User', avatar_attachment_id: null, background: '' });
assert.deepEqual(requests.at(-1).body, { name: 'User', avatar_attachment_id: null, background: '' });
console.log('Session configuration fields, concrete model selection, tool switches, locales and API requests passed.');
