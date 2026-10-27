import type { DieType } from './dice';
import type { CustomGame } from './customGame';
import type { LevelId } from './economy';
import type { GameState, PlayerId } from './state';
import { encodeDice, decodeDice, isEncodedDice } from './diceEncoding';

export const HISTORY_KEY = 'cogita.farkle.history';
export const HISTORY_LIMIT = 100;
export const HISTORY_PAGE_SIZE = 20;
export const RULES_VERSION = 1;
export const AI_POLICY_VERSION = 1;

export type MatchRecord = {
  startedAt: number; durationSeconds: number;
  playerDice: DieType[]; opponentDice: DieType[];
  playerScore: number; opponentScore: number; targetScore: number; winner: PlayerId;
  playerTurns: number; opponentTurns: number; playerRolls: number; opponentRolls: number;
  level: LevelId | null; opponentMode: CustomGame['opponentDiceMode'];
  rulesVersion: number; aiVersion: number;
};

// Format 1 dictionaries are fixed identities, independent of catalog/display order.
const levelCodes: readonly (LevelId | null)[] = [null, 'beggars', 'wagoners', 'masters', 'courtiers',
  'burgomasters', 'stewards', 'governors', 'chancellors', 'burgraves', 'electors'];
const modeCodes: readonly MatchRecord['opponentMode'][] = ['dynamic', 'random', 'wild', 'custom'];

export function matchRecord(state: GameState, finishedAt: number): MatchRecord {
  return {
    startedAt: state.startedAt!, durationSeconds: Math.max(0, Math.floor((finishedAt - state.startedAt!) / 1000)),
    playerDice: state.dice.filter((die) => die.player === 'B').map((die) => die.type),
    opponentDice: state.dice.filter((die) => die.player === 'A').map((die) => die.type),
    playerScore: state.totals.B, opponentScore: state.totals.A, targetScore: state.target, winner: state.winner!,
    playerTurns: state.turns.B, opponentTurns: state.turns.A, playerRolls: state.rolls.B, opponentRolls: state.rolls.A,
    level: state.setup!.kind === 'standard' ? state.setup!.level : null, opponentMode: state.opponentDiceMode!,
    rulesVersion: RULES_VERSION, aiVersion: AI_POLICY_VERSION,
  };
}

export function appendHistory(records: MatchRecord[], record: MatchRecord) {
  return [record, ...records].slice(0, HISTORY_LIMIT);
}

export function saveHistory(storage: Pick<Storage, 'setItem'>, records: MatchRecord[]) {
  storage.setItem(HISTORY_KEY, JSON.stringify([1, records.map((r) => [r.startedAt, r.durationSeconds,
    encodeDice(r.playerDice), encodeDice(r.opponentDice), r.playerScore, r.opponentScore, r.targetScore,
    r.winner === 'B' ? 0 : 1, r.playerTurns, r.opponentTurns, r.playerRolls, r.opponentRolls,
    levelCodes.indexOf(r.level), modeCodes.indexOf(r.opponentMode), r.rulesVersion, r.aiVersion])]));
}

export function readHistory(storage: Pick<Storage, 'getItem'>): MatchRecord[] {
  const raw = storage.getItem(HISTORY_KEY);
  if (raw === null) return [];
  const value: unknown = JSON.parse(raw);
  if (!Array.isArray(value) || value.length !== 2 || value[0] !== 1 || !Array.isArray(value[1])
    || value[1].length > HISTORY_LIMIT) throw new Error('Invalid Farkle history');
  return value[1].map((row: unknown) => {
    if (!Array.isArray(row) || row.length !== 16
      || !row.every((item, index) => index === 2 || index === 3
        ? isEncodedDice(item)
        // Winning totals may overshoot the safe-integer target limit.
        : typeof item === 'number' && item >= 0 && (index === 4 || index === 5 ? Number.isInteger(item) : Number.isSafeInteger(item)))
      || row[0] > 8_640_000_000_000_000 || row[6] <= 1 || row[6] >= Number.MAX_SAFE_INTEGER
      || row[7] > 1 || row[12] >= levelCodes.length || row[13] >= modeCodes.length
      || (row[12] !== 0 && row[13] === 3) || row[14] < 1 || row[15] < 1) {
      throw new Error('Invalid Farkle history record');
    }
    return { startedAt: row[0], durationSeconds: row[1], playerDice: decodeDice(row[2]), opponentDice: decodeDice(row[3]),
      playerScore: row[4], opponentScore: row[5], targetScore: row[6], winner: row[7] === 0 ? 'B' : 'A',
      playerTurns: row[8], opponentTurns: row[9], playerRolls: row[10], opponentRolls: row[11],
      level: levelCodes[row[12]], opponentMode: modeCodes[row[13]], rulesVersion: row[14], aiVersion: row[15] };
  });
}

export function historyPage(search: string, count: number) {
  const requested = Number(new URLSearchParams(search).get('page') ?? 1);
  return Math.min(Math.max(1, Math.ceil(count / HISTORY_PAGE_SIZE)), Number.isSafeInteger(requested) && requested > 0 ? requested : 1);
}

export function formatDuration(seconds: number) {
  const pad = (value: number) => String(value).padStart(2, '0');
  return seconds >= 3600 ? `${Math.floor(seconds / 3600)}:${pad(Math.floor(seconds / 60) % 60)}:${pad(seconds % 60)}`
    : `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}`;
}
