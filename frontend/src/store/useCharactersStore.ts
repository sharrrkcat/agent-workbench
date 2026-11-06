import { create } from 'zustand';
import { charactersApi } from '../api/characters';
import type { Character, CharacterInput, CharacterPatch } from '../types/characters';
import type { MemoryDeletionChoice } from '../types/memory';

type CharactersState = {
  characters: Character[];
  version: number;
  upsert: (character: Character) => void;
  reload: () => Promise<void>;
  load: (id: string) => Promise<Character>;
  save: (values: CharacterInput, id?: string) => Promise<Character>;
  patch: (id: string, values: CharacterPatch) => Promise<Character>;
  remove: (id: string, memory?: MemoryDeletionChoice) => Promise<void>;
};

const upsert = (characters: Character[], character: Character) =>
  [character, ...characters.filter((item) => item.id !== character.id)].sort((a, b) => b.updated_at.localeCompare(a.updated_at));

export const useCharactersStore = create<CharactersState>((set, get) => ({
  characters: [],
  version: 0,
  upsert: (character) => set((state) => {
    const existing = state.characters.find((item) => item.id === character.id);
    if (existing && existing.updated_at > character.updated_at) return {};
    return { characters: upsert(state.characters, character), version: state.version + 1 };
  }),
  reload: async () => {
    const version = get().version;
    const characters = await charactersApi.list();
    if (get().version === version) set({ characters });
  },
  load: async (id) => {
    const version = get().version;
    const character = await charactersApi.get(id);
    if (get().version === version) set((state) => ({ characters: upsert(state.characters, character) }));
    return character;
  },
  save: async (values, id) => {
    const { kind: _kind, ...patch } = values;
    if (id) return get().patch(id, patch);
    const character = await charactersApi.create(values);
    set((state) => ({ characters: upsert(state.characters, character), version: state.version + 1 }));
    return character;
  },
  patch: async (id, values) => {
    const version = get().version;
    const character = await charactersApi.update(id, values);
    if (get().version === version || get().characters.some((item) => item.id === id))
      set((state) => ({ characters: upsert(state.characters, character), version: state.version + 1 }));
    return character;
  },
  remove: async (id, memory) => {
    await charactersApi.remove(id, memory);
    set((state) => ({ characters: state.characters.filter((character) => character.id !== id), version: state.version + 1 }));
  },
}));
