export type ImagePreview = {
  url: string;
  alt?: string | null;
  title?: string | null;
  caption?: string | null;
};

export function safeImageUrl(value: string | null | undefined): string {
  const trimmed = value?.trim() ?? '';
  if (!trimmed) return '';
  if (/^https?:\/\//i.test(trimmed) || trimmed.startsWith('/')) return trimmed;
  if (/^data:image\/(?:png|jpe?g|webp|gif|svg\+xml);base64,[a-z0-9+/=\s]+$/i.test(trimmed)) return trimmed;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(trimmed) && !trimmed.startsWith('//') && /^[^\s<>"']+$/i.test(trimmed)) return trimmed;
  return '';
}
