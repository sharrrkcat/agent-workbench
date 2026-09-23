export const settingsSections = ['general', 'models', 'personas', 'knowledge', 'worldbook', 'tools'] as const;
export type SettingsSection = (typeof settingsSections)[number];

export const modelViews = ['profiles', 'providers', 'localRuntime', 'service'] as const;
export const resourceViews = ['list', 'settings'] as const;
export type ModelView = (typeof modelViews)[number];
export type ResourceView = (typeof resourceViews)[number];
export type SettingsRoute =
  | { section: 'models'; view: ModelView }
  | { section: 'knowledge' | 'worldbook'; view: ResourceView }
  | { section: 'general' | 'personas' | 'tools'; view?: never };
export type NavigationTarget = { pathname: string; search: string };
export type SettingsNavigate = (url: string) => Promise<boolean>;

export const settingsGroups: {
  id: 'application' | 'execution' | 'context';
  menus: { section: SettingsSection; pages: SettingsRoute[] }[];
}[] = [
  { id: 'application', menus: [{ section: 'general', pages: [{ section: 'general' }] }] },
  {
    id: 'execution',
    menus: [
      { section: 'models', pages: modelViews.map((view) => ({ section: 'models', view })) },
      { section: 'tools', pages: [{ section: 'tools' }] },
    ],
  },
  {
    id: 'context',
    menus: [
      { section: 'personas', pages: [{ section: 'personas' }] },
      { section: 'knowledge', pages: resourceViews.map((view) => ({ section: 'knowledge', view })) },
      { section: 'worldbook', pages: resourceViews.map((view) => ({ section: 'worldbook', view })) },
    ],
  },
];

export function readSettingsRoute(search: string): SettingsRoute {
  const params = new URLSearchParams(search);
  const value = params.get('tab');
  const section = settingsSections.find((item) => item === value) || 'general';
  const view = params.get('view');
  if (section === 'models') return { section, view: modelViews.find((item) => item === view) || 'profiles' };
  if (section === 'knowledge' || section === 'worldbook')
    return { section, view: resourceViews.find((item) => item === view) || 'list' };
  return { section };
}

export function settingsRouteUrl(route: SettingsRoute): string {
  return `/settings?tab=${route.section}${route.view ? `&view=${route.view}` : ''}`;
}

export function settingsPageLabel(route: SettingsRoute): string {
  if (route.section === 'models') return `llm:${route.view}`;
  if (route.section === 'knowledge' || route.section === 'worldbook')
    return `settings:resources.${route.view}`;
  return `settings:${route.section}`;
}
