export const DICE_TYPES = [
  { id: 'normal', category: 'normal', weights: [1, 1, 1, 1, 1, 1] },
  { id: 'even', category: 'special', weights: [1, 4, 1, 4, 1, 4] },
  { id: 'odd', category: 'special', weights: [4, 1, 4, 1, 4, 1] },
  { id: 'devil', category: 'special', weights: [1, 1, 1, 1, 1, 1] },
  { id: 'weighted', category: 'special', weights: [10, 1, 1, 1, 1, 1] },
  { id: 'merchant', category: 'merchant', weights: [1, 1, 1, 1, 1, 1] },
] as const;
export type DieType = typeof DICE_TYPES[number]['id'];
export type SpecialType = Extract<typeof DICE_TYPES[number], { category: 'special' }>['id'];
export type FaceValue = 1 | 2 | 3 | 4 | 5 | 6;
export type DiceCounts = Record<DieType, number>;
export const SPECIAL_TYPES = DICE_TYPES.filter((die) => die.category === 'special');
export const NORMAL_COUNT = 6;
export const SPECIAL_LIMIT = 6;
export const OPPONENT_POOL: DiceCounts = { normal: 6, even: 6, odd: 6, devil: 6, weighted: 6, merchant: 6 };

function weightedIndex(weights: readonly number[], sample: number) {
  let ticket = sample * weights.reduce((sum, weight) => sum + weight, 0);
  let index = 0;
  while (ticket >= weights[index]) ticket -= weights[index++];
  return index;
}

export function drawDice(pool: DiceCounts, random = Math.random): DieType[] {
  const remaining = DICE_TYPES.map(({ id }) => pool[id]);
  return Array.from({ length: 6 }, () => {
    const index = weightedIndex(remaining, random());
    remaining[index]--;
    return DICE_TYPES[index].id;
  });
}

export function rollValues(types: readonly DieType[], random = Math.random): FaceValue[] {
  return types.map((type) => (weightedIndex(DICE_TYPES.find(({ id }) => id === type)!.weights, random()) + 1) as FaceValue);
}
