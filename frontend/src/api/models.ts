import type {
  ModelInput,
  ModelInventoryItem,
  ModelKind,
  ModelProfile,
  ModelSettings,
  ModelStatus,
  ProviderInput,
  ProviderProfile,
  RuntimeCatalogEntry,
  RuntimeDownloadSettings,
  RuntimeInstallation,
  RuntimeJob,
  RuntimeStorage,
} from '../types/models';
import { request } from './http';

export const modelsApi = {
  runtimeCatalog: () => request<RuntimeCatalogEntry[]>('/api/models/runtimes/catalog'),
  runtimeInstallations: () => request<RuntimeInstallation[]>('/api/models/runtimes'),
  runtimeJobs: () => request<RuntimeJob[]>('/api/models/runtimes/jobs'),
  runtimeStorage: () => request<RuntimeStorage>('/api/models/runtimes/storage'),
  cleanupRuntimeCache: (mode: 'prune' | 'clean') => request<RuntimeJob>('/api/models/runtimes/cache/cleanup', {
    method: 'POST', body: JSON.stringify({ mode }),
  }),
  runtimeJob: (id: string) => request<RuntimeJob>(`/api/models/runtimes/jobs/${encodeURIComponent(id)}`),
  runtimeJobLog: (id: string) => request<{ text: string }>(`/api/models/runtimes/jobs/${encodeURIComponent(id)}/log`),
  cancelRuntimeJob: (id: string) =>
    request<RuntimeJob>(`/api/models/runtimes/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  runtimeAction: (runtime: string, variant: string, action: 'install' | 'uninstall') =>
    request<RuntimeJob>(
      `/api/models/runtimes/${encodeURIComponent(runtime)}/${encodeURIComponent(variant)}/${action}`,
      { method: 'POST' },
    ),
  runtimeSettings: () => request<RuntimeDownloadSettings>('/api/models/runtime/settings'),
  patchRuntimeSettings: (settings: RuntimeDownloadSettings) =>
    request<RuntimeDownloadSettings>('/api/models/runtime/settings', {
      method: 'PATCH',
      body: JSON.stringify(settings),
    }),
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
  modelAction: (id: string, action: 'load' | 'unload' | 'health') =>
    request<ModelStatus>(`/api/models/profiles/${encodeURIComponent(id)}/${action}`, { method: 'POST' }),
  getModelLog: (id: string) => request<{ text: string }>(`/api/models/profiles/${encodeURIComponent(id)}/log`),
  listModelInventory: (kind?: ModelKind) =>
    request<ModelInventoryItem[]>('/api/models/inventory' + (kind ? '?kind=' + kind : '')),
  listProviderProfiles: () => request<ProviderProfile[]>('/api/models/providers'),
  createProviderProfile: (profile: ProviderInput) =>
    request<ProviderProfile>('/api/models/providers', { method: 'POST', body: JSON.stringify(profile) }),
  patchProviderProfile: (id: string, patch: Partial<ProviderInput>) =>
    request<ProviderProfile>(`/api/models/providers/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteProviderProfile: (id: string) =>
    request<{ deleted: boolean }>(`/api/models/providers/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  listProviderModels: (id: string) =>
    request<{ models: string[] }>(`/api/models/providers/${encodeURIComponent(id)}/models`),
};
