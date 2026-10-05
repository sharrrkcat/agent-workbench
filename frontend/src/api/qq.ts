import { request } from './http';
import type { QQSession } from '../types/chat';
export type QQBinding = { session_id: string; project_id: string; target_kind: 'group' | 'friend'; target_id: string; paused: boolean; pause_reason: string; deadline: number | null; history_version: number; busy: boolean };
export type QQImageSegment = { type: 'image'; media_id: number; asset_id: number | null; description: string | null; kind: 'image' | 'sticker' | 'face'; status: 'pending' | 'ready' | 'failed' | 'deleted'; label: string; error_code: string | null; attachment: { id: string; type: 'image'; name: string; mime_type: 'image/png' | 'image/jpeg' | 'image/webp' | 'image/gif'; size: number; uri: string; width: number; height: number } | null };
export type QQSegment = { type: 'text'; text: string } | QQImageSegment;
export type QQMessage = { id: number; external_id: string; sender_id: string; sender_name: string; timestamp: string; text: string; segments: QQSegment[]; disposition: 'pending' | 'batched' | 'skipped'; batch_id: number | null; references: { type: 'at' | 'reply'; id: string; name: string | null; is_self: boolean }[] };
export type QQBatch = { id: number; status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'interrupted'; trigger_kind: 'keyword' | 'followup' | 'private' | 'icebreaker'; text: string; created_at: number; run_id: string | null; error_code: string | null };
export type QQDelivery = { id: number; run_id: string; text: string; status: 'pending' | 'sending' | 'sent' | 'failed' | 'unknown'; external_id: string | null; echoed: boolean; error_code: string | null; created_at: number;
  kind: 'text' | 'generated_image'; prompt: string | null; asset_id: number | null; description: string | null; attachment: QQImageSegment['attachment'] };
export type QQPage<T> = { items: T[]; next_cursor: number | null; history_version: number };
export type QQHistoryPruned = { deleted_message_ids: string[]; deleted_run_ids: string[]; deleted_qq_message_ids: number[]; deleted_qq_delivery_ids: number[]; history_version: number };
export type QQDeleteTarget = { kind: 'message' | 'delivery'; id: number } | { kind: 'reply'; id: string };
export type QQResource = { id: number; attachment: NonNullable<QQImageSegment['attachment']>; description: string | null;
  is_favorite: boolean; created_at: string; has_references: boolean };
export type QQResourceQuery = { page: number; sort: 'created_at' | 'size'; order: 'asc' | 'desc'; favorite: 'all' | 'favorites' | 'unfavorited' };
export type QQResourcePage = { items: QQResource[]; total: number; page: number; page_size: number };
export const qqResourcesApi = {
  list: (query: QQResourceQuery) => request<QQResourcePage>('/api/qq/resources?' + new URLSearchParams({
    ...query, page: String(query.page), page_size: '30' })),
  update: (id: number, values: { description?: string | null; is_favorite?: boolean }) =>
    request<QQResource>(`/api/qq/resources/${id}`, { method: 'PATCH', body: JSON.stringify(values) }),
  remove: (id: number) => request<{ deleted: boolean }>(`/api/qq/resources/${id}`, { method: 'DELETE' }),
};
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
  remove: (id: string, target: QQDeleteTarget) => request<QQHistoryPruned>(target.kind === 'reply'
    ? `/api/runs/${encodeURIComponent(target.id)}` : path(id) + `/${target.kind === 'message' ? 'messages' : 'deliveries'}/${target.id}`,
    { method: 'DELETE' }),
};
