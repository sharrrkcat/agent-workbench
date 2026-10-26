export const DICE_TYPES = [
  { id: 'normal', category: 'normal', weights: [1, 1, 1, 1, 1, 1] },
  { id: 'even', category: 'special', weights: [1, 4, 1, 4, 1, 4] },
  { id: 'odd', category: 'special', weights: [4, 1, 4, 1, 4, 1] },
  { id: 'devil', category: 'special', weights: [1, 1, 1, 1, 1, 1] },
  { id: 'weighted', category: 'special', weights: [10, 1, 1, 1, 1, 1] },
  { id: 'lucky', category: 'special', weights: [6, 1, 2, 3, 4, 6] },
  { id: 'unlucky', category: 'special', weights: [1, 3, 2, 2, 2, 1] },
  { id: 'favourable', category: 'special', weights: [6, 0, 1, 1, 6, 4] },
  { id: 'pie', category: 'special', weights: [6, 1, 3, 3, 0, 0] },
  { id: 'misfortune', category: 'special', weights: [1, 5, 5, 5, 5, 1] },
  { id: 'monk', category: 'special', weights: [8, 8, 1, 1, 1, 1] },
  { id: 'strip', category: 'special', weights: [4, 2, 2, 2, 3, 3] },
  { id: 'unbalanced', category: 'special', weights: [3, 4, 1, 1, 2, 1] },
  { id: 'shrinking', category: 'special', weights: [2, 1, 1, 1, 1, 3] },
  { id: 'painted', category: 'special', weights: [3, 1, 1, 1, 7, 3] },
  { id: 'heavenly', category: 'special', weights: [7, 2, 2, 2, 2, 4] },
  { id: 'grimy', category: 'special', weights: [1, 5, 1, 1, 7, 1] },
  { id: 'lu', category: 'special', weights: [3, 3, 3, 3, 3, 8] },
  { id: 'ci', category: 'special', weights: [3, 3, 3, 3, 3, 8] },
  { id: 'fer', category: 'special', weights: [3, 3, 3, 3, 3, 8] },
  { id: 'aranka', category: 'special', weights: [6, 1, 6, 1, 6, 1] },
  { id: 'merchant', category: 'merchant', weights: [1, 1, 1, 1, 1, 1] },
] as const;
export type DieType = typeof DICE_TYPES[number]['id'];
export type SpecialType = Extract<typeof DICE_TYPES[number], { category: 'special' }>['id'];
export type FaceValue = 1 | 2 | 3 | 4 | 5 | 6;
export type DiceCounts = Record<DieType, number>;
export const SPECIAL_TYPES = DICE_TYPES.filter((die) => die.category === 'special');
export const NORMAL_COUNT = 6;
export const SPECIAL_LIMIT = 6;
export const difficultyFor = (target: number) => Math.min(1, Math.max(0, target / 10_000));

function weightedIndex(weights: readonly number[], sample: number) {
  let ticket = sample * weights.reduce((sum, weight) => sum + weight, 0);
  let index = 0;
  while (ticket >= weights[index]) ticket -= weights[index++];
  return index;
}

export function drawOpponentDice(target: number, random = Math.random): DieType[] {
  const difficulty = difficultyFor(target);
  const range = difficulty <= 0.2 ? [0, 1] : difficulty <= 0.4 ? [1, 2]
    : difficulty <= 0.6 ? [2, 3] : difficulty <= 0.8 ? [3, 4] : [3, 5];
  const count = range[0] + Math.floor(random() * (range[1] - range[0] + 1));
  const remaining = SPECIAL_TYPES.map(({ id }) => ({ id, copies: id === 'weighted' ? 1 : 3 }));
  const dice: DieType[] = Array(6 - count).fill('normal');
  for (let copy = 0; copy < count; copy++) {
    const candidates = remaining.filter(({ copies }) => copies > 0);
    const selected = candidates[Math.floor(random() * candidates.length)];
    selected.copies--;
    dice.push(selected.id);
  }
  return dice;
}

export function rollValues(types: readonly DieType[], random = Math.random): FaceValue[] {
  return types.map((type) => (weightedIndex(DICE_TYPES.find(({ id }) => id === type)!.weights, random()) + 1) as FaceValue);
}
