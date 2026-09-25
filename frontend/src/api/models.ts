import type {
  ModelInput,
  LocalRuntimeSettings,
  LocalRuntimeSettingsPatch,
  ModelInventoryItem,
  ModelKind,
  ModelProfile,
  ModelSettings,
  ModelStatus,
  PresetVoice,
  ProviderInput,
  ProviderProfile,
  RuntimeCatalog,
  ProviderPatch,
  RuntimeInstallation,
  RuntimeJob,
  RuntimeStorage,
  SiglipInspection,
  TextEmbeddingInspection,
  RerankerInspection,
  ASRInspection,
  LocalEmbeddingParameters,
  SiglipTower,
} from '../types/models';
import { request } from './http';

export const modelsApi = {
  inspectASR: (model_ref: string) =>
    request<ASRInspection>('/api/models/inspect?' + new URLSearchParams({ kind: 'asr', model_ref })),
  inspectReranker: (model_ref: string) =>
    request<RerankerInspection>('/api/models/inspect?' + new URLSearchParams({ kind: 'reranker', model_ref })),
  localRuntimeSettings: () => request<LocalRuntimeSettings>('/api/models/local-runtime/settings'),
  patchLocalRuntimeSettings: (patch: LocalRuntimeSettingsPatch) =>
    request<LocalRuntimeSettings>('/api/models/local-runtime/settings', { method: 'PATCH', body: JSON.stringify(patch) }),
  runtimeCatalog: () => request<RuntimeCatalog>('/api/models/local-runtime/catalog'),
  runtimeInstallation: () => request<RuntimeInstallation>('/api/models/local-runtime'),
  runtimeJobs: () => request<RuntimeJob[]>('/api/models/local-runtime/jobs'),
  runtimeStorage: () => request<RuntimeStorage>('/api/models/local-runtime/storage'),
  cleanupRuntimeCache: (mode: 'prune' | 'clean') => request<RuntimeJob>('/api/models/local-runtime/cache/cleanup', {
    method: 'POST', body: JSON.stringify({ mode }),
  }),
  runtimeJob: (id: string) => request<RuntimeJob>(`/api/models/local-runtime/jobs/${encodeURIComponent(id)}`),
  runtimeJobLog: (id: string) => request<{ text: string }>(`/api/models/local-runtime/jobs/${encodeURIComponent(id)}/log`),
  cancelRuntimeJob: (id: string) =>
    request<RuntimeJob>(`/api/models/local-runtime/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  runtimeAction: (action: 'install' | 'repair' | 'uninstall') =>
    request<RuntimeJob>(`/api/models/local-runtime/${action}`, { method: 'POST' }),
  getModelSettings: () => request<ModelSettings>('/api/models/settings'),
  updateModelSettings: (patch: Partial<Omit<ModelSettings, 'has_external_api_key'>> & { external_api_key?: string }) =>
    request<ModelSettings>('/api/models/settings', { method: 'PATCH', body: JSON.stringify(patch) }),
  listModelProfiles: (kind?: ModelKind) =>
    request<ModelProfile[]>('/api/models/profiles' + (kind ? '?kind=' + kind : '')),
  createModelProfile: (profile: ModelInput) =>
    request<ModelProfile>('/api/models/profiles', { method: 'POST', body: JSON.stringify(profile) }),
  patchModelProfile: (id: string, patch: Partial<ModelInput>) =>
    request<ModelProfile>(`/api/models/profiles/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteModelProfile: (id: string) =>
    request<{ deleted: boolean }>(`/api/models/profiles/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getModelStatus: (id: string) => request<ModelStatus>(`/api/models/profiles/${encodeURIComponent(id)}/status`),
  getModelVoices: (id: string) => request<PresetVoice[]>(`/api/models/profiles/${encodeURIComponent(id)}/voices`),
  modelAction: (id: string, action: 'load' | 'unload' | 'health', tower?: SiglipTower) =>
    request<ModelStatus>(`/api/models/profiles/${encodeURIComponent(id)}/${action}`, {
      method: 'POST', ...(tower ? { body: JSON.stringify({ tower }) } : {}),
    }),
  getModelLog: (id: string, tower?: SiglipTower) =>
    request<{ text: string }>(`/api/models/profiles/${encodeURIComponent(id)}/log` + (tower ? `?tower=${tower}` : '')),
  inspectImageEmbedding: (model_ref: string) =>
    request<SiglipInspection>('/api/models/inspect?' + new URLSearchParams({ kind: 'image_embedding', model_ref })),
  inspectTextEmbedding: (model_ref: string, parameters: LocalEmbeddingParameters) => {
    const query = new URLSearchParams({ kind: 'embedding', model_ref });
    for (const [key, value] of Object.entries(parameters)) if (value !== null) query.set(key, value);
    return request<TextEmbeddingInspection>('/api/models/inspect?' + query);
  },
  listModelInventory: (kind?: ModelKind) =>
    request<ModelInventoryItem[]>('/api/models/inventory' + (kind ? '?kind=' + kind : '')),
  listProviderProfiles: () => request<ProviderProfile[]>('/api/models/providers'),
  createProviderProfile: (profile: ProviderInput) =>
    request<ProviderProfile>('/api/models/providers', { method: 'POST', body: JSON.stringify(profile) }),
  patchProviderProfile: (id: string, patch: ProviderPatch) =>
    request<ProviderProfile>(`/api/models/providers/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteProviderProfile: (id: string) =>
    request<{ deleted: boolean }>(`/api/models/providers/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  listProviderModels: (id: string) =>
    request<{ models: string[] }>(`/api/models/providers/${encodeURIComponent(id)}/models`),
};
