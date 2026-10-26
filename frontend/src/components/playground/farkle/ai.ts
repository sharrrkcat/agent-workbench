import { DICE_TYPES, difficultyFor, type DieType } from './dice';
import { isWild, scoreSubsets } from './scoring';
import type { GameDie } from './state';

export type AiPosition = { target: number; banked: number; round: number; dice: GameDie[] };
export type AiDecision = { dice: string[]; action: 'store' | 'pass'; score: number };
type Choice = { mask: number; score: number };
type RollScores = { bank: Choice; continuations: Choice[] };
type Outcome = { probability: number; bank: number; options: { remaining: number; score: number }[] };

// Scoring depends on natural faces and heads, not on the probabilities of their dice.
const scoresCache = new Map<string, RollScores>();
function rollScores(symbols: number[]): RollScores {
  const key = symbols.join('');
  const cached = scoresCache.get(key);
  if (cached) return cached;
  const scores = scoreSubsets(symbols.map((value) => ({
    type: value === 7 ? 'devil' : 'normal', value: (value === 7 ? 1 : value) as GameDie['value'],
  })));
  const full = scores.length - 1;
  const result: RollScores = { bank: { mask: 0, score: 0 }, continuations: [] };
  for (let mask = 1; mask <= full; mask++) {
    const score = scores[mask];
    if (score <= 0) continue;
    if (score > result.bank.score) result.bank = { mask, score };
    // Do not abandon another independently scoring batch when taking both gives hot dice.
    if (scores[full ^ mask] <= 0) result.continuations.push({ mask, score });
  }
  scoresCache.set(key, result);
  return result;
}

function physicalMask(mask: number, order: number[]) {
  return order.reduce((result, index, offset) => result | (mask & (1 << offset) ? 1 << index : 0), 0);
}

/** Exact turn values for one fixed loadout. No simulations or gameplay randomness. */
export class FarkleAI {
  private readonly full: number;
  private readonly canonical: number[];
  private readonly masks: number[];
  private readonly kernels = new Map<number, Outcome[]>();
  private goal = 0;
  private values: Float64Array[] = [];

  constructor(private readonly types: readonly DieType[]) {
    this.full = (1 << types.length) - 1;
    // Equal types are interchangeable before a roll; actual die identities remain in decisions.
    this.canonical = Array.from({ length: this.full + 1 }, (_, mask) => {
      const counts = new Map<DieType, number>();
      types.forEach((type, index) => { if (mask & (1 << index)) counts.set(type, (counts.get(type) ?? 0) + 1); });
      return types.reduce((result, type, index) => {
        if (!counts.get(type)) return result;
        counts.set(type, counts.get(type)! - 1);
        return result | (1 << index);
      }, 0);
    });
    this.masks = [...new Set(this.canonical.slice(1))];
    for (const mask of this.masks) this.kernels.set(mask, this.buildKernel(mask));
  }

  private buildKernel(mask: number): Outcome[] {
    const indices = this.types.map((_, index) => index).filter((index) => mask & (1 << index));
    const symbols = Array<number>(this.types.length);
    const outcomes = new Map<string, Outcome>();
    const distributions = this.types.map((type) => {
      const weights = DICE_TYPES.find((die) => die.id === type)!.weights;
      const sum = weights.reduce<number>((total, weight) => total + weight, 0);
      return weights.map((weight) => weight / sum);
    });
    const visit = (offset: number, probability: number) => {
      if (offset < indices.length) {
        const index = indices[offset];
        distributions[index].forEach((chance, face) => {
          if (!chance) return;
          symbols[index] = this.types[index] === 'devil' && face === 0 ? 7 : face + 1;
          visit(offset + 1, probability * chance);
        });
        return;
      }
      const order = [...indices].sort((a, b) => symbols[a] - symbols[b] || a - b);
      const scores = rollScores(order.map((index) => symbols[index]));
      if (!scores.bank.score) return; // Bust contributes zero to the turn value.
      const byRemaining = new Map<number, number>();
      for (const choice of scores.continuations) {
        const remaining = this.canonical[mask & ~physicalMask(choice.mask, order)] || this.full;
        byRemaining.set(remaining, Math.max(byRemaining.get(remaining) ?? 0, choice.score));
      }
      const options = [...byRemaining].sort(([a], [b]) => a - b).map(([remaining, score]) => ({ remaining, score }));
      const key = `${scores.bank.score}|${options.map(({ remaining, score }) => `${remaining}:${score}`).join(',')}`;
      const previous = outcomes.get(key);
      if (previous) previous.probability += probability;
      else outcomes.set(key, { probability, bank: scores.bank.score, options });
    };
    visit(0, 1);
    return [...outcomes.values()];
  }

  private prepareValues(goal: number) {
    if (this.goal === goal) return;
    this.goal = goal;
    const steps = Math.ceil(goal / 50);
    this.values = Array.from({ length: this.full + 1 }, () => new Float64Array(steps));
    // Every submission adds at least 50, including a submission that releases all six dice.
    for (let step = steps - 1; step >= 0; step--) for (const mask of this.masks) {
      const round = step * 50;
      let value = 0;
      for (const outcome of this.kernels.get(mask)!) {
        let best = Math.min(goal, round + outcome.bank);
        if (best < goal) for (const option of outcome.options) {
          best = Math.max(best, this.values[option.remaining][step + option.score / 50]);
        }
        value += outcome.probability * best;
      }
      this.values[mask][step] = value;
    }
  }

  decide(position: AiPosition): AiDecision & { bankValue: number; continueValue: number | null } {
    const available = position.dice.filter((die) => die.status !== 'scored')
      .sort((a, b) => (isWild(a) ? 7 : a.value) - (isWild(b) ? 7 : b.value) || a.index - b.index);
    const scores = rollScores(available.map((die) => isWild(die) ? 7 : die.value));
    const order = available.map((die) => die.index);
    const remainingMask = order.reduce((mask, index) => mask | (1 << index), 0);
    const goal = position.target - position.banked;
    const bankValue = Math.min(goal, position.round + scores.bank.score);
    const decision = (choice: Choice, action: AiDecision['action'], continueValue: number | null) => ({
      dice: available.filter((_, index) => choice.mask & (1 << index))
        .sort((a, b) => a.value - b.value || a.index - b.index).map((die) => die.id),
      action, score: choice.score, bankValue, continueValue,
    });
    if (bankValue >= goal) return decision(scores.bank, 'pass', null);
    this.prepareValues(goal);
    let best = scores.continuations[0];
    let continueValue = -Infinity;
    for (const choice of scores.continuations) {
      const remaining = this.canonical[remainingMask & ~physicalMask(choice.mask, order)] || this.full;
      const value = this.values[remaining][(position.round + choice.score) / 50];
      if (value > continueValue + 1e-9 || (Math.abs(value - continueValue) <= 1e-9 && choice.score > best.score)) {
        best = choice;
        continueValue = value;
      }
    }
    // All levels use optimal continuation values. Lower levels require a larger advantage to risk banking.
    const premium = 0.15 * (1 - difficultyFor(position.target));
    return continueValue > bankValue * (1 + premium) + 1e-9
      ? decision(best, 'store', continueValue) : decision(scores.bank, 'pass', continueValue);
  }
}
