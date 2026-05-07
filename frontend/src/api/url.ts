export const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api';
export const API_BASE_URL = trimTrailingSlash(rawApiBaseUrl);

export function joinApiUrl(base: string, path: string): string {
  const normalizedBase = trimTrailingSlash(base.trim() || '/api');
  const normalizedPath = normalizeEndpointPath(path);
  return `${normalizedBase}${normalizedPath}`;
}

export function normalizeEndpointPath(path: string): string {
  const trimmed = path.trim();
  const withoutLeadingSlash = trimmed.replace(/^\/+/, '');
  const withoutApiPrefix = withoutLeadingSlash.replace(/^api(?:\/|$)/, '');
  return `/${withoutApiPrefix}`;
}

export function createWebSocketUrlFromBase(base: string, sessionId: string, origin: string): string {
  const httpUrl = new URL(joinApiUrl(base, `/ws/${encodeURIComponent(sessionId)}`), origin);
  httpUrl.protocol = httpUrl.protocol === 'https:' ? 'wss:' : 'ws:';
  return httpUrl.toString();
}

export function resolveAttachmentUrlFromBase(base: string, value: string | null | undefined): string {
  const trimmed = value?.trim() || '';
  if (!trimmed) return '';
  const localAttachment = trimmed.match(/^local:\/\/attachments\/(.+)$/i);
  if (localAttachment) {
    return joinApiUrl(base, `/attachments/${encodeURIComponent(localAttachment[1])}`);
  }
  if (/^\/api\/attachments\/.+/i.test(trimmed) || /^\/attachments\/.+/i.test(trimmed)) {
    return joinApiUrl(base, trimmed);
  }
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^data:image\/(?:png|jpe?g|webp|gif|svg\+xml);base64,[a-z0-9+/=\s]+$/i.test(trimmed)) return trimmed;
  return '';
}

export function resolveAvatarUrlFromBase(base: string, value: string | null | undefined): string {
  const trimmed = value?.trim() || '';
  if (!trimmed) return '';
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^data:image\/(?:png|jpe?g|webp|gif|svg\+xml);base64,[a-z0-9+/=\s]+$/i.test(trimmed)) return trimmed;
  if (/^\/api\/agents\/.+/i.test(trimmed) || /^\/agents\/.+/i.test(trimmed)) return joinApiUrl(base, trimmed);
  return '';
}

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '') || '/';
}
