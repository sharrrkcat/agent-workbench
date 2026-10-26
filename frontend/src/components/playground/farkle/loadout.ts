import { DICE_TYPES, type DiceCounts, type DieType } from './dice';

export const LOADOUT_KEY = 'cogita.farkle.loadout';
export const defaultLoadout = (): DiceCounts =>
  Object.fromEntries(DICE_TYPES.map(({ id }) => [id, id === 'normal' ? 6 : 0])) as DiceCounts;
export const loadoutSize = (counts: DiceCounts) => DICE_TYPES.reduce((total, { id }) => total + counts[id], 0);
export const loadoutDice = (counts: DiceCounts): DieType[] => DICE_TYPES.flatMap(({ id }) => Array<DieType>(counts[id]).fill(id));

export function readLoadout(storage: Pick<Storage, 'getItem'>, owned: DiceCounts): DiceCounts {
  const raw = storage.getItem(LOADOUT_KEY);
  if (raw === null) return defaultLoadout();
  let value: DiceCounts;
  try { value = JSON.parse(raw); }
  catch (error) { if (error instanceof SyntaxError) return defaultLoadout(); throw error; }
  if (!value || typeof value !== 'object'
    || !DICE_TYPES.every(({ id }) => Number.isInteger(value[id]) && value[id] >= 0 && value[id] <= owned[id])
    || loadoutSize(value) !== 6) return defaultLoadout();
  return Object.fromEntries(DICE_TYPES.map(({ id }) => [id, value[id]])) as DiceCounts;
}

export function saveLoadout(storage: Pick<Storage, 'setItem'>, counts: DiceCounts) {
  storage.setItem(LOADOUT_KEY, JSON.stringify(counts));
}
