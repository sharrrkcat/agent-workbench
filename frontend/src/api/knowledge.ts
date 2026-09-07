import type {
  KnowledgeBase,
  KnowledgeSearchResponse,
  KnowledgeSettings,
  KnowledgeSource,
  SessionKnowledgeBindings,
} from '../types/knowledge';
import type { BindingMode } from '../types/chat';
import { request } from './http';

export const knowledgeApi = {
  getKnowledgeSettings: () => request<KnowledgeSettings>('/api/knowledge/settings'),
  updateKnowledgeSettings: (patch: Record<string, unknown>) =>
    request<KnowledgeSettings>('/api/knowledge/settings', { method: 'PATCH', body: JSON.stringify(patch) }),
  listKnowledgeBases: () => request<KnowledgeBase[]>('/api/knowledge/bases'),
  createKnowledgeBase: (value: Record<string, unknown>) =>
    request<KnowledgeBase>('/api/knowledge/bases', { method: 'POST', body: JSON.stringify(value) }),
  patchKnowledgeBase: (id: string, patch: Record<string, unknown>) =>
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
    request<KnowledgeSource>(`/api/knowledge/bases/${encodeURIComponent(baseId)}/sources`, {
      method: 'POST',
      body: JSON.stringify({ source_type: 'pasted_text', title, text }),
    }),
  createFileKnowledgeSource: (baseId: string, path: string, title?: string) =>
    request<KnowledgeSource>(`/api/knowledge/bases/${encodeURIComponent(baseId)}/sources`, {
      method: 'POST',
      body: JSON.stringify({ source_type: 'file', path, title }),
    }),
  deleteKnowledgeSource: (id: string) =>
    request<{ deleted: boolean; source_id: string }>(`/api/knowledge/sources/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  reindexKnowledgeSource: (id: string) =>
    request<Record<string, unknown>>(`/api/knowledge/sources/${encodeURIComponent(id)}/reindex`, { method: 'POST' }),
  reindexKnowledgeBase: (id: string) =>
    request<Record<string, unknown>>(`/api/knowledge/bases/${encodeURIComponent(id)}/reindex`, { method: 'POST' }),
  getKnowledgeSourcePreview: (id: string) =>
    request<{ source_id: string; title: string; uri: string; content: string; truncated: boolean }>(
      `/api/knowledge/sources/${encodeURIComponent(id)}/preview`,
    ),
  searchKnowledge: (payload: {
    query: string;
    knowledge_base_ids?: string[];
    session_id?: string;
    top_k?: number;
    max_context_chars?: number;
    debug?: boolean;
  }) => request<KnowledgeSearchResponse>('/api/knowledge/search', { method: 'POST', body: JSON.stringify(payload) }),
  listSessionKnowledgeBases: (sessionId: string) =>
    request<SessionKnowledgeBindings>(`/api/sessions/${encodeURIComponent(sessionId)}/knowledge-bases`),
  updateSessionKnowledgeBases: (sessionId: string, mode: BindingMode, ids?: string[]) =>
    request<SessionKnowledgeBindings>(`/api/sessions/${encodeURIComponent(sessionId)}/knowledge-bases`, {
      method: 'PATCH',
      body: JSON.stringify({ mode, knowledge_base_ids: ids }),
    }),
};
