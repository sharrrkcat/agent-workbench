export function projectUrl(id: string, sessionId?: string | null) {
  return `/projects/${encodeURIComponent(id)}` + (sessionId ? `?session=${encodeURIComponent(sessionId)}` : '');
}

export function newChatUrl(projectId: string | null = null) {
  return projectId ? `/projects/${encodeURIComponent(projectId)}/new` : '/new';
}

export function isDraftRoute(location: { pathname: string }) {
  return location.pathname === '/new' || /^\/projects\/[^/]+\/new$/.test(location.pathname);
}

export function readProjectRoute(location: { pathname: string; search: string }) {
  const match = /^\/projects\/([^/]+)(?:\/new)?$/.exec(location.pathname);
  return { projectId: match ? decodeURIComponent(match[1]) : null,
    sessionId: match && !isDraftRoute(location) ? new URLSearchParams(location.search).get('session') : null };
}
