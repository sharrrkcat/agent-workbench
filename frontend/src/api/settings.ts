import type {
  GeneralSettings,
  GeneralSettingsPatch,
  PetListResponse,
  PetSettings,
  PetSettingsPatch,
  PetSettingsResponse,
} from '../types/settings';
import { request, requestForm } from './http';

export const settingsApi = {
  getGeneralSettings: () => request<GeneralSettings>('/api/settings/general'),
  updateGeneralSettings: (patch: GeneralSettingsPatch) =>
    request<GeneralSettings>('/api/settings/general', { method: 'PATCH', body: JSON.stringify(patch) }),
  getPetSettings: () => request<PetSettingsResponse>('/api/pets/settings'),
  updatePetSettings: (values: PetSettingsPatch) =>
    request<PetSettingsResponse>('/api/pets/settings', { method: 'PATCH', body: JSON.stringify({ values }) }),
  listPets: () => request<PetListResponse>('/api/pets'),
  scanPets: () => request<PetListResponse>('/api/pets/scan', { method: 'POST' }),
  importPet: (manifest: File, spritesheet: File) => {
    const form = new FormData();
    form.append('pet_json', manifest, 'pet.json');
    form.append('spritesheet', spritesheet, 'spritesheet.webp');
    return requestForm<{ pets: PetListResponse['pets']; settings: PetSettings }>('/api/pets/import', form);
  },
  deletePet: (id: string) =>
    request<{ deleted: boolean; pet_id: string; pets: PetListResponse['pets'] }>(
      `/api/pets/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    ),
  getHealthDetails: () => request<Record<string, unknown>>('/api/health/details'),
};
