import { modelKinds } from '../../types/models';

export const settingsSections = ['general', 'models', 'personas', 'knowledge', 'worldbook', 'tools'] as const;
export type SettingsSection = (typeof settingsSections)[number];

export const modelViews = ['dashboard', ...modelKinds, 'providers', 'localRuntime'] as const;
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
  menus: { id: string; section: SettingsSection; label: string; pages: SettingsRoute[] }[];
}[] = [
  { id: 'application', menus: [{ id: 'general', section: 'general', label: 'general', pages: [{ section: 'general' }] }] },
  {
    id: 'execution',
    menus: [
      { id: 'models', section: 'models', label: 'models', pages: [
        { section: 'models', view: 'dashboard' },
        ...modelKinds.map((view) => ({ section: 'models' as const, view })),
      ] },
      { id: 'providersRuntime', section: 'models', label: 'providersRuntime', pages: [
        { section: 'models', view: 'providers' }, { section: 'models', view: 'localRuntime' },
      ] },
      { id: 'tools', section: 'tools', label: 'tools', pages: [{ section: 'tools' }] },
    ],
  },
  {
    id: 'daily',
    menus: [
      { id: 'daily-personas', section: 'personas', label: 'personas', pages: [{ section: 'personas', view: 'user' }, { section: 'personas', view: 'agent' }] },
      { id: 'knowledge', section: 'knowledge', label: 'knowledge', pages: resourceViews.map((view) => ({ section: 'knowledge', view })) },
    ],
  },
  {
    id: 'roleplay',
    menus: [
      { id: 'roleplay-personas', section: 'personas', label: 'personas', pages: [{ section: 'personas', view: 'roleplay_user' }, { section: 'personas', view: 'character' }] },
      { id: 'worldbook', section: 'worldbook', label: 'worldbook', pages: resourceViews.map((view) => ({ section: 'worldbook', view })) },
    ],
  },
];

export function readSettingsRoute(search: string): SettingsRoute {
  const params = new URLSearchParams(search);
  const value = params.get('tab');
  const section = settingsSections.find((item) => item === value) || 'general';
  const view = params.get('view');
  if (section === 'models') return { section, view: modelViews.find((item) => item === view) || 'dashboard' };
  if (section === 'personas') return { section, view: personaViews.find((item) => item === view) || 'user' };
  if (section === 'knowledge' || section === 'worldbook')
    return { section, view: resourceViews.find((item) => item === view) || 'list' };
  return { section };
}

export function settingsRouteUrl(route: SettingsRoute): string {
  return `/settings?tab=${route.section}${route.view ? `&view=${route.view}` : ''}`;
}

export function settingsPageLabel(route: SettingsRoute): string {
  if (route.section === 'models') return route.view === 'dashboard' || route.view === 'providers' || route.view === 'localRuntime'
    ? `llm:${route.view}` : `llm:kinds.${route.view}`;
  if (route.section === 'personas') return `personas:collections.${route.view}`;
  if (route.section === 'knowledge' || route.section === 'worldbook')
    return `settings:resources.${route.view}`;
  return `settings:${route.section}`;
}

export function settingsMenuLabel(route: SettingsRoute): string {
  return route.section === 'models' && (route.view === 'providers' || route.view === 'localRuntime')
    ? 'providersRuntime' : route.section;
}
