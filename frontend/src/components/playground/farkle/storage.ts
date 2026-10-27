import { CUSTOM_GAME_KEY } from './customGame';
import { INVENTORY_KEY } from './economy';
import { LOADOUT_KEY } from './loadout';
import { FARKLE_SETTINGS_KEY } from './settings';

export function clearFarkleStorage(storage: Pick<Storage, 'removeItem'>) {
  for (const key of [INVENTORY_KEY, LOADOUT_KEY, FARKLE_SETTINGS_KEY, CUSTOM_GAME_KEY]) storage.removeItem(key);
}
