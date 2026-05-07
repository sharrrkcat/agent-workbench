import { API_BASE_URL } from '../api/client';
import type { Attachment } from '../types';

export type ImagePreview = {
  url: string;
  alt?: string | null;
  title?: string | null;
  caption?: string | null;
};

export function safeImageUrl(value: string | null | undefined): string {
  return resolveAttachmentUrl(value);
}

export function resolveAttachmentUrl(value: string | Attachment | null | undefined): string {
  const raw = typeof value === 'string' ? value : value?.uri || value?.data_url || '';
  const trimmed = raw.trim();
  if (!trimmed) return '';
  if (/^local:\/\/attachments\/[a-f0-9-]+\.[a-z0-9]+$/i.test(trimmed)) {
    return `${API_BASE_URL}/api/attachments/${encodeURIComponent(trimmed.replace(/^local:\/\/attachments\//i, ''))}`;
  }
  if (/^\/api\/attachments\/[a-f0-9-]+\.[a-z0-9]+$/i.test(trimmed)) {
    return `${API_BASE_URL}${trimmed}`;
  }
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^data:image\/(?:png|jpe?g|webp|gif|svg\+xml);base64,[a-z0-9+/=\s]+$/i.test(trimmed)) return trimmed;
  return '';
}

export function attachmentImageUrl(value: string | null | undefined): string {
  return safeImageUrl(value);
}

export function localAttachmentUrl(value: string | null | undefined): string {
  return resolveAttachmentUrl(value);
}
