export function projectUrl(id: string, sessionId?: string | null) {
  return `/projects/${encodeURIComponent(id)}` + (sessionId ? `?session=${encodeURIComponent(sessionId)}` : '');
}

export function readProjectRoute(location: { pathname: string; search: string }) {
  const match = /^\/projects\/([^/]+)$/.exec(location.pathname);
  return { projectId: match?.[1] ?? null, sessionId: match ? new URLSearchParams(location.search).get('session') : null };
}
