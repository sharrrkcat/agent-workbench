export type PlaygroundRoute = 'index' | 'farkle';

export function playgroundUrl(app?: 'farkle') {
  return app ? `/playground/${app}` : '/playground';
}

export function readPlaygroundRoute(location: { pathname: string }): PlaygroundRoute | null {
  if (location.pathname === '/playground') return 'index';
  if (location.pathname === '/playground/farkle') return 'farkle';
  return null;
}
