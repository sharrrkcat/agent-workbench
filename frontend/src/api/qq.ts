import { request } from './http';
import type { QQSession } from '../types/chat';
export type QQBinding = { session_id: string; project_id: string; target_kind: 'group' | 'friend'; target_id: string; paused: boolean; pause_reason: string; deadline: number | null };
export type QQMessage = { id: number; external_id: string; sender_id: string; sender_name: string; timestamp: string; text: string; disposition: 'pending' | 'batched' | 'skipped'; batch_id: number | null; references: { type: 'at' | 'reply'; id: string }[] };
export type QQBatch = { id: number; status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'interrupted'; text: string; created_at: number; run_id: string | null; error_code: string | null };
export type QQDelivery = { id: number; run_id: string; text: string; status: 'pending' | 'sending' | 'sent' | 'failed' | 'unknown'; external_id: string | null; echoed: boolean; error_code: string | null; created_at: number };
export type QQPage<T> = { items: T[]; next_cursor: number | null };
const path = (id: string) => `/api/qq/sessions/${encodeURIComponent(id)}`;
export const qqApi = {
  createSession: (id: string, values: { title: string; target_kind: 'group' | 'friend'; target_id: string }) =>
    request<QQSession>(`/api/projects/${encodeURIComponent(id)}/sessions`, { method: 'POST', body: JSON.stringify(values) }),
  status: (id: string) => request<{ status: string; connected: boolean }>(`/api/qq/projects/${encodeURIComponent(id)}/status`),
  binding: (id: string) => request<QQBinding>(path(id)),
  control: (id: string, action: 'pause' | 'resume' | 'stop') => request<QQBinding>(path(id) + '/control', { method: 'POST', body: JSON.stringify({ action }) }),
  messages: (id: string, before?: number) => request<QQPage<QQMessage>>(path(id) + '/messages' + (before ? `?before=${before}` : '')),
  batches: (id: string, before?: number) => request<QQPage<QQBatch>>(path(id) + '/batches' + (before ? `?before=${before}` : '')),
  deliveries: (id: string, before?: number) => request<QQPage<QQDelivery>>(path(id) + '/deliveries' + (before ? `?before=${before}` : '')),
};
