import type {
  Agent,
  AgentConfig,
  Attachment,
  CapabilityConfig,
  Command,
  DeleteMessageResponse,
  DismissNotificationResponse,
  DeleteSessionResponse,
  Diagnostics,
  LlmResolvedConfig,
  LlmDefaults,
  LlmProfile,
  LlmProfileInput,
  LlmProviderModel,
  LlmProviderProfile,
  LlmProviderProfileInput,
  LlmProviderStatusRefreshResponse,
  LlmTestResult,
  Message,
  Run,
  RunEvent,
  HealthDetails,
  CleanupOrphansResult,
  GeneralSettings,
  OrphanScanResult,
  EmbeddingModelProfile,
  EmbeddingModelProfileInput,
  KnowledgeBase,
  KnowledgeBaseInput,
  SessionKnowledgeBinding,
  KnowledgeSource,
  KnowledgeSourceChunksResponse,
  KnowledgeSourceIndexResult,
  KnowledgeSourcePreview,
  KnowledgeModelScan,
  KnowledgeSearchResponse,
  SessionWorldbooksResponse,
  KnowledgeChunk,
  KnowledgeSettings,
  Worldbook,
  WorldbookEntry,
  WorldbookEntryInput,
  WorldbookInput,
  WorldbookMatchTestResponse,
  WorldbookSettings,
  PetListResponse,
  PetImportResponse,
  PetSettings,
  PetSettingsResponse,
  RuntimeResponse,
  RuntimeMemoryFreeResult,
  RuntimeMemorySummary,
  RuntimeResources,
  RuntimeMemoryTarget,
  UtilityLlmJsonTestResult,
  UtilityLlmModelScan,
  UtilityLlmStatus,
  UtilityLlmTitleTestResult,
  IntentRouteTestResponse,
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

async function requestForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(joinApiUrl(API_BASE_URL, path), {
    method: 'POST',
    body,
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
  refreshLlmProviderStatuses: (providerProfileIds?: string[]) =>
    request<LlmProviderStatusRefreshResponse>('/api/llm-provider-profiles/status/refresh', {
      method: 'POST',
      body: JSON.stringify({ provider_profile_ids: providerProfileIds, force: true }),
    }),
  refreshLlmProviderStatus: (profileId: string) =>
    request<LlmProviderStatusRefreshResponse>(`/api/llm-provider-profiles/${profileId}/status/refresh`, { method: 'POST' }),
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
  getKnowledgeSettings: () => request<KnowledgeSettings>('/api/knowledge/settings'),
  updateKnowledgeSettings: (patch: Partial<KnowledgeSettings>) =>
    request<KnowledgeSettings>('/api/knowledge/settings', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  getWorldbookSettings: () => request<WorldbookSettings>('/api/worldbook/settings'),
  updateWorldbookSettings: (patch: Partial<WorldbookSettings>) =>
    request<WorldbookSettings>('/api/worldbook/settings', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  listWorldbooks: () => request<Worldbook[]>('/api/worldbooks'),
  createWorldbook: (worldbook: WorldbookInput) =>
    request<Worldbook>('/api/worldbooks', {
      method: 'POST',
      body: JSON.stringify(worldbook),
    }),
  patchWorldbook: (worldbookId: string, patch: WorldbookInput) =>
    request<Worldbook>(`/api/worldbooks/${worldbookId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteWorldbook: (worldbookId: string) =>
    request<{ deleted: boolean; worldbook_id: string }>(`/api/worldbooks/${worldbookId}`, { method: 'DELETE' }),
  listWorldbookEntries: (worldbookId: string) => request<WorldbookEntry[]>(`/api/worldbooks/${worldbookId}/entries`),
  getWorldbookEntry: (entryId: string) => request<WorldbookEntry>(`/api/worldbook-entries/${entryId}`),
  createWorldbookEntry: (worldbookId: string, entry: WorldbookEntryInput) =>
    request<WorldbookEntry>(`/api/worldbooks/${worldbookId}/entries`, {
      method: 'POST',
      body: JSON.stringify(entry),
    }),
  patchWorldbookEntry: (entryId: string, patch: WorldbookEntryInput) =>
    request<WorldbookEntry>(`/api/worldbook-entries/${entryId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteWorldbookEntry: (entryId: string) =>
    request<{ deleted: boolean; entry_id: string }>(`/api/worldbook-entries/${entryId}`, { method: 'DELETE' }),
  reorderWorldbookEntries: (worldbookId: string, entryIds: string[]) =>
    request<{ worldbook_id: string; entries: WorldbookEntry[] }>(`/api/worldbooks/${worldbookId}/entries/reorder`, {
      method: 'PATCH',
      body: JSON.stringify({ entry_ids: entryIds }),
    }),
  getSessionWorldbooks: (sessionId: string) => request<SessionWorldbooksResponse>(`/api/sessions/${sessionId}/worldbooks`),
  updateSessionWorldbooks: (sessionId: string, worldbookIds: string[]) =>
    request<SessionWorldbooksResponse>(`/api/sessions/${sessionId}/worldbooks`, {
      method: 'PATCH',
      body: JSON.stringify({ worldbook_ids: worldbookIds }),
    }),
  matchWorldbooks: (payload: { text: string; worldbook_ids?: string[]; session_id?: string | null }) =>
    request<WorldbookMatchTestResponse>('/api/worldbooks/match-test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  scanKnowledgeModels: () => request<KnowledgeModelScan>('/api/knowledge/models/scan'),
  listEmbeddingModels: () => request<EmbeddingModelProfile[]>('/api/knowledge/embedding-models'),
  createEmbeddingModel: (profile: EmbeddingModelProfileInput) =>
    request<EmbeddingModelProfile>('/api/knowledge/embedding-models', {
      method: 'POST',
      body: JSON.stringify(profile),
    }),
  patchEmbeddingModel: (profileId: string, patch: EmbeddingModelProfileInput) =>
    request<EmbeddingModelProfile>(`/api/knowledge/embedding-models/${profileId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteEmbeddingModel: (profileId: string) =>
    request<{ deleted: boolean; profile_id: string }>(`/api/knowledge/embedding-models/${profileId}`, { method: 'DELETE' }),
  testEmbeddingModel: (profileId: string, text: string, purpose: 'query' | 'document' = 'query') =>
    request<{ ok: boolean; dimension: number; sample: number[]; normalized: boolean }>(`/api/knowledge/embedding-models/${profileId}/test`, {
      method: 'POST',
      body: JSON.stringify({ text, purpose }),
    }),
  createKnowledgeEmbeddings: (payload: { model_profile_id: string; purpose: 'query' | 'document'; inputs: string[] }) =>
    request<{ model_profile_id: string; dimension: number; vectors: number[][] }>('/api/knowledge/embeddings', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  rerankKnowledge: (payload: { query: string; documents: { id: string; text: string }[] }) =>
    request<{ ok: boolean; model_path: string; results: { id: string; score: number }[] }>('/api/knowledge/rerank', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listKnowledgeBases: () => request<KnowledgeBase[]>('/api/knowledge/bases'),
  createKnowledgeBase: (knowledgeBase: KnowledgeBaseInput) =>
    request<KnowledgeBase>('/api/knowledge/bases', {
      method: 'POST',
      body: JSON.stringify(knowledgeBase),
    }),
  patchKnowledgeBase: (knowledgeBaseId: string, patch: KnowledgeBaseInput) =>
    request<KnowledgeBase>(`/api/knowledge/bases/${knowledgeBaseId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteKnowledgeBase: (knowledgeBaseId: string) =>
    request<{ deleted: boolean; knowledge_base_id: string }>(`/api/knowledge/bases/${knowledgeBaseId}`, { method: 'DELETE' }),
  listKnowledgeSources: (knowledgeBaseId: string) => request<KnowledgeSource[]>(`/api/knowledge/bases/${knowledgeBaseId}/sources`),
  createPastedKnowledgeSource: (knowledgeBaseId: string, payload: { title: string; text: string }) =>
    request<KnowledgeSourceIndexResult>(`/api/knowledge/bases/${knowledgeBaseId}/sources`, {
      method: 'POST',
      body: JSON.stringify({ source_type: 'pasted_text', ...payload }),
    }),
  createAttachmentKnowledgeSource: (knowledgeBaseId: string, payload: { attachment_id: string; title?: string }) =>
    request<KnowledgeSourceIndexResult>(`/api/knowledge/bases/${knowledgeBaseId}/sources`, {
      method: 'POST',
      body: JSON.stringify({ source_type: 'attachment_text', ...payload }),
    }),
  deleteKnowledgeSource: (sourceId: string) =>
    request<{ deleted: boolean; source_id: string }>(`/api/knowledge/sources/${sourceId}`, { method: 'DELETE' }),
  reindexKnowledgeSource: (sourceId: string) =>
    request<KnowledgeSourceIndexResult>(`/api/knowledge/sources/${sourceId}/reindex`, { method: 'POST' }),
  reindexKnowledgeBase: (knowledgeBaseId: string) =>
    request<{ knowledge_base_id: string; sources: KnowledgeSourceIndexResult[] }>(`/api/knowledge/bases/${knowledgeBaseId}/reindex`, { method: 'POST' }),
  getKnowledgeSourcePreview: (sourceId: string) =>
    request<KnowledgeSourcePreview>(`/api/knowledge/sources/${sourceId}/preview`),
  listKnowledgeSourceChunks: (sourceId: string) =>
    request<KnowledgeSourceChunksResponse>(`/api/knowledge/sources/${sourceId}/chunks`),
  searchKnowledge: (payload: {
    query: string;
    knowledge_base_ids?: string[];
    session_id?: string | null;
    top_k?: number;
    max_context_chars?: number;
    min_score_threshold?: number | null;
    max_chunks_per_source?: number | null;
    max_chunks_per_knowledge_base?: number | null;
    expand_query?: boolean | null;
    debug?: boolean;
  }) =>
    request<KnowledgeSearchResponse>('/api/knowledge/search', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getKnowledgeChunk: (chunkId: string) => request<KnowledgeChunk>(`/api/knowledge/chunks/${encodeURIComponent(chunkId)}`),
  uploadAttachment: (file: File) => {
    const formData = new FormData();
    formData.append('file', file, file.name || 'attachment.txt');
    return requestForm<Attachment>('/api/attachments', formData);
  },
  getPetSettings: () => request<PetSettingsResponse>('/api/pets/settings'),
  updatePetSettings: (values: Partial<PetSettings>) =>
    request<PetSettingsResponse>('/api/pets/settings', {
      method: 'PATCH',
      body: JSON.stringify({ values }),
    }),
  listPets: () => request<PetListResponse>('/api/pets'),
  scanPets: () => request<PetListResponse>('/api/pets/scan', { method: 'POST' }),
  importPet: (petJson: File, spritesheet: File) => {
    const formData = new FormData();
    formData.append('pet_json', petJson, 'pet.json');
    formData.append('spritesheet', spritesheet, 'spritesheet.webp');
    return requestForm<PetImportResponse>('/api/pets/import', formData);
  },
  deletePet: (petId: string) =>
    request<{ deleted: boolean; pet_id: string }>(`/api/pets/${encodeURIComponent(petId)}`, {
      method: 'DELETE',
    }),
  listSessionKnowledgeBases: (sessionId: string) => request<SessionKnowledgeBinding[]>(`/api/sessions/${sessionId}/knowledge-bases`),
  updateSessionKnowledgeBases: (sessionId: string, knowledgeBaseIds: string[]) =>
    request<SessionKnowledgeBinding[]>(`/api/sessions/${sessionId}/knowledge-bases`, {
      method: 'PATCH',
      body: JSON.stringify({ knowledge_base_ids: knowledgeBaseIds }),
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
  getRuntimeMemory: (sessionId?: string | null) =>
    request<RuntimeMemorySummary>(`/api/runtime/memory${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`),
  getRuntimeResources: () => request<RuntimeResources>('/api/runtime/resources'),
  getUtilityLlmStatus: () => request<UtilityLlmStatus>('/api/intent/utility-llm/status'),
  scanUtilityLlmModels: () => request<UtilityLlmModelScan>('/api/intent/utility-llm/models/scan'),
  testUtilityLlmTitle: (text: string) =>
    request<UtilityLlmTitleTestResult>('/api/intent/utility-llm/test-title', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  testUtilityLlmJson: (text: string) =>
    request<UtilityLlmJsonTestResult>('/api/intent/utility-llm/test-json', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  unloadUtilityLlm: () => request<{ ok: boolean; status: string }>('/api/intent/utility-llm/unload', { method: 'POST' }),
  testIntentRoute: (payload: { text: string; session_id?: string | null; default_agent_id?: string | null; include_utility?: boolean }) =>
    request<IntentRouteTestResponse>('/api/intent/test-route', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  freeRuntimeMemory: (targets: RuntimeMemoryTarget[], sessionId?: string | null) =>
    request<RuntimeMemoryFreeResult>('/api/runtime/free-memory', {
      method: 'POST',
      body: JSON.stringify({ targets, session_id: sessionId || null }),
    }),
  listSessions: () => request<Session[]>('/api/sessions'),
  createSession: (title = '', default_agent_id = 'chat') =>
    request<Session>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ title, default_agent_id }),
    }),
  getSession: (sessionId: string) => request<Session>(`/api/sessions/${sessionId}`),
  updateSession: (sessionId: string, patch: Partial<Pick<Session, 'title' | 'default_agent_id' | 'llm_profile_id' | 'context_mode'>>) =>
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
  dismissNotification: (sessionId: string, notificationId: string) =>
    request<DismissNotificationResponse>(`/api/sessions/${sessionId}/notifications/${encodeURIComponent(notificationId)}/dismiss`, {
      method: 'POST',
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
  submitForm: (
    sessionId: string,
    payload: { source_message_id: string; form_id: string; values: Record<string, unknown> },
  ) =>
    request<RuntimeResponse>(`/api/sessions/${sessionId}/forms/submit`, {
      method: 'POST',
      body: JSON.stringify(payload),
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
