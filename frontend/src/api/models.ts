import type {
  ModelInput,
  ModelInventoryItem,
  ModelKind,
  ModelProfile,
  ModelSettings,
  ModelStatus,
  PresetVoice,
  BackendInput,
  BackendProfile,
  RuntimeCatalog,
  BackendPatch,
  RuntimeInstallation,
  RuntimeJob,
  RuntimeStorage,
} from '../types/models';
import { request } from './http';

export const modelsApi = {
  runtimeCatalog: () => request<RuntimeCatalog>('/api/models/backends/local/runtime/catalog'),
  runtimeInstallation: () => request<RuntimeInstallation>('/api/models/backends/local/runtime'),
  runtimeJobs: () => request<RuntimeJob[]>('/api/models/runtimes/jobs'),
  runtimeStorage: () => request<RuntimeStorage>('/api/models/runtimes/storage'),
  cleanupRuntimeCache: (mode: 'prune' | 'clean') => request<RuntimeJob>('/api/models/runtimes/cache/cleanup', {
    method: 'POST', body: JSON.stringify({ mode }),
  }),
  runtimeJob: (id: string) => request<RuntimeJob>(`/api/models/runtimes/jobs/${encodeURIComponent(id)}`),
  runtimeJobLog: (id: string) => request<{ text: string }>(`/api/models/runtimes/jobs/${encodeURIComponent(id)}/log`),
  cancelRuntimeJob: (id: string) =>
    request<RuntimeJob>(`/api/models/runtimes/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  runtimeAction: (action: 'install' | 'repair' | 'uninstall') =>
    request<RuntimeJob>(`/api/models/backends/local/runtime/${action}`, { method: 'POST' }),
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
  modelAction: (id: string, action: 'load' | 'unload' | 'health') =>
    request<ModelStatus>(`/api/models/profiles/${encodeURIComponent(id)}/${action}`, { method: 'POST' }),
  getModelLog: (id: string) => request<{ text: string }>(`/api/models/profiles/${encodeURIComponent(id)}/log`),
  listModelInventory: (kind?: ModelKind) =>
    request<ModelInventoryItem[]>('/api/models/inventory' + (kind ? '?kind=' + kind : '')),
  listBackendProfiles: () => request<BackendProfile[]>('/api/models/backends'),
  createBackendProfile: (profile: BackendInput) =>
    request<BackendProfile>('/api/models/backends', { method: 'POST', body: JSON.stringify(profile) }),
  patchBackendProfile: (id: string, patch: BackendPatch) =>
    request<BackendProfile>(`/api/models/backends/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteBackendProfile: (id: string) =>
    request<{ deleted: boolean }>(`/api/models/backends/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  listBackendModels: (id: string) =>
    request<{ models: string[] }>(`/api/models/backends/${encodeURIComponent(id)}/models`),
};
