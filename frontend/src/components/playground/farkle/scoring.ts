import type { GameDie } from './state';

type ScoringDie = Pick<GameDie, 'value' | 'skin'>;

export function isWild(die: ScoringDie) {
  return die.skin === 'devil' && die.value === 1;
}

function combinationScore(dice: readonly ScoringDie[]): number {
  const natural = dice.filter((die) => !isWild(die)).map((die) => die.value);
  if (dice.length === 1) return natural[0] === 1 ? 100 : natural[0] === 5 ? 50 : 0;
  let score = 0;
  if (dice.length >= 3 && natural.every((value) => value === natural[0])) {
    const face = natural[0] ?? 1;
    score = (face === 1 ? 1000 : face * 100) * 2 ** (dice.length - 3);
  }
  if (new Set(natural).size === natural.length) {
    if (dice.length === 5 && natural.every((value) => value <= 5)) score = Math.max(score, 500);
    if (dice.length === 5 && natural.every((value) => value >= 2)) score = Math.max(score, 750);
    if (dice.length === 6) score = Math.max(score, 1500);
  }
  return score;
}

/** Exact coverage scores selections; any scoring subset keeps a roll alive. */
export function evaluateDice(dice: readonly ScoringDie[]) {
  const size = 1 << dice.length;
  const groups = Array<number>(size).fill(0);
  const best = Array<number>(size).fill(-Infinity);
  best[0] = 0;
  for (let mask = 1; mask < size; mask++) {
    groups[mask] = combinationScore(dice.filter((_, index) => mask & (1 << index)));
    // Every partition has exactly one group containing its first die.
    const first = mask & -mask;
    for (let group = mask; group; group = (group - 1) & mask) {
      if ((group & first) && groups[group]) best[mask] = Math.max(best[mask], groups[group] + best[mask ^ group]);
    }
  }
  const valid = dice.length > 0 && best[size - 1] > 0;
  return { valid, score: valid ? best[size - 1] : 0, hasScore: groups.some((score) => score > 0) };
}
