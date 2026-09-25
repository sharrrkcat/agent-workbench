export const settingsSections = ['general', 'models', 'personas', 'knowledge', 'worldbook', 'tools'] as const;
export type SettingsSection = (typeof settingsSections)[number];

export const modelViews = ['profiles', 'providers', 'localRuntime', 'service'] as const;
export const resourceViews = ['list', 'settings'] as const;
export const personaViews = ['user', 'agent', 'roleplay_user', 'character'] as const;
export type ModelView = (typeof modelViews)[number];
export type ResourceView = (typeof resourceViews)[number];
export type PersonaView = (typeof personaViews)[number];
export type SettingsRoute =
  | { section: 'models'; view: ModelView }
  | { section: 'knowledge' | 'worldbook'; view: ResourceView }
  | { section: 'personas'; view: PersonaView }
  | { section: 'general' | 'tools'; view?: never };
export type NavigationTarget = { pathname: string; search: string };
export type SettingsNavigate = (url: string) => Promise<boolean>;

export const settingsGroups: {
  id: 'application' | 'execution' | 'daily' | 'roleplay';
  menus: { id: string; section: SettingsSection; pages: SettingsRoute[] }[];
}[] = [
  { id: 'application', menus: [{ id: 'general', section: 'general', pages: [{ section: 'general' }] }] },
  {
    id: 'execution',
    menus: [
      { id: 'models', section: 'models', pages: modelViews.map((view) => ({ section: 'models', view })) },
      { id: 'tools', section: 'tools', pages: [{ section: 'tools' }] },
    ],
  },
  {
    id: 'daily',
    menus: [
      { id: 'daily-personas', section: 'personas', pages: [{ section: 'personas', view: 'user' }, { section: 'personas', view: 'agent' }] },
      { id: 'knowledge', section: 'knowledge', pages: resourceViews.map((view) => ({ section: 'knowledge', view })) },
    ],
  },
  {
    id: 'roleplay',
    menus: [
      { id: 'roleplay-personas', section: 'personas', pages: [{ section: 'personas', view: 'roleplay_user' }, { section: 'personas', view: 'character' }] },
      { id: 'worldbook', section: 'worldbook', pages: resourceViews.map((view) => ({ section: 'worldbook', view })) },
    ],
  },
];

export function readSettingsRoute(search: string): SettingsRoute {
  const params = new URLSearchParams(search);
  const value = params.get('tab');
  const section = settingsSections.find((item) => item === value) || 'general';
  const view = params.get('view');
  if (section === 'models') return { section, view: modelViews.find((item) => item === view) || 'profiles' };
  if (section === 'personas') return { section, view: personaViews.find((item) => item === view) || 'user' };
  if (section === 'knowledge' || section === 'worldbook')
    return { section, view: resourceViews.find((item) => item === view) || 'list' };
  return { section };
}

export function settingsRouteUrl(route: SettingsRoute): string {
  return `/settings?tab=${route.section}${route.view ? `&view=${route.view}` : ''}`;
}

export function settingsPageLabel(route: SettingsRoute): string {
  if (route.section === 'models') return `llm:${route.view}`;
  if (route.section === 'personas') return `personas:collections.${route.view}`;
  if (route.section === 'knowledge' || route.section === 'worldbook')
    return `settings:resources.${route.view}`;
  return `settings:${route.section}`;
}
