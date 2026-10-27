import calibration from './calibration.json';
import { DICE_TYPES, SPECIAL_TYPES, difficultyFor, type DieType, type SpecialType } from './dice';

export const OPPONENT_DICE_MODES = ['dynamic', 'random', 'wild'] as const;
export type OpponentDiceMode = typeof OPPONENT_DICE_MODES[number];

type Branch = readonly [pool: 0 | 1] | readonly [pool: 2 | 3 | 4 | 5, lower: number, upper: number];
const rules: { maximum: number; branches: Branch[] }[] = [
  { maximum: 0.2, branches: [[0], [1]] },
  { maximum: 0.4, branches: [[1], [2, 40, 60]] },
  { maximum: 0.6, branches: [[2, 50, 80], [3, 50, 70]] },
  { maximum: 0.8, branches: [[3, 50, 80], [4, 50, 80]] },
  { maximum: 1, branches: [[3, 50, 90], [4, 50, 80], [5, 50, 80]] },
];

// The checked-in artifact is verified when captured and by tests, not on each match.
// Each pool is a flat sequence of [base-20 combination code, wins out of 2,000].
const types = calibration.types as SpecialType[];
const tiers = rules.map(({ maximum, branches }) => ({ maximum, branches: branches.map((branch) => {
  const codes: number[] = [];
  if (branch.length === 3) {
    const [pool, lower, upper] = branch, rows = calibration.pools[pool - 1];
    for (let index = 0; index < rows.length; index += 2) {
      if (rows[index + 1] > lower * 20 && rows[index + 1] <= upper * 20) codes.push(rows[index]);
    }
  }
  return { pool: branch[0], codes };
}) }));

export function decodeCombination(pool: number, code: number): DieType[] {
  const dice: DieType[] = Array(6).fill('normal');
  for (let index = 5; index >= 6 - pool; index--) {
    dice[index] = types[code % 20];
    code = Math.floor(code / 20);
  }
  return dice;
}

export function drawOpponentDice(target: number, mode: OpponentDiceMode, random = Math.random): DieType[] {
  if (mode === 'wild') return Array.from({ length: 6 }, () => DICE_TYPES[Math.floor(random() * DICE_TYPES.length)].id);

  const tier = tiers.find(({ maximum }) => difficultyFor(target) <= maximum)!;
  const { pool, codes } = tier.branches[Math.floor(random() * tier.branches.length)];
  if (mode === 'dynamic' && pool >= 2) return decodeCombination(pool, codes[Math.floor(random() * codes.length)]);

  // Random mode retains the original sequential uniform-type draw and random-call order.
  // Dynamic pools zero and one use this same unfiltered selection.
  const remaining = SPECIAL_TYPES.map(({ id }) => ({ id, copies: id === 'weighted' ? 1 : 3 }));
  const dice: DieType[] = Array(6 - pool).fill('normal');
  for (let copy = 0; copy < pool; copy++) {
    const candidates = remaining.filter(({ copies }) => copies > 0);
    const selected = candidates[Math.floor(random() * candidates.length)];
    selected.copies--;
    dice.push(selected.id);
  }
  return dice;
}
