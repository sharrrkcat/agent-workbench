export type ImagePreview = {
  url: string;
  alt?: string | null;
  title?: string | null;
  caption?: string | null;
};

export function safeImageUrl(value: string | null | undefined): string {
  const trimmed = value?.trim() ?? '';
  if (!trimmed) return '';
  if (/^local:\/\/attachments\/[a-f0-9-]+\.(?:png|jpe?g|webp|gif|svg)$/i.test(trimmed)) {
    return `/api/attachments/${encodeURIComponent(trimmed.replace(/^local:\/\/attachments\//i, ''))}`;
  }
  if (/^https?:\/\//i.test(trimmed) || trimmed.startsWith('/')) return trimmed;
  if (/^data:image\/(?:png|jpe?g|webp|gif|svg\+xml);base64,[a-z0-9+/=\s]+$/i.test(trimmed)) return trimmed;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(trimmed) && !trimmed.startsWith('//') && /^[^\s<>"']+$/i.test(trimmed)) return trimmed;
  return '';
}

export function attachmentImageUrl(value: string | null | undefined): string {
  return safeImageUrl(value);
}

export function localAttachmentUrl(value: string | null | undefined): string {
  const trimmed = String(value || '').trim();
  if (/^local:\/\/attachments\/[a-f0-9-]+\.[a-z0-9]+$/i.test(trimmed)) {
    return `/api/attachments/${encodeURIComponent(trimmed.replace(/^local:\/\/attachments\//i, ''))}`;
  }
  return '';
}
