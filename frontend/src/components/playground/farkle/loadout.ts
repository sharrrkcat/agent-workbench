import { DICE_TYPES, type DiceCounts, type DieType } from './dice';

export const LOADOUT_KEY = 'cogita.farkle.loadout';
export const FULL_DICE_POOL = Object.fromEntries(DICE_TYPES.map(({ id }) => [id, 6])) as DiceCounts;
export const defaultLoadout = (): DiceCounts =>
  Object.fromEntries(DICE_TYPES.map(({ id }) => [id, id === 'normal' ? 6 : 0])) as DiceCounts;
export const loadoutSize = (counts: DiceCounts) => DICE_TYPES.reduce((total, { id }) => total + counts[id], 0);
export const loadoutDice = (counts: DiceCounts): DieType[] => DICE_TYPES.flatMap(({ id }) => Array<DieType>(counts[id]).fill(id));

export function randomLoadout(available: DiceCounts, random: () => number = Math.random): DiceCounts {
  const pool = loadoutDice({ ...available, merchant: Math.min(6, available.merchant) });
  const counts = { ...defaultLoadout(), normal: 0 };
  for (let index = 0; index < 6; index++) {
    const [type] = pool.splice(Math.floor(random() * pool.length), 1);
    counts[type]++;
  }
  return counts;
}

export function isLoadout(value: unknown, available: DiceCounts): value is DiceCounts {
  if (!value || typeof value !== 'object') return false;
  const counts = value as DiceCounts;
  return DICE_TYPES.every(({ id }) => Number.isInteger(counts[id]) && counts[id] >= 0 && counts[id] <= available[id])
    && loadoutSize(counts) === 6;
}

export function canAdjustLoadout(counts: DiceCounts, available: DiceCounts, type: DieType, change: -1 | 1) {
  if (change === -1) return type !== 'normal' && counts[type] > 0;
  return type === 'normal' ? counts.normal < 6 : counts.normal > 0 && counts[type] < available[type];
}

export function adjustLoadout(counts: DiceCounts, type: DieType, change: -1 | 1, englishOrder: readonly DieType[]): DiceCounts {
  if (type === 'normal') {
    const replaced = englishOrder.find((id) => id !== 'normal' && counts[id] > 0)!;
    return { ...counts, normal: counts.normal + 1, [replaced]: counts[replaced] - 1 };
  }
  return { ...counts, [type]: counts[type] + change, normal: counts.normal - change };
}

export function readLoadout(storage: Pick<Storage, 'getItem'>, owned: DiceCounts): DiceCounts {
  const raw = storage.getItem(LOADOUT_KEY);
  if (raw === null) return defaultLoadout();
  let value: DiceCounts;
  try { value = JSON.parse(raw); }
  catch (error) { if (error instanceof SyntaxError) return defaultLoadout(); throw error; }
  if (!isLoadout(value, FULL_DICE_POOL)) return defaultLoadout();
  const counts = Object.fromEntries(DICE_TYPES.map(({ id }) => [id, Math.min(value[id], owned[id])])) as DiceCounts;
  counts.normal += 6 - loadoutSize(counts);
  return counts;
}

export function saveLoadout(storage: Pick<Storage, 'setItem'>, counts: DiceCounts) {
  storage.setItem(LOADOUT_KEY, JSON.stringify(counts));
}
