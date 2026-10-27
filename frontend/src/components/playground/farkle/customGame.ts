import type { DiceCounts } from './dice';
import { defaultLoadout, encodeLoadout, decodeLoadout } from './loadout';
import { isEncodedDice } from './diceEncoding';
import { OPPONENT_DICE_MODES } from './opponentDice';
import { LEVELS, type LevelId } from './economy';

export const CUSTOM_GAME_KEY = 'cogita.farkle.customGame';
export const CUSTOM_OPPONENT_MODES = [...OPPONENT_DICE_MODES, 'custom'] as const;
export type CustomGame = {
  target: number;
  opponentDiceMode: typeof CUSTOM_OPPONENT_MODES[number];
  opponentLoadout: DiceCounts;
  playerLoadout: DiceCounts;
};
export type MatchSetup = { kind: 'standard'; level: LevelId } | { kind: 'custom'; config: CustomGame };
export const matchTarget = (setup: MatchSetup) => setup.kind === 'custom'
  ? setup.config.target : LEVELS.find(({ id }) => id === setup.level)!.target;
export const defaultCustomGame = (): CustomGame => ({ target: 1500, opponentDiceMode: 'dynamic',
  opponentLoadout: defaultLoadout(), playerLoadout: defaultLoadout() });
const validTarget = (value: unknown): value is number => typeof value === 'number'
  && Number.isInteger(value) && value > 1 && value < Number.MAX_SAFE_INTEGER;

export function targetError(text: string): 'integer' | 'minimum' | 'maximum' | null {
  if (!/^-?\d+$/.test(text)) return 'integer';
  const target = Number(text);
  if (target <= 1) return 'minimum';
  return target >= Number.MAX_SAFE_INTEGER ? 'maximum' : null;
}

export function readCustomGame(storage: Pick<Storage, 'getItem'>): CustomGame {
  const raw = storage.getItem(CUSTOM_GAME_KEY);
  if (raw === null) return defaultCustomGame();
  let value;
  try { value = JSON.parse(raw); }
  catch (error) { if (error instanceof SyntaxError) return defaultCustomGame(); throw error; }
  if (!validTarget(value?.target) || !CUSTOM_OPPONENT_MODES.includes(value?.opponentDiceMode)
    || !isEncodedDice(value?.opponentLoadout)
    || !isEncodedDice(value?.playerLoadout)) return defaultCustomGame();
  return { target: value.target, opponentDiceMode: value.opponentDiceMode,
    playerLoadout: decodeLoadout(value.playerLoadout), opponentLoadout: decodeLoadout(value.opponentLoadout) };
}

export function saveCustomGame(storage: Pick<Storage, 'setItem'>, config: CustomGame) {
  storage.setItem(CUSTOM_GAME_KEY, JSON.stringify({ ...config,
    playerLoadout: encodeLoadout(config.playerLoadout), opponentLoadout: encodeLoadout(config.opponentLoadout) }));
}
