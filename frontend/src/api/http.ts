import { API_BASE_URL, joinApiUrl } from './url';

export class ApiError extends Error {
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.details = details;
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has('Content-Type') && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json');
  const response = await fetch(joinApiUrl(API_BASE_URL, path), { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw toApiError(response.status, payload);
  return payload as T;
}

export async function requestForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(joinApiUrl(API_BASE_URL, path), { method: 'POST', body });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw toApiError(response.status, payload);
  return payload as T;
}

function toApiError(status: number, payload: unknown): ApiError {
  const error = (payload as { error?: { code?: unknown; message?: unknown; details?: unknown } } | null)?.error;
  const code = typeof error?.code === 'string' ? error.code : 'HTTP_ERROR';
  const message = typeof error?.message === 'string' ? error.message : `Request failed: ${status}`;
  const details = error?.details && typeof error.details === 'object' ? (error.details as Record<string, unknown>) : {};
  return new ApiError(code, message, details);
}
