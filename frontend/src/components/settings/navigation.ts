export const settingsSections = ['general', 'models', 'personas', 'knowledge', 'worldbook', 'tools', 'pet'] as const;
export type SettingsSection = (typeof settingsSections)[number];

export function readSettingsSection(search: string): SettingsSection {
  const value = new URLSearchParams(search).get('tab');
  return settingsSections.find((section) => section === value) || 'general';
}

export function settingsSectionUrl(section: SettingsSection): string {
  return `/settings?tab=${section}`;
}
