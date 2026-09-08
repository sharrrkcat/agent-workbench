import type { SessionWorldbooksResponse, Worldbook, WorldbookEntry, WorldbookSettings, WorldbookInput, WorldbookEntryInput, WorldbookSettingsInput, WorldbookMatchResponse } from '../types/worldbook';
import { request } from './http';

export const worldbookApi = {
  getWorldbookSettings: () => request<WorldbookSettings>('/api/worldbook/settings'),
  updateWorldbookSettings: (patch: Partial<WorldbookSettingsInput>) =>
    request<WorldbookSettings>('/api/worldbook/settings', { method: 'PATCH', body: JSON.stringify(patch) }),
  listWorldbooks: () => request<Worldbook[]>('/api/worldbooks'),
  getWorldbook: (id: string) => request<Worldbook>(`/api/worldbooks/${encodeURIComponent(id)}`),
  createWorldbook: (value: WorldbookInput) =>
    request<Worldbook>('/api/worldbooks', { method: 'POST', body: JSON.stringify(value) }),
  patchWorldbook: (id: string, patch: Partial<WorldbookInput>) =>
    request<Worldbook>(`/api/worldbooks/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteWorldbook: (id: string) =>
    request<{ deleted: boolean; worldbook_id: string }>(`/api/worldbooks/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  listWorldbookEntries: (id: string) => request<WorldbookEntry[]>(`/api/worldbooks/${encodeURIComponent(id)}/entries`),
  createWorldbookEntry: (id: string, value: WorldbookEntryInput) =>
    request<WorldbookEntry>(`/api/worldbooks/${encodeURIComponent(id)}/entries`, {
      method: 'POST',
      body: JSON.stringify(value),
    }),
  patchWorldbookEntry: (id: string, patch: Partial<WorldbookEntryInput>) =>
    request<WorldbookEntry>(`/api/worldbook-entries/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteWorldbookEntry: (id: string) =>
    request<{ deleted: boolean; entry_id: string }>(`/api/worldbook-entries/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  reorderWorldbookEntries: (id: string, entryIds: string[]) =>
    request<{ worldbook_id: string; entries: WorldbookEntry[] }>(`/api/worldbooks/${encodeURIComponent(id)}/entries/reorder`, {
      method: 'PATCH', body: JSON.stringify({ entry_ids: entryIds }),
    }),
  matchWorldbooks: (value: { text: string; worldbook_ids: string[] }) =>
    request<WorldbookMatchResponse>('/api/worldbooks/match-test', { method: 'POST', body: JSON.stringify(value) }),
  getSessionWorldbooks: (sessionId: string) =>
    request<SessionWorldbooksResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/worldbooks`),
  updateSessionWorldbooks: (sessionId: string, ids: string[]) =>
    request<SessionWorldbooksResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/worldbooks`, {
      method: 'PATCH',
      body: JSON.stringify({ worldbook_ids: ids }),
    }),
};
