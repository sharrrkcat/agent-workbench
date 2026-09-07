import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { apiMocks, createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const resources = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale, { llm:
  JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8')),
}]));
const i18n = i18next.createInstance();
await i18n.init({ resources, lng: 'en', interpolation: { escapeValue: false } });
const usage = { complete: true, file_count: 2, logical_bytes: 1024, unique_bytes: 1024, shared_bytes: 1000, exclusive_bytes: 24 };
const cacheJob = { id: 'cache', runtime_id: null, variant: null, version: null, operation: 'cache_clean',
  state: 'completed', stage: 'completed', revision: 3, created_at: '2026-09-08T00:00:00Z', error_code: null,
  result: { before: usage, after: { ...usage, file_count: 0, logical_bytes: 0, unique_bytes: 0, shared_bytes: 0, exclusive_bytes: 0 } },
};
const state = { storage: { scanned_at: cacheJob.created_at, complete: true, totals: usage,
  groups: [{ ...usage, id: '.cache', category: 'cache', relative_path: '.cache' }], warnings: [] },
  storageLoading: false, storageError: '', reloadStorage: async () => {}, jobs: [cacheJob] };
const load = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
  [sourceUrl('store/useModelsStore.ts')]: mockModule({ useModelsStore: () => state }),
});
const { RuntimeStoragePanel, CacheJobResult, runtimeBytes } = (await load('../src/components/settings/RuntimeStoragePanel.tsx')).exports;
const { CudaLayersField } = (await load('../src/components/settings/models/CudaLayersField.tsx')).exports;
assert.equal(runtimeBytes(null, 'Unknown'), 'Unknown');
assert.equal(runtimeBytes(0, 'Unknown'), '0 B');
assert.equal(runtimeBytes(1024, 'Unknown'), '1 KiB');
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const t = i18n.getFixedT(locale, 'llm');
  const panel = renderToStaticMarkup(React.createElement(RuntimeStoragePanel, {
    busy: false, active: undefined, onCleanup: async () => {}, onCancel: () => {},
  }));
  for (const key of ['storage.title', 'storage.reclaimable', 'cachePrune', 'cacheClean', 'jobStates.completed']) {
    assert.ok(panel.includes(t(key)), key);
  }
  assert.match(panel, /24 B/);
  assert.doesNotMatch(panel, /null \/ null|undefined|NaN/);
  const empty = renderToStaticMarkup(React.createElement(CacheJobResult, { job: {
    ...cacheJob, result: { before: null, after: cacheJob.result.after },
  } }));
  assert.ok(empty.includes(t('storage.unknown')) && empty.includes('0 B'));
  const auto = renderToStaticMarkup(React.createElement(CudaLayersField, { value: 'auto', onChange: () => {} }));
  assert.ok(auto.includes(t('gpuAuto')) && auto.includes(t('gpuManual')));
  assert.match(auto, /aria-pressed="true"/);
  assert.doesNotMatch(auto, /type="number"|NaN/);
  const manual = renderToStaticMarkup(React.createElement(CudaLayersField, { value: 7, onChange: () => {} }));
  assert.match(manual, /min="1"/);
  assert.match(manual, /max="999"/);
  assert.match(manual, /value="7"/);
}

const mockApi = {};
const storeLoad = createModuleLoader(apiMocks(mockApi));
const { useModelsStore } = (await storeLoad('../src/store/useModelsStore.ts')).exports;
let resolveOld;
mockApi.runtimeStorage = () => new Promise((resolve) => { resolveOld = resolve; });
const oldRead = useModelsStore.getState().reloadStorage();
mockApi.runtimeStorage = async () => ({ ...state.storage, scanned_at: 'new' });
await useModelsStore.getState().reloadStorage();
resolveOld({ ...state.storage, scanned_at: 'old' });
await oldRead;
assert.equal(useModelsStore.getState().storage.scanned_at, 'new');
useModelsStore.getState().setJob(cacheJob);
useModelsStore.getState().setJob({ ...cacheJob, revision: 1, result: null, state: 'running' });
assert.equal(useModelsStore.getState().jobs[0].result.after.logical_bytes, 0);
assert.equal(useModelsStore.getState().jobs[0].state, 'completed');
mockApi.runtimeStorage = async () => { throw new Error('scan failed'); };
await assert.rejects(useModelsStore.getState().reloadStorage(), /scan failed/);
assert.equal(useModelsStore.getState().storage, null);
assert.equal(useModelsStore.getState().storageLoading, false);

const requests = [];
globalThis.fetch = async (url, options) => {
  requests.push({ url, method: options.method, body: options.body ? JSON.parse(options.body) : null });
  return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
};
const { modelsApi } = (await load('../src/api/models.ts')).exports;
await modelsApi.runtimeStorage();
assert.equal(requests.at(-1).url, '/api/models/runtimes/storage');
for (const mode of ['prune', 'clean']) {
  await modelsApi.cleanupRuntimeCache(mode);
  assert.deepEqual(requests.at(-1), { url: '/api/models/runtimes/cache/cleanup', method: 'POST', body: { mode } });
}
console.log('Runtime storage accounting display, locales, cache jobs, CUDA fields, refresh ordering and APIs passed.');
