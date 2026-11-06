import type { Character, CharacterInput, CharacterPatch } from '../types/characters';
import type { NormalSession, SessionPatch, Session } from '../types/chat';
import { request } from './http';
import type { MemoryDeletionChoice } from '../types/memory';

const path = (id: string) => `/api/characters/${encodeURIComponent(id)}`;

export const charactersApi = {
  list: () => request<Character[]>('/api/characters'),
  get: (id: string) => request<Character>(path(id)),
  create: (values: CharacterInput) => request<Character>('/api/characters', { method: 'POST', body: JSON.stringify(values) }),
  update: (id: string, values: CharacterPatch) => request<Character>(path(id), { method: 'PATCH', body: JSON.stringify(values) }),
  remove: (id: string, memory?: MemoryDeletionChoice) => request<{ deleted: boolean; character_id: string; deleted_session_ids: string[] }>(path(id), { method: 'DELETE', body: memory ? JSON.stringify(memory) : undefined }),
  listSessions: (id: string) => request<Session[]>(path(id) + '/sessions'),
  createSession: (id: string, values: SessionPatch = {}) => request<NormalSession>(path(id) + '/sessions', {
    method: 'POST', body: JSON.stringify(values),
  }),
};
