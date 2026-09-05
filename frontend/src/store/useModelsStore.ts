import { create } from 'zustand';
import { api } from '../api/client';
import type { ModelProfile, ProviderProfile, ModelSettings, ModelStatus } from '../types';

type ModelsState = {
  profiles: ModelProfile[]; providers: ProviderProfile[]; settings: ModelSettings | null;
  statuses: Record<string, ModelStatus>; loading: boolean; error: string;
  reload: () => Promise<void>;
  setStatus: (id: string, status: ModelStatus) => void;
};

export const useModelsStore = create<ModelsState>((set, get) => {
  let reloadVersion = 0;
  const statusVersions = new Map<string, number>();
  return {
  profiles: [], providers: [], settings: null, statuses: {}, loading: false, error: '',
  reload: async () => {
    const version = ++reloadVersion;
    const initialStatusVersions = new Map(statusVersions);
    set({ loading: true, error: '' });
    try {
      const [profiles, providers, settings] = await Promise.all([api.listModelProfiles(), api.listProviderProfiles(), api.getModelSettings()]);
      const statuses = Object.fromEntries(await Promise.all(profiles.map(async (p) => [p.id, await api.getModelStatus(p.id)])));
      if (version !== reloadVersion) return;
      for (const profile of profiles) {
        if (statusVersions.get(profile.id) !== initialStatusVersions.get(profile.id) && get().statuses[profile.id]) {
          statuses[profile.id] = get().statuses[profile.id];
        }
      }
      set({ profiles, providers, settings, statuses });
    } catch (error) {
      if (version !== reloadVersion) return;
      set({ error: error instanceof Error ? error.message : String(error) });
      throw error;
    } finally { if (version === reloadVersion) set({ loading: false }); }
  },
  setStatus: (id, status) => {
    statusVersions.set(id, (statusVersions.get(id) || 0) + 1);
    set((state) => ({ statuses: { ...state.statuses, [id]: status } }));
  },
  };
});
