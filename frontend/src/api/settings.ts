import type {
  GeneralSettings,
  GeneralSettingsPatch,
  PetSettingsPatch,
  PetSettingsResponse,
} from '../types/settings';
import { request } from './http';

export const settingsApi = {
  getGeneralSettings: () => request<GeneralSettings>('/api/settings/general'),
  updateGeneralSettings: (patch: GeneralSettingsPatch) =>
    request<GeneralSettings>('/api/settings/general', { method: 'PATCH', body: JSON.stringify(patch) }),
  getPetSettings: () => request<PetSettingsResponse>('/api/pets/settings'),
  updatePetSettings: (values: PetSettingsPatch) =>
    request<PetSettingsResponse>('/api/pets/settings', { method: 'PATCH', body: JSON.stringify({ values }) }),
  getHealthDetails: () => request<Record<string, unknown>>('/api/health/details'),
};
