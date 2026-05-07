import { API_BASE_URL } from '../api/client';
import { resolveAttachmentUrlFromBase } from '../api/url';
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
  return resolveAttachmentUrlFromBase(API_BASE_URL, raw);
}

export function attachmentImageUrl(value: string | null | undefined): string {
  return safeImageUrl(value);
}

export function localAttachmentUrl(value: string | null | undefined): string {
  return resolveAttachmentUrl(value);
}
