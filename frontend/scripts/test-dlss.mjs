import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createModuleLoader, mockModule, sourceUrl, apiMocks } from './module-loader.mjs';

const actual = createModuleLoader();
const { default: i18n } = (await actual('../src/i18n/index.ts')).exports;
const calls = [];
const load = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(i18n.language, namespace) }) }),
  [sourceUrl('api/http.ts')]: mockModule({ request: async (...args) => { calls.push(args); return {}; } }),
});
const { newModel, localEngine, localOnly, selectModelReference } = (await load('../src/components/settings/models/profileDefaults.ts')).exports;
const { ProfileParameters } = (await load('../src/components/settings/models/ProfileParameters.tsx')).exports;
const { modelsApi } = (await load('../src/api/models.ts')).exports;
const model = newModel('processor');
assert.equal(localEngine(model), 'dlss5nr');
assert.ok(localOnly('processor'));
assert.equal(model.external_enabled, false);
assert.deepEqual(model.source.execution_options, { device: 'd3d12', gpu_index: 0 });
assert.equal(model.source.lifecycle.unload, 'manual');
const edited = { ...model, parameters: { ...model.parameters, intensity: 0, preset: 0, auto_mask: false, style: '6' } };
assert.deepEqual(selectModelReference(edited, 'processors/other', true).parameters, edited.parameters);
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const markup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: edited, onChange() {} }));
  for (const key of ['style', 'preset', 'intensity', 'tone', 'structure', 'skin', 'auto_mask', 'channel_order', 'task']) {
    assert.ok(markup.includes(i18n.t('processor.' + key, { ns: 'llm' })), key);
  }
  assert.match(markup, /value="0"/);
  assert.match(markup, /aria-checked="false"/);
  assert.doesNotMatch(markup, /NaN|undefined|intraop_threads/);
}
await modelsApi.runtimeComponents();
assert.equal(calls.at(-1)[0], '/api/models/local-runtime/components');
for (const action of ['install', 'repair', 'uninstall']) {
  await modelsApi.runtimeAction(action, 'dlss5nr');
  assert.equal(calls.at(-1)[0], '/api/models/local-runtime/components/dlss5nr/' + action);
}

const api = { listModelProfiles: async () => [{ id: 'created' }], listProviderProfiles: async () => [],
  getModelSettings: async () => ({}), getModelStatus: async () => ({ state: 'unloaded' }),
  runtimeCatalog: async () => ({}), runtimeInstallation: async () => ({ state: 'installed' }),
  runtimeJobs: async () => [], localRuntimeSettings: async () => ({ enabled: true }),
};
const storeLoad = createModuleLoader(apiMocks(api));
const { useModelsStore } = (await storeLoad('../src/store/useModelsStore.ts')).exports;
let release;
api.runtimeComponents = () => new Promise((resolve) => { release = resolve; });
const pending = useModelsStore.getState().reloadRuntimes();
const component = { component_id: 'dlss5nr', state: 'installed', version: '0.1.0', bundled_version: '0.1.0' };
useModelsStore.getState().applyModelEvent({ type: 'runtime_status', payload: { component } });
release([{ ...component, state: 'installing' }]);
await pending;
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(useModelsStore.getState().components[0].state, 'installed');
assert.equal(useModelsStore.getState().profiles[0].id, 'created');
console.log('DLSS defaults, controls, component APIs, stale-event ordering and generated profile refresh passed.');
