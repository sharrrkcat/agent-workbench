import type { SessionWorldbooksResponse, Worldbook, WorldbookEntry, WorldbookSettings } from '../types/worldbook';
import { request } from './http';

export const worldbookApi = {
  getWorldbookSettings: () => request<WorldbookSettings>('/api/worldbook/settings'),
  updateWorldbookSettings: (patch: Record<string, unknown>) =>
    request<WorldbookSettings>('/api/worldbook/settings', { method: 'PATCH', body: JSON.stringify(patch) }),
  listWorldbooks: () => request<Worldbook[]>('/api/worldbooks'),
  createWorldbook: (value: Record<string, unknown>) =>
    request<Worldbook>('/api/worldbooks', { method: 'POST', body: JSON.stringify(value) }),
  patchWorldbook: (id: string, patch: Record<string, unknown>) =>
    request<Worldbook>(`/api/worldbooks/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteWorldbook: (id: string) =>
    request<{ deleted: boolean; worldbook_id: string }>(`/api/worldbooks/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  listWorldbookEntries: (id: string) => request<WorldbookEntry[]>(`/api/worldbooks/${encodeURIComponent(id)}/entries`),
  createWorldbookEntry: (id: string, value: Record<string, unknown>) =>
    request<WorldbookEntry>(`/api/worldbooks/${encodeURIComponent(id)}/entries`, {
      method: 'POST',
      body: JSON.stringify(value),
    }),
  patchWorldbookEntry: (id: string, patch: Record<string, unknown>) =>
    request<WorldbookEntry>(`/api/worldbook-entries/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteWorldbookEntry: (id: string) =>
    request<{ deleted: boolean; entry_id: string }>(`/api/worldbook-entries/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  getSessionWorldbooks: (sessionId: string) =>
    request<SessionWorldbooksResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/worldbooks`),
  updateSessionWorldbooks: (sessionId: string, ids: string[]) =>
    request<SessionWorldbooksResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/worldbooks`, {
      method: 'PATCH',
      body: JSON.stringify({ worldbook_ids: ids }),
    }),
};
