import type {
  Agent,
  AgentConfig,
  CapabilityConfig,
  Command,
  DeleteMessageResponse,
  DeleteSessionResponse,
  Diagnostics,
  LlmResolvedConfig,
  LlmDefaults,
  LlmProfile,
  LlmProfileInput,
  LlmProviderModel,
  LlmProviderProfile,
  LlmProviderProfileInput,
  LlmTestResult,
  Message,
  Run,
  RunEvent,
  HealthDetails,
  CleanupOrphansResult,
  GeneralSettings,
  OrphanScanResult,
  RuntimeResponse,
  Session,
  SendMessageAttachment,
  StorageStats,
} from '../types';
import { API_BASE_URL, createWebSocketUrlFromBase, joinApiUrl } from './url';

export { API_BASE_URL, joinApiUrl };

export class ApiError extends Error {
  code: string;
  details: Record<string, unknown>;

  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = code;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(joinApiUrl(API_BASE_URL, path), {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const backendError = payload?.error;
    const code = typeof backendError?.code === 'string' ? backendError.code : 'HTTP_ERROR';
    const message = typeof backendError?.message === 'string' ? backendError.message : `Request failed: ${response.status}`;
    const details = typeof backendError?.details === 'object' && backendError.details ? backendError.details : {};
    throw new ApiError(code, message, details);
  }
  return payload as T;
}

export const api = {
  listAgents: () => request<Agent[]>('/api/agents'),
  listCommands: () => request<Command[]>('/api/commands'),
  listAgentConfigs: () => request<AgentConfig[]>('/api/agent-configs'),
  getAgentConfig: (agentId: string) => request<AgentConfig>(`/api/agent-configs/${agentId}`),
  updateAgentConfig: (agentId: string, patch: Partial<Pick<AgentConfig, 'enabled' | 'user_config' | 'display' | 'runtime'>>) =>
    request<AgentConfig>(`/api/agent-configs/${agentId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  resetAgentOverrides: (agentId: string) =>
    request<AgentConfig>(`/api/agent-configs/${agentId}/reset-overrides`, {
      method: 'POST',
    }),
  writeAgentOverridesToManifest: (agentId: string) =>
    request<AgentConfig>(`/api/agent-configs/${agentId}/write-manifest`, {
      method: 'POST',
      body: JSON.stringify({ confirm: true }),
    }),
  listCapabilityConfigs: () => request<CapabilityConfig[]>('/api/capability-configs'),
  getCapabilityConfig: (capabilityId: string) => request<CapabilityConfig>(`/api/capability-configs/${capabilityId}`),
  updateCapabilityConfig: (
    capabilityId: string,
    patch: Partial<Pick<CapabilityConfig, 'enabled' | 'user_config'>>,
  ) =>
    request<CapabilityConfig>(`/api/capability-configs/${capabilityId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  getResolvedLlmConfig: () => request<LlmResolvedConfig>('/api/capability-configs/llm/resolved'),
  listLlmModels: () => request<{ success: boolean; models: { id: string }[] }>('/api/capability-configs/llm/models'),
  testLlmConnection: () => request<LlmTestResult>('/api/capability-configs/llm/test', { method: 'POST' }),
  listLlmProfiles: () => request<LlmProfile[]>('/api/llm-profiles'),
  listLlmProviderProfiles: () => request<LlmProviderProfile[]>('/api/llm-provider-profiles'),
  createLlmProviderProfile: (profile: LlmProviderProfileInput) =>
    request<LlmProviderProfile>('/api/llm-provider-profiles', {
      method: 'POST',
      body: JSON.stringify(profile),
    }),
  patchLlmProviderProfile: (profileId: string, patch: LlmProviderProfileInput) =>
    request<LlmProviderProfile>(`/api/llm-provider-profiles/${profileId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteLlmProviderProfile: (profileId: string) =>
    request<{ deleted: boolean; profile_id: string }>(`/api/llm-provider-profiles/${profileId}`, {
      method: 'DELETE',
    }),
  duplicateLlmProviderProfile: (profileId: string) =>
    request<LlmProviderProfile>(`/api/llm-provider-profiles/${profileId}/duplicate`, { method: 'POST' }),
  testLlmProviderProfile: (profileId: string) =>
    request<LlmTestResult>(`/api/llm-provider-profiles/${profileId}/test`, { method: 'POST' }),
  listLlmProviderModels: (profileId: string) =>
    request<{ success: boolean; provider_profile_id: string; provider: string; models: LlmProviderModel[]; warnings: string[] }>(`/api/llm-provider-profiles/${profileId}/refresh-models`, { method: 'POST' }),
  createLlmProfile: (profile: LlmProfileInput) =>
    request<LlmProfile>('/api/llm-profiles', {
      method: 'POST',
      body: JSON.stringify(profile),
    }),
  patchLlmProfile: (profileIdOrAlias: string, patch: LlmProfileInput) =>
    request<LlmProfile>(`/api/llm-profiles/${profileIdOrAlias}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteLlmProfile: (profileIdOrAlias: string) =>
    request<{ deleted: boolean; profile_id: string }>(`/api/llm-profiles/${profileIdOrAlias}`, {
      method: 'DELETE',
    }),
  duplicateLlmProfile: (profileIdOrAlias: string) =>
    request<LlmProfile>(`/api/llm-profiles/${profileIdOrAlias}/duplicate`, { method: 'POST' }),
  testLlmProfile: (profileIdOrAlias: string) =>
    request<LlmTestResult>(`/api/llm-profiles/${profileIdOrAlias}/test`, { method: 'POST' }),
  getGeneralSettings: () => request<GeneralSettings>('/api/settings/general'),
  getLlmDefaults: () => request<LlmDefaults>('/api/settings/llm-defaults'),
  updateLlmDefaults: (patch: Partial<LlmDefaults>) =>
    request<LlmDefaults>('/api/settings/llm-defaults', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  updateGeneralSettings: (patch: Partial<GeneralSettings>) =>
    request<GeneralSettings>('/api/settings/general', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  getStorageStats: () => request<StorageStats>('/api/data/storage-stats'),
  getDiagnostics: () => request<Diagnostics>('/api/diagnostics'),
  scanOrphanAttachments: () => request<OrphanScanResult>('/api/data/attachments/scan-orphans', { method: 'POST' }),
  cleanupOrphanAttachments: (confirm: boolean) =>
    request<CleanupOrphansResult>('/api/data/attachments/cleanup-orphans', {
      method: 'POST',
      body: JSON.stringify({ confirm }),
    }),
  listLlmProfileModels: (profileIdOrAlias: string) =>
    request<{ success: boolean; models: { id: string }[] }>(`/api/llm-profiles/${profileIdOrAlias}/models`),
  getHealthDetails: () => request<HealthDetails>('/api/health/details'),
  listSessions: () => request<Session[]>('/api/sessions'),
  createSession: (title = '', default_agent_id = 'chat') =>
    request<Session>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ title, default_agent_id }),
    }),
  getSession: (sessionId: string) => request<Session>(`/api/sessions/${sessionId}`),
  updateSession: (sessionId: string, patch: Partial<Pick<Session, 'title' | 'default_agent_id' | 'llm_profile_id'>>) =>
    request<Session>(`/api/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteSession: (sessionId: string) =>
    request<DeleteSessionResponse>(`/api/sessions/${sessionId}`, {
      method: 'DELETE',
    }),
  listMessages: (sessionId: string) => request<Message[]>(`/api/sessions/${sessionId}/messages`),
  sendMessage: (sessionId: string, content: string, attachments: SendMessageAttachment[] = []) =>
    request<RuntimeResponse>(`/api/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content, attachments }),
    }),
  deleteMessage: (messageId: string) =>
    request<DeleteMessageResponse>(`/api/messages/${messageId}`, {
      method: 'DELETE',
    }),
  retryMessage: (messageId: string) =>
    request<RuntimeResponse>(`/api/messages/${messageId}/retry`, {
      method: 'POST',
    }),
  editMessage: (messageId: string, content: string, rerun = true) =>
    request<RuntimeResponse>(`/api/messages/${messageId}/edit`, {
      method: 'POST',
      body: JSON.stringify({ content, rerun }),
    }),
  invokeAction: (
    sessionId: string,
    payload: { agent_id: string; action_id: string; source_message_id: string; input_text?: string; prefill?: Record<string, unknown> },
  ) =>
    request<RuntimeResponse>(`/api/sessions/${sessionId}/actions`, {
      method: 'POST',
      body: JSON.stringify({ input_text: '', prefill: {}, ...payload }),
    }),
  listRuns: (sessionId: string) => request<Run[]>(`/api/sessions/${sessionId}/runs`),
  listRunEvents: (runId: string) => request<RunEvent[]>(`/api/runs/${runId}/events`),
  cancelRun: (runId: string) =>
    request<{ run: Run; cancelled: boolean; task_cancelled?: boolean; reason: string }>(`/api/runs/${runId}/cancel`, {
      method: 'POST',
    }),
};

export function createWebSocketUrl(sessionId: string): string {
  return createWebSocketUrlFromBase(API_BASE_URL, sessionId, window.location.origin);
}
