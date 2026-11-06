import { request } from './http';
import type { QQSession } from '../types/chat';
import type { Run } from '../types/runs';
import type { HistoryQuery } from '../types/history';
export type QQBinding = { session_id: string; character_id: string; target_kind: 'group' | 'friend'; target_id: string; paused: boolean; pause_reason: string; deadline: number | null; history_version: number; busy: boolean };
export type QQImageSegment = { type: 'image'; media_id: number; asset_id: number | null; description: string | null; kind: 'image' | 'sticker' | 'face'; status: 'pending' | 'ready' | 'failed' | 'deleted'; label: string; error_code: string | null; attachment: { id: string; type: 'image'; name: string; mime_type: 'image/png' | 'image/jpeg' | 'image/webp' | 'image/gif'; size: number; uri: string; width: number; height: number } | null };
export type QQSegment = { type: 'text'; text: string } | QQImageSegment;
export type QQMessage = { id: number; external_id: string; sender_id: string; sender_name: string; timestamp: string; text: string; segments: QQSegment[]; kind: 'chat' | 'command'; command_status: 'pending' | 'done' | null; disposition: 'pending' | 'batched' | 'skipped' | 'command'; batch_id: number | null; references: { type: 'at' | 'reply'; id: string; name: string | null; is_self: boolean }[] };
export type QQDelivery = { id: number; run_id: string | null; origin: 'model' | 'command' | 'notification'; command_message_id: number | null; notification_id: number | null; text: string; status: 'pending' | 'sending' | 'sent' | 'failed' | 'unknown' | 'cancelled'; external_id: string | null; echoed: boolean; error_code: string | null; created_at: number;
  kind: 'text' | 'generated_image' | 'resource_image'; prompt: string | null; asset_id: number | null; description: string | null; attachment: QQImageSegment['attachment'] };
export type QQHistoryItem = { id: string; cursor: string; created_at: string } & (
  { kind: 'incoming'; message: QQMessage } | { kind: 'reply'; run: Run; deliveries: QQDelivery[] }
  | { kind: 'program'; delivery: QQDelivery });
export type QQHistoryPage = { items: QQHistoryItem[]; binding: QQBinding; history_version: number;
  before_cursor: string | null; after_cursor: string | null; has_before: boolean; has_after: boolean;
  active_run: Run | null; latest_run: Run | null };
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
    request<QQSession>(`/api/characters/${encodeURIComponent(id)}/sessions`, { method: 'POST', body: JSON.stringify(values) }),
  status: (id: string, signal?: AbortSignal) => request<{ status: string; connected: boolean }>(`/api/qq/characters/${encodeURIComponent(id)}/status`, { signal }),
  history: (id: string, query: HistoryQuery = {}, signal?: AbortSignal) => request<QQHistoryPage>(path(id) + '/history?' +
    new URLSearchParams(Object.entries(query).map(([key, value]) => [key, String(value)])), { signal }),
  binding: (id: string) => request<QQBinding>(path(id)),
  control: (id: string, action: 'pause' | 'resume' | 'stop') => request<QQBinding>(path(id) + '/control', { method: 'POST', body: JSON.stringify({ action }) }),
  remove: (id: string, target: QQDeleteTarget) => request<QQHistoryPruned>(target.kind === 'reply'
    ? `/api/runs/${encodeURIComponent(target.id)}` : path(id) + `/${target.kind === 'message' ? 'messages' : 'deliveries'}/${target.id}`,
    { method: 'DELETE' }),
};
