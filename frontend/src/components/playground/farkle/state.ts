import { evaluateDice } from './scoring';
import type { DieType, FaceValue } from './dice';
import type { TargetScore } from './economy';

export type PlayerId = 'A' | 'B';
export type GameDie = {
  id: string; player: PlayerId; index: number; type: DieType;
  value: FaceValue; status: 'idle' | 'selected' | 'scored';
};
export type GameCommand =
  | { kind: 'reset'; id: number; values: FaceValue[] | null }
  | { kind: 'roll'; id: number; dice: { id: string; value: FaceValue }[] }
  | { kind: 'store'; id: number; dice: string[]; score: number; next: 'roll' | 'pass' }
  | { kind: 'view'; id: number; from: PlayerId; to: PlayerId }
  | { kind: 'turnEnd'; id: number }
  | { kind: 'bust'; id: number };
export type GameState = {
  revision: number; matchId: number; turnId: number; playing: boolean; player: PlayerId; busy: boolean;
  target: TargetScore; hoverId: string | null; batches: Record<PlayerId, string[][]>;
  totals: Record<PlayerId, number>; rounds: Record<PlayerId, number>; winner: PlayerId | null;
  dice: GameDie[]; command: GameCommand | null;
};
export type TurnInput =
  | { type: 'store' | 'pass' }
  | { type: 'hover'; id: string | null }
  | { type: 'select'; id: string };
export type GameAction =
  | { type: 'start'; target: TargetScore; loadout: Record<PlayerId, DieType[]>; values: FaceValue[] }
  | { type: 'exit' }
  | (TurnInput & ({ actor: 'human' } | { actor: 'ai'; revision: number }))
  | { type: 'complete'; id: number; hoverSample: number | null; values: FaceValue[] };

export const initialGame: GameState = {
  revision: 0, matchId: 0, turnId: 0, playing: false, player: 'B', busy: false, target: 1500,
  hoverId: null, batches: { A: [], B: [] }, dice: [], command: null,
  totals: { A: 0, B: 0 }, rounds: { A: 0, B: 0 }, winner: null,
};

export function canPlay(state: GameState) {
  return state.playing && !state.busy && !state.winner;
}

export function canHumanPlay(state: GameState) {
  return canPlay(state) && state.player === 'B';
}

export function selection(state: GameState, player = state.player) {
  const dice = state.dice.filter((die) => die.player === player && die.status === 'selected');
  return { dice, ...evaluateDice(dice) };
}

function beginRoll(state: GameState, values: FaceValue[]): GameState {
  const dice = state.dice.map((die) => die.player === state.player && die.status !== 'scored'
    ? { ...die, value: values[die.index] } : die);
  const id = state.revision + 1;
  return { ...state, revision: id, busy: true, hoverId: null, dice,
    command: { kind: 'roll', id, dice: dice.filter((die) => die.player === state.player && die.status !== 'scored')
      .map(({ id, value }) => ({ id, value })) } };
}

function releaseDice(state: GameState): GameState {
  return { ...state, batches: { ...state.batches, [state.player]: [] },
    dice: state.dice.map((die) => die.player === state.player ? { ...die, status: 'idle' } : die) };
}

function handOff(state: GameState): GameState {
  const player = state.player === 'B' ? 'A' : 'B';
  const id = state.revision + 1;
  return { ...state, revision: id, turnId: id, player, busy: true, hoverId: null,
    command: { kind: 'view', id, from: state.player, to: player } };
}

function bankRound(state: GameState): GameState {
  const total = state.totals[state.player] + state.rounds[state.player];
  const next = { ...state, totals: { ...state.totals, [state.player]: total },
    rounds: { ...state.rounds, [state.player]: 0 }, hoverId: null, command: null, busy: false };
  return total >= state.target ? { ...next, winner: state.player } : endTurn(next);
}

function endTurn(state: GameState): GameState {
  if (state.player === 'B') return handOff(state);
  const id = state.revision + 1;
  return { ...state, revision: id, busy: true, hoverId: null, command: { kind: 'turnEnd', id } };
}

export function gameReducer(state: GameState, action: GameAction): GameState {
  const id = state.revision + 1;
  if (action.type === 'start' || action.type === 'exit') {
    const playing = action.type === 'start';
    const dice: GameDie[] = playing ? (['A', 'B'] as const).flatMap((player) => action.loadout[player].map((type, index) => ({
      id: `${player}${index}`, player, index, type, value: 1, status: 'idle',
    }))) : [];
    return { ...initialGame, revision: id, matchId: playing ? id : 0, turnId: playing ? id : 0, playing, busy: true, dice,
      target: playing ? action.target : initialGame.target, batches: { A: [], B: [] },
      totals: { A: 0, B: 0 }, rounds: { A: 0, B: 0 },
      command: { kind: 'reset', id, values: playing ? action.values : null } };
  }
  if (action.type === 'complete') {
    const command = state.command;
    if (!command || command.id !== action.id) return state;
    if (command.kind === 'reset' && command.values) return beginRoll(state, command.values);
    if (command.kind === 'bust') return endTurn(state);
    if (command.kind === 'turnEnd') return handOff(state);
    if (command.kind === 'view') return beginRoll(releaseDice(state), action.values);
    if (command.kind === 'store') {
      const dice = state.dice.map((die): GameDie => command.dice.includes(die.id) ? { ...die, status: 'scored' } : die);
      let next: GameState = { ...state, dice,
        rounds: { ...state.rounds, [state.player]: state.rounds[state.player] + command.score },
        batches: { ...state.batches, [state.player]: [...state.batches[state.player], command.dice] } };
      if (command.next === 'pass') return bankRound(next);
      if (dice.filter((die) => die.player === state.player).every((die) => die.status === 'scored')) next = releaseDice(next);
      return beginRoll(next, action.values);
    }
    const candidates = state.dice.filter((die) => die.player === state.player && die.status !== 'scored');
    if (command.kind === 'roll' && !evaluateDice(candidates).hasScore) {
      return { ...state, revision: id, hoverId: null, rounds: { ...state.rounds, [state.player]: 0 },
        command: { kind: 'bust', id } };
    }
    const hoverId = state.player === 'B' && action.hoverSample !== null && candidates.length
      ? candidates[Math.floor(action.hoverSample * candidates.length)].id : null;
    return { ...state, busy: false, command: null, hoverId };
  }
  if (!canPlay(state)) return state;
  if (action.actor === 'human' ? state.player !== 'B' : state.player !== 'A' || action.revision !== state.revision) return state;
  if (action.type === 'hover' && action.id === null) return state.hoverId === null ? state : { ...state, hoverId: null };
  if (action.type === 'select' || action.type === 'hover') {
    const target = state.dice.find((die) => die.id === action.id && die.player === state.player && die.status !== 'scored');
    if (!target) return state;
    if (action.type === 'hover') return state.hoverId === target.id ? state : { ...state, hoverId: target.id };
    return { ...state, dice: state.dice.map((die) => die.id === target.id
      ? { ...die, status: die.status === 'selected' ? 'idle' : 'selected' } : die) };
  }
  const selected = selection(state);
  if (action.type === 'pass' && !selected.dice.length) return bankRound(state);
  if (!selected.valid) return state;
  const dice = selected.dice.sort((a, b) => a.value - b.value || a.index - b.index).map((die) => die.id);
  return { ...state, revision: id, busy: true, hoverId: null,
    command: { kind: 'store', id, dice, score: selected.score, next: action.type === 'pass' ? 'pass' : 'roll' } };
}
