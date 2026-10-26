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
  const remaining = [3, 3, 3, 1];
  // A mild quality bias preserves variety; actual rolls retain their published weights.
  const quality = [1, 1 + difficulty, 1 + 2 * difficulty, 1 + 3 * difficulty];
  const dice: DieType[] = Array(6 - count).fill('normal');
  for (let copy = 0; copy < count; copy++) {
    const index = weightedIndex(remaining.map((copies, index) => copies * quality[index]), random());
    remaining[index]--;
    dice.push(SPECIAL_TYPES[index].id);
  }
  return dice;
}

export function rollValues(types: readonly DieType[], random = Math.random): FaceValue[] {
  return types.map((type) => (weightedIndex(DICE_TYPES.find(({ id }) => id === type)!.weights, random()) + 1) as FaceValue);
}
