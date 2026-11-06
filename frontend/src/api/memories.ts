import { request } from './http';
import type { MemoryCreate, MemoryEdit, MemoryEntry, MemoryPage, MemoryQuery, MemoryDeletionPreview } from '../types/memory';

const path = (id: string) => `/api/memories/${encodeURIComponent(id)}`;
const queryString = (values: object) => new URLSearchParams(Object.entries(values)
  .filter(([, value]) => value !== undefined && value !== '').map(([key, value]) => [key, String(value)])).toString();
export const memoriesApi = {
  list: (values: MemoryQuery = {}, signal?: AbortSignal) => request<MemoryPage>(`/api/memories?${queryString(values)}`, { signal }),
  get: (id: string, signal?: AbortSignal) => request<MemoryEntry>(path(id), { signal }),
  create: (value: MemoryCreate) => request<MemoryEntry>('/api/memories', { method: 'POST', body: JSON.stringify(value) }),
  edit: (id: string, value: MemoryEdit) => request<MemoryEntry>(path(id), { method: 'PATCH', body: JSON.stringify(value) }),
  forget: (id: string, revision: number) => request<{ deleted: boolean }>(path(id), { method: 'DELETE', body: JSON.stringify({ expected_revision: revision }) }),
  publish: (id: string, revision: number) => request<MemoryEntry>(path(id) + '/publish', { method: 'POST', body: JSON.stringify({ expected_revision: revision }) }),
  session: (id: string, values: { q?: string; own?: boolean; offset?: number } = {}, signal?: AbortSignal) =>
    request<MemoryPage>(`/api/sessions/${encodeURIComponent(id)}/memories?${queryString(values)}`, { signal }),
  sessionEntry: (sessionId: string, id: string, signal?: AbortSignal) =>
    request<MemoryEntry>(`/api/sessions/${encodeURIComponent(sessionId)}/memories/${encodeURIComponent(id)}`, { signal }),
  deletionPreview: (kind: 'session' | 'character', id: string) =>
    request<MemoryDeletionPreview>(`/api/${kind === 'session' ? 'sessions' : 'characters'}/${encodeURIComponent(id)}/memory-deletion-preview`),
};
