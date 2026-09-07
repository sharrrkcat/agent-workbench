import { create } from 'zustand';
import { api, ApiError } from '../api/client';
import type { Persona } from '../types';

type State = {
  personas: Persona[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
};

let requestVersion = 0;
export const usePersonasStore = create<State>((set) => ({
  personas: [], loading: false, error: null,
  reload: async () => {
    const version = ++requestVersion;
    set({ loading: true, error: null });
    try {
      const personas = await api.listPersonas();
      if (version === requestVersion) set({ personas });
    } catch (error) {
      if (version === requestVersion) set({ error: error instanceof ApiError ? `${error.code}: ${error.message}` : String(error) });
      throw error;
    } finally {
      if (version === requestVersion) set({ loading: false });
    }
  },
}));
