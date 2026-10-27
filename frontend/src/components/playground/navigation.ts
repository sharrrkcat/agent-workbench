export type PlaygroundRoute = 'index' | 'farkle';

export function playgroundUrl(app?: 'farkle') {
  return app ? `/playground/${app}` : '/playground';
}

export const farkleHistoryUrl = (page = 1) => `/playground/farkle?view=history&page=${page}`;
export const isFarkleHistory = (search: string) => new URLSearchParams(search).get('view') === 'history';

export function readPlaygroundRoute(location: { pathname: string }): PlaygroundRoute | null {
  if (location.pathname === '/playground') return 'index';
  if (location.pathname === '/playground/farkle') return 'farkle';
  return null;
}
