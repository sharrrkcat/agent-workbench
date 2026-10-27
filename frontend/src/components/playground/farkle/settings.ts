import { OPPONENT_DICE_MODES, type OpponentDiceMode } from './opponentDice';

export const FARKLE_SETTINGS_KEY = 'cogita.farkle.settings';
export const DEFAULT_OPPONENT_MODE: OpponentDiceMode = 'dynamic';

export function readFarkleSettings(storage: Pick<Storage, 'getItem'>): OpponentDiceMode {
  const raw = storage.getItem(FARKLE_SETTINGS_KEY);
  if (raw === null) return DEFAULT_OPPONENT_MODE;
  let value;
  try { value = JSON.parse(raw); }
  catch (error) { if (error instanceof SyntaxError) return DEFAULT_OPPONENT_MODE; throw error; }
  return OPPONENT_DICE_MODES.includes(value?.opponentDiceMode) ? value.opponentDiceMode : DEFAULT_OPPONENT_MODE;
}

export function saveFarkleSettings(storage: Pick<Storage, 'setItem'>, opponentDiceMode: OpponentDiceMode) {
  storage.setItem(FARKLE_SETTINGS_KEY, JSON.stringify({ opponentDiceMode }));
}
