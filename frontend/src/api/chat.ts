import type { HistoryPage, HistoryUsersPage, HistoryQuery } from '../types/history';
import type { Persona, PersonaInput, Session, SessionPatch } from '../types/chat';
import type { Attachment } from '../types/messages';
import type { HistoryPruned, RuntimeResponse } from '../types/runs';
import { request, requestForm } from './http';
import type { MemoryDeletionChoice } from '../types/memory';

export const chatApi = {
  getSession: (sessionId: string, signal?: AbortSignal) => request<Session>(`/api/sessions/${encodeURIComponent(sessionId)}`, { signal }),
  updateSession: (sessionId: string, patch: SessionPatch) =>
    request<Session>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteSession: (sessionId: string, memory?: MemoryDeletionChoice) =>
    request<{ deleted: boolean; session_id: string }>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
      body: memory ? JSON.stringify(memory) : undefined,
    }),
  getHistory: (sessionId: string, query: HistoryQuery = {}, signal?: AbortSignal) =>
    request<HistoryPage>(`/api/sessions/${encodeURIComponent(sessionId)}/history?${new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)]))}`, { signal }),
  getHistoryUsers: (sessionId: string, query: HistoryQuery = {}) =>
    request<HistoryUsersPage>(`/api/sessions/${encodeURIComponent(sessionId)}/history/users?${new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)]))}`),
  sendMessage: (
    sessionId: string,
    content: string,
    attachments: Record<string, unknown>[] = [],
    clientMessageId = '',
  ) =>
    request<RuntimeResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({
        content,
        attachments,
        client_message_id: clientMessageId,
      }),
    }),
  deleteMessage: (messageId: string) =>
    request<HistoryPruned>(`/api/messages/${encodeURIComponent(messageId)}`, {
      method: 'DELETE',
    }),
  editMessage: (messageId: string, content: string, attachmentIds: string[], rerun = true) =>
    request<RuntimeResponse>(`/api/messages/${encodeURIComponent(messageId)}/edit`, {
      method: 'POST',
      body: JSON.stringify({ content, attachment_ids: attachmentIds, rerun }),
    }),
  listPersonas: () => request<Persona[]>('/api/personas'),
  createPersona: (value: PersonaInput) =>
    request<Persona>('/api/personas', { method: 'POST', body: JSON.stringify(value) }),
  patchPersona: (id: string, value: Partial<PersonaInput>) =>
    request<Persona>(`/api/personas/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(value) }),
  deletePersona: (id: string) =>
    request<{ deleted: boolean }>(`/api/personas/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  uploadAttachment: (file: File) => {
    const form = new FormData();
    form.append('file', file, file.name || 'attachment');
    return requestForm<Attachment & { uri: string }>('/api/attachments', form);
  },
  deleteAttachment: (id: string) =>
    request<{ deleted: boolean }>(`/api/attachments/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};
