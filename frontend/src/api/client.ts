import type {
  Attachment, EmbeddingModelProfile, GeneralSettings, KnowledgeBase, KnowledgeSearchResponse,
  KnowledgeSettings, KnowledgeSource, LlmDefaults, LlmProfile, LlmProfileInput,
  LlmProviderProfile, LlmProviderProfileInput, Message, PetListResponse, PetSettings,
  PetSettingsResponse, RuntimeEvent, RuntimeResponse, Run, RunEvent, Session,
  SessionKnowledgeBinding, SessionWorldbooksResponse, Worldbook, WorldbookEntry,
  WorldbookSettings,
} from '../types';
import { API_BASE_URL, createWebSocketUrlFromBase, joinApiUrl } from './url';

export { API_BASE_URL, joinApiUrl };

export class ApiError extends Error {
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.details = details;
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(joinApiUrl(API_BASE_URL, path), { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw toApiError(response.status, payload);
  return payload as T;
}

async function requestForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(joinApiUrl(API_BASE_URL, path), { method: 'POST', body });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw toApiError(response.status, payload);
  return payload as T;
}

function toApiError(status: number, payload: unknown): ApiError {
  const error = (payload as { error?: { code?: unknown; message?: unknown; details?: unknown } } | null)?.error;
  const code = typeof error?.code === 'string' ? error.code : 'HTTP_ERROR';
  const message = typeof error?.message === 'string' ? error.message : `Request failed: ${status}`;
  const details = error?.details && typeof error.details === 'object' ? error.details as Record<string, unknown> : {};
  return new ApiError(code, message, details);
}

export const api = {
  listSessions: () => request<Session[]>('/api/sessions'),
  createSession: (title = '', context_mode: Session['context_mode'] = 'single_assistant', llm_profile_id: string | null = null) =>
    request<Session>('/api/sessions', { method: 'POST', body: JSON.stringify({ title, context_mode, llm_profile_id }) }),
  getSession: (sessionId: string) => request<Session>(`/api/sessions/${encodeURIComponent(sessionId)}`),
  updateSession: (sessionId: string, patch: Partial<Pick<Session, 'title' | 'context_mode' | 'llm_profile_id'>>) =>
    request<Session>(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteSession: (sessionId: string) => request<{ deleted: boolean; session_id: string }>(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }),
  listMessages: (sessionId: string) => request<Message[]>(`/api/sessions/${encodeURIComponent(sessionId)}/messages`),
  getTimeline: (sessionId: string) => request<Array<{ kind: string; message?: Message; notification?: Record<string, unknown> }>>(`/api/sessions/${encodeURIComponent(sessionId)}/timeline`),
  sendMessage: (sessionId: string, content: string, attachments: Record<string, unknown>[] = [], clientMessageId = '') =>
    request<RuntimeResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, { method: 'POST', body: JSON.stringify({ content, attachments, client_message_id: clientMessageId }) }),
  deleteMessage: (messageId: string) => request<{ deleted: boolean; message_id: string }>(`/api/messages/${encodeURIComponent(messageId)}`, { method: 'DELETE' }),
  retryMessage: (messageId: string) => request<RuntimeResponse>(`/api/messages/${encodeURIComponent(messageId)}/retry`, { method: 'POST' }),
  editMessage: (messageId: string, content: string, rerun = true) => request<RuntimeResponse>(`/api/messages/${encodeURIComponent(messageId)}/edit`, { method: 'POST', body: JSON.stringify({ content, rerun }) }),
  dismissNotification: (sessionId: string, notificationId: string) => request<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(sessionId)}/notifications/${encodeURIComponent(notificationId)}/dismiss`, { method: 'POST' }),
  listRuns: (sessionId: string) => request<Run[]>(`/api/sessions/${encodeURIComponent(sessionId)}/runs`),
  getRun: (runId: string) => request<Run>(`/api/runs/${encodeURIComponent(runId)}`),
  listRunEvents: (runId: string) => request<RunEvent[]>(`/api/runs/${encodeURIComponent(runId)}/events`),
  cancelRun: (runId: string) => request<{ run: Run; cancelled: boolean; reason: string }>(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' }),

  getGeneralSettings: () => request<GeneralSettings>('/api/settings/general'),
  updateGeneralSettings: (patch: Record<string, unknown>) => request<GeneralSettings>('/api/settings/general', { method: 'PATCH', body: JSON.stringify(patch) }),
  getLlmDefaults: () => request<LlmDefaults>('/api/settings/llm-defaults'),
  updateLlmDefaults: (patch: Partial<LlmDefaults>) => request<LlmDefaults>('/api/settings/llm-defaults', { method: 'PATCH', body: JSON.stringify(patch) }),
  listLlmProfiles: () => request<LlmProfile[]>('/api/llm-profiles'),
  createLlmProfile: (profile: LlmProfileInput) => request<LlmProfile>('/api/llm-profiles', { method: 'POST', body: JSON.stringify(profile) }),
  patchLlmProfile: (id: string, patch: Record<string, unknown>) => request<LlmProfile>(`/api/llm-profiles/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteLlmProfile: (id: string) => request<{ deleted: boolean; profile_id: string }>(`/api/llm-profiles/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  duplicateLlmProfile: (id: string) => request<LlmProfile>(`/api/llm-profiles/${encodeURIComponent(id)}/duplicate`, { method: 'POST' }),
  testLlmProfile: (id: string) => request<{ success: boolean; message: string; models?: string[] }>(`/api/llm-profiles/${encodeURIComponent(id)}/test`, { method: 'POST' }),
  listLlmProfileModels: (id: string) => request<{ success: boolean; models: Array<{ id: string }> }>(`/api/llm-profiles/${encodeURIComponent(id)}/models`),
  listProviderProfiles: () => request<LlmProviderProfile[]>('/api/llm-provider-profiles'),
  createProviderProfile: (profile: LlmProviderProfileInput) => request<LlmProviderProfile>('/api/llm-provider-profiles', { method: 'POST', body: JSON.stringify(profile) }),
  patchProviderProfile: (id: string, patch: Record<string, unknown>) => request<LlmProviderProfile>(`/api/llm-provider-profiles/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteProviderProfile: (id: string) => request<{ deleted: boolean; profile_id: string }>(`/api/llm-provider-profiles/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  duplicateProviderProfile: (id: string) => request<LlmProviderProfile>(`/api/llm-provider-profiles/${encodeURIComponent(id)}/duplicate`, { method: 'POST' }),
  testProviderProfile: (id: string) => request<{ success: boolean; message: string; models?: string[] }>(`/api/llm-provider-profiles/${encodeURIComponent(id)}/test`, { method: 'POST' }),
  listProviderModels: (id: string) => request<{ success: boolean; provider_profile_id: string; models: Array<{ id: string }> }>(`/api/llm-provider-profiles/${encodeURIComponent(id)}/models`),

  getKnowledgeSettings: () => request<KnowledgeSettings>('/api/knowledge/settings'),
  updateKnowledgeSettings: (patch: Record<string, unknown>) => request<KnowledgeSettings>('/api/knowledge/settings', { method: 'PATCH', body: JSON.stringify(patch) }),
  listEmbeddingModels: () => request<EmbeddingModelProfile[]>('/api/knowledge/embedding-models'),
  createEmbeddingModel: (profile: Record<string, unknown>) => request<EmbeddingModelProfile>('/api/knowledge/embedding-models', { method: 'POST', body: JSON.stringify(profile) }),
  patchEmbeddingModel: (id: string, patch: Record<string, unknown>) => request<EmbeddingModelProfile>(`/api/knowledge/embedding-models/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteEmbeddingModel: (id: string) => request<{ deleted: boolean; profile_id: string }>(`/api/knowledge/embedding-models/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  scanKnowledgeModels: () => request<Record<string, unknown>>('/api/knowledge/models/scan'),
  listKnowledgeBases: () => request<KnowledgeBase[]>('/api/knowledge/bases'),
  createKnowledgeBase: (value: Record<string, unknown>) => request<KnowledgeBase>('/api/knowledge/bases', { method: 'POST', body: JSON.stringify(value) }),
  patchKnowledgeBase: (id: string, patch: Record<string, unknown>) => request<KnowledgeBase>(`/api/knowledge/bases/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteKnowledgeBase: (id: string) => request<{ deleted: boolean; knowledge_base_id: string }>(`/api/knowledge/bases/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  listKnowledgeSources: (baseId: string) => request<KnowledgeSource[]>(`/api/knowledge/bases/${encodeURIComponent(baseId)}/sources`),
  createPastedKnowledgeSource: (baseId: string, title: string, text: string) => request<KnowledgeSource>(`/api/knowledge/bases/${encodeURIComponent(baseId)}/sources`, { method: 'POST', body: JSON.stringify({ source_type: 'pasted_text', title, text }) }),
  createFileKnowledgeSource: (baseId: string, path: string, title?: string) => request<KnowledgeSource>(`/api/knowledge/bases/${encodeURIComponent(baseId)}/sources`, { method: 'POST', body: JSON.stringify({ source_type: 'file', path, title }) }),
  deleteKnowledgeSource: (id: string) => request<{ deleted: boolean; source_id: string }>(`/api/knowledge/sources/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  reindexKnowledgeSource: (id: string) => request<Record<string, unknown>>(`/api/knowledge/sources/${encodeURIComponent(id)}/reindex`, { method: 'POST' }),
  reindexKnowledgeBase: (id: string) => request<Record<string, unknown>>(`/api/knowledge/bases/${encodeURIComponent(id)}/reindex`, { method: 'POST' }),
  getKnowledgeSourcePreview: (id: string) => request<{ source_id: string; title: string; uri: string; content: string; truncated: boolean }>(`/api/knowledge/sources/${encodeURIComponent(id)}/preview`),
  searchKnowledge: (payload: { query: string; knowledge_base_ids?: string[]; session_id?: string; top_k?: number; max_context_chars?: number; debug?: boolean }) => request<KnowledgeSearchResponse>('/api/knowledge/search', { method: 'POST', body: JSON.stringify(payload) }),
  listSessionKnowledgeBases: (sessionId: string) => request<SessionKnowledgeBinding[]>(`/api/sessions/${encodeURIComponent(sessionId)}/knowledge-bases`),
  updateSessionKnowledgeBases: (sessionId: string, ids: string[]) => request<SessionKnowledgeBinding[]>(`/api/sessions/${encodeURIComponent(sessionId)}/knowledge-bases`, { method: 'PATCH', body: JSON.stringify({ knowledge_base_ids: ids }) }),

  getWorldbookSettings: () => request<WorldbookSettings>('/api/worldbook/settings'),
  updateWorldbookSettings: (patch: Record<string, unknown>) => request<WorldbookSettings>('/api/worldbook/settings', { method: 'PATCH', body: JSON.stringify(patch) }),
  listWorldbooks: () => request<Worldbook[]>('/api/worldbooks'),
  createWorldbook: (value: Record<string, unknown>) => request<Worldbook>('/api/worldbooks', { method: 'POST', body: JSON.stringify(value) }),
  patchWorldbook: (id: string, patch: Record<string, unknown>) => request<Worldbook>(`/api/worldbooks/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteWorldbook: (id: string) => request<{ deleted: boolean; worldbook_id: string }>(`/api/worldbooks/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  listWorldbookEntries: (id: string) => request<WorldbookEntry[]>(`/api/worldbooks/${encodeURIComponent(id)}/entries`),
  createWorldbookEntry: (id: string, value: Record<string, unknown>) => request<WorldbookEntry>(`/api/worldbooks/${encodeURIComponent(id)}/entries`, { method: 'POST', body: JSON.stringify(value) }),
  patchWorldbookEntry: (id: string, patch: Record<string, unknown>) => request<WorldbookEntry>(`/api/worldbook-entries/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteWorldbookEntry: (id: string) => request<{ deleted: boolean; entry_id: string }>(`/api/worldbook-entries/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getSessionWorldbooks: (sessionId: string) => request<SessionWorldbooksResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/worldbooks`),
  updateSessionWorldbooks: (sessionId: string, ids: string[]) => request<SessionWorldbooksResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/worldbooks`, { method: 'PATCH', body: JSON.stringify({ worldbook_ids: ids }) }),

  getPetSettings: () => request<PetSettingsResponse>('/api/pets/settings'),
  updatePetSettings: (values: Partial<PetSettings>) => request<PetSettingsResponse>('/api/pets/settings', { method: 'PATCH', body: JSON.stringify({ values }) }),
  listPets: () => request<PetListResponse>('/api/pets'),
  scanPets: () => request<PetListResponse>('/api/pets/scan', { method: 'POST' }),
  importPet: (manifest: File, spritesheet: File) => { const form = new FormData(); form.append('pet_json', manifest, 'pet.json'); form.append('spritesheet', spritesheet, 'spritesheet.webp'); return requestForm<{ pets: PetListResponse['pets']; settings: PetSettings }>('/api/pets/import', form); },
  deletePet: (id: string) => request<{ deleted: boolean; pet_id: string; pets: PetListResponse['pets'] }>(`/api/pets/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  uploadAttachment: (file: File) => { const form = new FormData(); form.append('file', file, file.name || 'attachment'); return requestForm<Attachment>('/api/attachments', form); },

  getRuntimeResources: () => request<Record<string, unknown>>('/api/runtime/resources'),
  getRuntimeMemory: (sessionId?: string) => request<Record<string, unknown>>(`/api/runtime/memory${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`),
  freeRuntimeMemory: (targets: string[], sessionId?: string) => request<Record<string, unknown>>('/api/runtime/free-memory', { method: 'POST', body: JSON.stringify({ targets, session_id: sessionId ?? null }) }),
  getHealthDetails: () => request<Record<string, unknown>>('/api/health/details'),
};

export function createWebSocketUrl(sessionId: string): string {
  return createWebSocketUrlFromBase(API_BASE_URL, sessionId, window.location.origin);
}

export type { RuntimeEvent };
