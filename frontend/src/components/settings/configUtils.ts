import type { AgentConfig, CapabilityConfig, ConfigFieldSchema } from '../../types';

export type EditableConfig = AgentConfig | CapabilityConfig;
export type ConfigValues = Record<string, unknown>;

export function initialConfigValues(config: EditableConfig): ConfigValues {
  const source = config.user_config || {};
  return Object.fromEntries((config.config_schema || []).map((field) => [field.name, source[field.name] ?? '']));
}

export function buildUserConfig(fields: ConfigFieldSchema[], values: ConfigValues): Record<string, unknown> {
  const userConfig: Record<string, unknown> = {};
  for (const field of fields) {
    const value = values[field.name];
    if (value === '' || value === undefined) {
      continue;
    }
    if (field.type === 'integer') {
      const parsed = Number(value);
      if (!Number.isInteger(parsed)) throw new Error(`${field.label || field.name} must be an integer.`);
      userConfig[field.name] = parsed;
    } else if (field.type === 'float') {
      const parsed = Number(value);
      if (Number.isNaN(parsed)) throw new Error(`${field.label || field.name} must be a number.`);
      userConfig[field.name] = parsed;
    } else if (field.type === 'json') {
      if (typeof value === 'string') {
        userConfig[field.name] = JSON.parse(value);
      } else {
        userConfig[field.name] = value;
      }
    } else {
      userConfig[field.name] = value;
    }
  }
  return userConfig;
}

export function isConfigDirty(config: EditableConfig, enabled: boolean, values: ConfigValues): boolean {
  if (enabled !== config.enabled) return true;
  try {
    return stableConfigString(buildUserConfig(config.config_schema || [], values)) !== stableConfigString(config.user_config || {});
  } catch {
    return true;
  }
}

export function stableConfigString(value: Record<string, unknown>): string {
  return JSON.stringify(sortObject(value));
}

export function sortObject(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortObject);
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, sortObject(item)]),
    );
  }
  return value;
}

export function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return 'Unset';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function initials(value: string): string {
  const words = value
    .replace(/[/_-]/g, ' ')
    .split(/\s+/)
    .filter(Boolean);
  return words
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join('');
}
