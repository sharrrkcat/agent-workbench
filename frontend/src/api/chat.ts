import type { Persona, PersonaInput, Session, SessionPatch } from '../types/chat';
import type { Attachment, Message } from '../types/messages';
import type { RuntimeResponse } from '../types/runs';
import { request, requestForm } from './http';

export const chatApi = {
  listSessions: () => request<Session[]>('/api/sessions'),
  createSession: (values: SessionPatch = {}) =>
    request<Session>('/api/sessions', { method: 'POST', body: JSON.stringify(values) }),
  getSession: (sessionId: string) => request<Session>(`/api/sessions/${encodeURIComponent(sessionId)}`),
  updateSession: (sessionId: string, patch: SessionPatch) =>
    request<Session>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteSession: (sessionId: string) =>
    request<{ deleted: boolean; session_id: string }>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    }),
  listMessages: (sessionId: string) => request<Message[]>(`/api/sessions/${encodeURIComponent(sessionId)}/messages`),
  getTimeline: (sessionId: string) =>
    request<Array<{ kind: string; message?: Message; notification?: Record<string, unknown> }>>(
      `/api/sessions/${encodeURIComponent(sessionId)}/timeline`,
    ),
  sendMessage: (
    sessionId: string,
    content: string,
    attachments: Record<string, unknown>[] = [],
    clientMessageId = '',
    sourceMessageId: string | null = null,
  ) =>
    request<RuntimeResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({
        content,
        attachments,
        client_message_id: clientMessageId,
        source_message_id: sourceMessageId,
      }),
    }),
  deleteMessage: (messageId: string) =>
    request<{ deleted: boolean; message_id: string }>(`/api/messages/${encodeURIComponent(messageId)}`, {
      method: 'DELETE',
    }),
  retryMessage: (messageId: string) =>
    request<RuntimeResponse>(`/api/messages/${encodeURIComponent(messageId)}/retry`, { method: 'POST' }),
  editMessage: (messageId: string, content: string, rerun = true) =>
    request<RuntimeResponse>(`/api/messages/${encodeURIComponent(messageId)}/edit`, {
      method: 'POST',
      body: JSON.stringify({ content, rerun }),
    }),
  dismissNotification: (sessionId: string, notificationId: string) =>
    request<{ ok: boolean }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/notifications/${encodeURIComponent(notificationId)}/dismiss`,
      { method: 'POST' },
    ),
  listPersonas: () => request<Persona[]>('/api/personas'),
  createPersona: (value: PersonaInput) =>
    request<Persona>('/api/personas', { method: 'POST', body: JSON.stringify(value) }),
  patchPersona: (id: string, value: Partial<PersonaInput>) =>
    request<Persona>(`/api/personas/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(value) }),
  deletePersona: (id: string) =>
    request<{ deleted: boolean }>(`/api/personas/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getPersonaKnowledge: (id: string) =>
    request<{ knowledge_base_ids: string[] }>(`/api/personas/${encodeURIComponent(id)}/knowledge-bases`),
  patchPersonaKnowledge: (id: string, ids: string[]) =>
    request<{ knowledge_base_ids: string[] }>(`/api/personas/${encodeURIComponent(id)}/knowledge-bases`, {
      method: 'PATCH',
      body: JSON.stringify({ knowledge_base_ids: ids }),
    }),
  getPersonaWorldbooks: (id: string) =>
    request<{ worldbook_ids: string[] }>(`/api/personas/${encodeURIComponent(id)}/worldbooks`),
  patchPersonaWorldbooks: (id: string, ids: string[]) =>
    request<{ worldbook_ids: string[] }>(`/api/personas/${encodeURIComponent(id)}/worldbooks`, {
      method: 'PATCH',
      body: JSON.stringify({ worldbook_ids: ids }),
    }),
  uploadAttachment: (file: File) => {
    const form = new FormData();
    form.append('file', file, file.name || 'attachment');
    return requestForm<Attachment>('/api/attachments', form);
  },
  deleteAttachment: (id: string) =>
    request<{ deleted: boolean }>(`/api/attachments/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};
