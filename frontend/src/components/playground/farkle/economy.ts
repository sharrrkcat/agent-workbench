import { NORMAL_COUNT, SPECIAL_LIMIT, SPECIAL_TYPES, type DiceCounts, type SpecialType } from './dice';
import { encodeDie, decodeDie, isDiceCode } from './diceEncoding';

export const LEVELS = [
  { id: 'beggars', target: 1500, special: 2, merchant: 1, firstWin: 1 },
  { id: 'wagoners', target: 2000, special: 2, merchant: 1, firstWin: 1 },
  { id: 'masters', target: 3000, special: 3, merchant: 2, firstWin: 2 },
  { id: 'courtiers', target: 4000, special: 3, merchant: 2, firstWin: 2 },
  { id: 'burgomasters', target: 5000, special: 3, merchant: 3, firstWin: 3 },
  { id: 'stewards', target: 6000, special: 3, merchant: 3, firstWin: 3 },
  { id: 'governors', target: 7000, special: 4, merchant: 3, firstWin: 3 },
  { id: 'chancellors', target: 8000, special: 4, merchant: 3, firstWin: 3 },
  { id: 'burgraves', target: 9000, special: 4, merchant: 4, firstWin: 4 },
  { id: 'electors', target: 10000, special: 4, merchant: 4, firstWin: 4 },
] as const;
export type LevelId = typeof LEVELS[number]['id'];
export type Inventory = {
  special: Record<SpecialType, number>;
  merchant: number;
  firstWins: LevelId[];
};
export type Reward = {
  special: Record<SpecialType, number>;
  merchant: number;
  firstWin: number;
  converted: number;
};
export const INVENTORY_KEY = 'cogita.farkle.inventory';
export const emptySpecial = (): Record<SpecialType, number> =>
  Object.fromEntries(SPECIAL_TYPES.map(({ id }) => [id, 0])) as Record<SpecialType, number>;
export const newInventory = (): Inventory => ({ special: emptySpecial(), merchant: 0, firstWins: [] });

export const DICE_BUY_PRICE = 2;
export const DICE_SELL_PRICE = 1;
export type DiceTrade = 'buy' | 'sell';
export const canTradeDice = (inventory: Inventory, type: SpecialType, action: DiceTrade) => action === 'buy'
  ? inventory.special[type] < SPECIAL_LIMIT && inventory.merchant >= DICE_BUY_PRICE
  : inventory.special[type] > 0 && inventory.merchant <= Number.MAX_SAFE_INTEGER - DICE_SELL_PRICE;

export function tradeDice(inventory: Inventory, type: SpecialType, action: DiceTrade): Inventory {
  return { ...inventory,
    special: { ...inventory.special, [type]: inventory.special[type] + (action === 'buy' ? 1 : -1) },
    merchant: inventory.merchant + (action === 'buy' ? -DICE_BUY_PRICE : DICE_SELL_PRICE) };
}

export const INVENTORY_ACTIONS = ['fillDice', 'clearDice', 'addMerchantDice', 'clearMerchantDice'] as const;
export type InventoryAction = typeof INVENTORY_ACTIONS[number];
export const canModifyInventory = (inventory: Inventory, action: InventoryAction) =>
  action !== 'addMerchantDice' || inventory.merchant <= Number.MAX_SAFE_INTEGER - 999;

export function modifyInventory(inventory: Inventory, action: InventoryAction): Inventory {
  switch (action) {
    case 'fillDice': return { ...inventory, merchant: 999,
      special: Object.fromEntries(SPECIAL_TYPES.map(({ id }) => [id, SPECIAL_LIMIT])) as Inventory['special'] };
    case 'clearDice': return { ...inventory, special: emptySpecial(), merchant: 0 };
    case 'addMerchantDice': return { ...inventory, merchant: inventory.merchant + 999 };
    case 'clearMerchantDice': return { ...inventory, merchant: 0 };
  }
}

export function inventoryPool(inventory: Inventory): DiceCounts {
  return { ...inventory.special, normal: NORMAL_COUNT, merchant: inventory.merchant };
}

/** This is the only parsing boundary; normal dice are never read from storage. */
export function readInventory(storage: Pick<Storage, 'getItem'>): Inventory {
  const raw = storage.getItem(INVENTORY_KEY);
  if (raw === null) return newInventory();
  const value = JSON.parse(raw);
  if (!value || typeof value !== 'object' || !value.dice || typeof value.dice !== 'object' || Array.isArray(value.dice)
    || !Object.entries(value.dice).every(([code, count]) => {
      if (!isDiceCode(code)) return false;
      const type = decodeDie(code);
      return type === 'normal' || (typeof count === 'number' && Number.isSafeInteger(count) && count >= 0
        && (type === 'merchant' || count <= SPECIAL_LIMIT));
    })
    || !Array.isArray(value.firstWins) || !value.firstWins.every((id: unknown) => LEVELS.some((level) => level.id === id))) {
    throw new Error('Invalid Farkle inventory');
  }
  const inventory = { ...newInventory(), firstWins: [...new Set<LevelId>(value.firstWins)] };
  for (const [code, count] of Object.entries(value.dice)) {
    const type = decodeDie(code);
    if (type === 'merchant') inventory.merchant = count as number;
    else if (type !== 'normal') inventory.special[type] = count as number;
  }
  return inventory;
}

export function saveInventory(storage: Pick<Storage, 'setItem'>, inventory: Inventory) {
  const counts = { ...inventory.special, merchant: inventory.merchant };
  storage.setItem(INVENTORY_KEY, JSON.stringify({
    dice: Object.fromEntries(Object.entries(counts).filter(([, count]) => count > 0)
      .map(([type, count]) => [encodeDie(type as SpecialType | 'merchant'), count])),
    firstWins: inventory.firstWins,
  }));
}

export function awardDice(inventory: Inventory, levelId: LevelId, won: boolean, random = Math.random) {
  const level = LEVELS.find((item) => item.id === levelId)!;
  const next: Inventory = { special: { ...inventory.special }, merchant: inventory.merchant, firstWins: [...inventory.firstWins] };
  const firstWin = won && !next.firstWins.includes(level.id) ? level.firstWin : 0;
  const reward: Reward = { special: emptySpecial(), merchant: won ? level.merchant : 0, firstWin, converted: 0 };
  let remaining = won ? level.special : 1;
  while (remaining) {
    const candidates = SPECIAL_TYPES.filter(({ id }) => next.special[id] < SPECIAL_LIMIT);
    if (!candidates.length) break;
    const { id } = candidates[Math.floor(random() * candidates.length)];
    next.special[id]++;
    reward.special[id]++;
    remaining--;
  }
  reward.converted = Math.ceil(remaining / 2);
  reward.merchant += firstWin + reward.converted;
  next.merchant += reward.merchant;
  if (firstWin) next.firstWins.push(level.id);
  return { inventory: next, reward };
}
