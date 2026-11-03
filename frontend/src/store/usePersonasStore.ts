import { create } from 'zustand';
import { chatApi } from '../api/chat';
import { ApiError } from '../api/http';
import type { Persona } from '../types/chat';

type State = {
  personas: Persona[];
  loading: boolean;
  loaded: boolean;
  error: string | null;
  reload: (force?: boolean) => Promise<void>;
  upsert: (persona: Persona) => void;
  remove: (id: string) => void;
};

let pending: Promise<void> | null = null;
let again = false;
// Changes received while a list request is pending must win over that response.
const pendingChanges = new Map<string, Persona | null>();
export const usePersonasStore = create<State>((set, get) => ({
  personas: [], loading: false, loaded: false, error: null,
  upsert: (persona) => {
    if (get().loading) pendingChanges.set(persona.id, persona);
    set((state) => ({ personas: [...state.personas.filter((item) => item.id !== persona.id), persona] }));
  },
  remove: (id) => {
    if (get().loading) pendingChanges.set(id, null);
    set((state) => ({ personas: state.personas.filter((item) => item.id !== id) }));
  },
  reload: (force = false) => {
    if (pending) { again ||= force; return pending; }
    pendingChanges.clear();
    set({ loading: true, error: null });
    pending = (async () => {
      try {
        do {
          again = false;
          const personas = await chatApi.listPersonas();
          if (again) continue;
          const current = new Map(personas.map((persona) => [persona.id, persona]));
          for (const [id, persona] of pendingChanges) {
            if (persona) current.set(id, persona);
            else current.delete(id);
          }
          set({ personas: [...current.values()], loaded: true });
        } while (again);
      } catch (error) {
        set({ error: error instanceof ApiError ? `${error.code}: ${error.message}` : String(error) });
        throw error;
      } finally {
        pending = null; pendingChanges.clear(); set({ loading: false });
      }
    })();
    return pending;
  },
}));
