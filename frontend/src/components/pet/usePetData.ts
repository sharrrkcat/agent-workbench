import { useEffect, useState } from 'react';
import { settingsApi } from '../../api/settings';
import type { PetItem, PetSettings } from '../../types/settings';

export function usePetData() {
  const [data, setData] = useState<{ settings: PetSettings | null; pets: PetItem[] }>({ settings: null, pets: [] });
  useEffect(() => {
    let version = 0;
    let disposed = false;
    async function refresh() {
      const request = ++version;
      try {
        const [response, catalog] = await Promise.all([settingsApi.getPetSettings(), settingsApi.listPets()]);
        if (!disposed && version === request) setData({ settings: response.settings, pets: catalog.pets });
      } catch {
        /* A failed refresh leaves the optional overlay at its last known state. */
      }
    }
    void refresh();
    const listener = () => void refresh();
    window.addEventListener('pet-settings-changed', listener);
    return () => {
      disposed = true;
      window.removeEventListener('pet-settings-changed', listener);
    };
  }, []);
  return data;
}
