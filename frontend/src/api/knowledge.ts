import type {
  KnowledgeBase,
  KnowledgeSearchResponse,
  KnowledgeSettings,
  KnowledgeSource,
  SessionKnowledgeBindings,
  KnowledgeBaseInput, KnowledgeSettingsInput, KnowledgeSourceIndexResult, KnowledgeSourcePreview, KnowledgeSourceChunk, KnowledgeSearchInput,
} from '../types/knowledge';
import { request } from './http';

export const knowledgeApi = {
  getKnowledgeSettings: () => request<KnowledgeSettings>('/api/knowledge/settings'),
  updateKnowledgeSettings: (patch: Partial<KnowledgeSettingsInput>) =>
    request<KnowledgeSettings>('/api/knowledge/settings', { method: 'PATCH', body: JSON.stringify(patch) }),
  listKnowledgeBases: () => request<KnowledgeBase[]>('/api/knowledge/bases'),
  getKnowledgeBase: (id: string) => request<KnowledgeBase>(`/api/knowledge/bases/${encodeURIComponent(id)}`),
  createKnowledgeBase: (value: KnowledgeBaseInput) =>
    request<KnowledgeBase>('/api/knowledge/bases', { method: 'POST', body: JSON.stringify(value) }),
  patchKnowledgeBase: (id: string, patch: Partial<KnowledgeBaseInput>) =>
    request<KnowledgeBase>(`/api/knowledge/bases/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteKnowledgeBase: (id: string) =>
    request<{ deleted: boolean; knowledge_base_id: string }>(`/api/knowledge/bases/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  listKnowledgeSources: (baseId: string) =>
    request<KnowledgeSource[]>(`/api/knowledge/bases/${encodeURIComponent(baseId)}/sources`),
  createPastedKnowledgeSource: (baseId: string, title: string, text: string) =>
    request<KnowledgeSourceIndexResult>(`/api/knowledge/bases/${encodeURIComponent(baseId)}/sources`, {
      method: 'POST',
      body: JSON.stringify({ source_type: 'pasted_text', title, text }),
    }),
  createFileKnowledgeSource: (baseId: string, path: string, title?: string) =>
    request<KnowledgeSourceIndexResult>(`/api/knowledge/bases/${encodeURIComponent(baseId)}/sources`, {
      method: 'POST',
      body: JSON.stringify({ source_type: 'file', path, title }),
    }),
  createAttachmentKnowledgeSource: (baseId: string, attachmentId: string, title: string) =>
    request<KnowledgeSourceIndexResult>(`/api/knowledge/bases/${encodeURIComponent(baseId)}/sources`, {
      method: 'POST', body: JSON.stringify({ source_type: 'attachment_text', attachment_id: attachmentId, title }),
    }),
  deleteKnowledgeSource: (id: string) =>
    request<{ deleted: boolean; source_id: string }>(`/api/knowledge/sources/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  reindexKnowledgeSource: (id: string) =>
    request<KnowledgeSourceIndexResult>(`/api/knowledge/sources/${encodeURIComponent(id)}/reindex`, { method: 'POST' }),
  reindexKnowledgeBase: (id: string) =>
    request<{ knowledge_base_id: string; sources: KnowledgeSourceIndexResult[] }>(`/api/knowledge/bases/${encodeURIComponent(id)}/reindex`, { method: 'POST' }),
  getKnowledgeSourcePreview: (id: string) =>
    request<KnowledgeSourcePreview>(
      `/api/knowledge/sources/${encodeURIComponent(id)}/preview`,
    ),
  listKnowledgeSourceChunks: (id: string) =>
    request<{ source_id: string; chunks: KnowledgeSourceChunk[] }>(`/api/knowledge/sources/${encodeURIComponent(id)}/chunks`),
  searchKnowledge: (payload: KnowledgeSearchInput) => request<KnowledgeSearchResponse>('/api/knowledge/search', { method: 'POST', body: JSON.stringify(payload) }),
  listSessionKnowledgeBases: (sessionId: string) =>
    request<SessionKnowledgeBindings>(`/api/sessions/${encodeURIComponent(sessionId)}/knowledge-bases`),
  updateSessionKnowledgeBases: (sessionId: string, ids: string[]) =>
    request<SessionKnowledgeBindings>(`/api/sessions/${encodeURIComponent(sessionId)}/knowledge-bases`, {
      method: 'PATCH',
      body: JSON.stringify({ knowledge_base_ids: ids }),
    }),
};
