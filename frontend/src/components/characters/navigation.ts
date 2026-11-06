import { COGITA_CHARACTER_ID } from '../../types/chat';

export function characterUrl(id: string, sessionId?: string | null) {
  return `/characters/${encodeURIComponent(id)}` + (sessionId ? `?session=${encodeURIComponent(sessionId)}` : '');
}
export function newChatUrl(characterId: string | null = COGITA_CHARACTER_ID) {
  return `/characters/${encodeURIComponent(characterId ?? COGITA_CHARACTER_ID)}/new`;
}
export function characterSettingsUrl(id: string) {
  return `/characters/${encodeURIComponent(id)}/settings`;
}
export function isDraftRoute(location: { pathname: string }) {
  return /^\/characters\/[^/]+\/new$/.test(location.pathname);
}
export function isCharacterSettingsRoute(location: { pathname: string }) {
  return /^\/characters\/[^/]+\/settings$/.test(location.pathname);
}
export function isResourcesRoute(location: { pathname: string }) {
  return /^\/characters\/[^/]+\/resources$/.test(location.pathname);
}
export function characterResourcesUrl(id: string) {
  return `/characters/${encodeURIComponent(id)}/resources`;
}
export function readCharacterRoute(location: { pathname: string; search: string }) {
  const match = /^\/characters\/([^/]+)(?:\/(?:new|settings|resources))?$/.exec(location.pathname);
  const characterId = match ? decodeURIComponent(match[1]) : location.pathname === '/' ? COGITA_CHARACTER_ID : null;
  return { characterId, sessionId: match && !isDraftRoute(location) && !isResourcesRoute(location) && !isCharacterSettingsRoute(location)
    ? new URLSearchParams(location.search).get('session') : null };
}
