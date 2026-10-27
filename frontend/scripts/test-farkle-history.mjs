import assert from 'node:assert/strict';
import { createModuleLoader } from './module-loader.mjs';

const load = createModuleLoader();
const { initialGame, gameReducer } = (await load('../src/components/playground/farkle/state.ts')).exports;
const { DICE_TYPES } = (await load('../src/components/playground/farkle/dice.ts')).exports;
const { encodeDie, decodeDie, encodeDice, decodeDice, isDiceCode, isEncodedDice } =
  (await load('../src/components/playground/farkle/diceEncoding.ts')).exports;
const { defaultCustomGame } = (await load('../src/components/playground/farkle/customGame.ts')).exports;
const { appendHistory, matchRecord, readHistory, saveHistory, HISTORY_KEY, historyPage, formatDuration } =
  (await load('../src/components/playground/farkle/history.ts')).exports;
const { farkleHistoryUrl, isFarkleHistory } = (await load('../src/components/playground/navigation.ts')).exports;

const startedAt = 1793100000123;
const fixedTypes = ['normal', 'even', 'odd', 'devil', 'weighted', 'lucky', 'unlucky', 'favourable', 'pie', 'misfortune',
  'monk', 'strip', 'unbalanced', 'shrinking', 'painted', 'heavenly', 'grimy', 'lu', 'ci', 'fer', 'aranka', 'merchant'];
assert.deepEqual([...fixedTypes].sort(), DICE_TYPES.map(({ id }) => id).sort());
assert.equal(encodeDice(fixedTypes), 'abcdefghijklmnopqrstuv', 'Persisted identities do not follow display sorting');
assert.deepEqual(decodeDice('abcdefghijklmnopqrstuv'), fixedTypes);
for (const [index, type] of fixedTypes.entries()) {
  const code = String.fromCharCode(97 + index);
  assert.equal(encodeDie(type), code); assert.equal(decodeDie(code), type); assert.equal(isDiceCode(code), true);
}
for (const invalid of [null, '', 'aa', 'a\n', 'b\r\n', 'w', 'normal', 'A', 0]) assert.equal(isDiceCode(invalid), false);
for (const invalid of [null, '', 'aaaaa', 'aaaaaaa', 'aaaaaa\n', 'aaaaaa\r', 'aaaaaw', 'aaaaaA', {}]) assert.equal(isEncodedDice(invalid), false);
const ones = Array(6).fill(1), bust = [2, 2, 3, 3, 4, 6];
const start = (previous = initialGame) => gameReducer(previous, { type: 'start', startedAt, opponentDiceMode: 'wild',
  setup: { kind: 'standard', level: 'electors' }, loadout: { A: Array(6).fill('normal'), B: Array(6).fill('normal') }, values: ones });
const complete = (state, values = ones) => gameReducer(state, { type: 'complete', id: state.command.id, values, hoverSample: null });
const act = (state, input) => gameReducer(state, { ...input, actor: state.player === 'B' ? 'human' : 'ai', revision: state.revision });
const all = (state) => Array.from({ length: 6 }, (_, i) => `${state.player}${i}`).reduce((next, id) => act(next, { type: 'select', id }), state);

let game = start();
assert.deepEqual(game.rolls, { A: 0, B: 0 });
game = complete(game);
assert.deepEqual(game.rolls, { A: 0, B: 1 }, 'Only starting an actual throw increments rolls');
game = complete(game);
game = act(all(game), { type: 'store' });
const storing = game.command.id;
game = complete(game);
assert.deepEqual(game.rolls, { A: 0, B: 2 }, 'Hot dice count as another throw in the same turn');
assert.deepEqual(game.turns, { A: 0, B: 0 });
assert.equal(gameReducer(game, { type: 'complete', id: storing, values: ones, hoverSample: null }), game);
game = complete(game);
game = complete(act(all(game), { type: 'pass' }));
assert.equal(game.winner, 'B');
assert.deepEqual(game.turns, { A: 0, B: 1 }, 'The winning turn is included');
assert.deepEqual(game.rolls, { A: 0, B: 2 });
assert.equal(act(game, { type: 'pass' }), game);
const record = matchRecord(game, startedAt + 630999);
assert.equal(record.durationSeconds, 630);
assert.equal(record.startedAt, startedAt);
assert.equal(record.playerScore, 16000);
assert.equal(record.targetScore, 10000);
assert.equal(record.level, 'electors');
assert.equal(record.opponentMode, 'wild');
assert.deepEqual(record.playerDice, Array(6).fill('normal'));

let turns = complete(complete(start()));
turns = act(turns, { type: 'pass' });
assert.deepEqual(turns.turns, { A: 0, B: 1 }, 'Zero-score passes count');
turns = complete(turns, bust);
assert.deepEqual(turns.rolls, { A: 1, B: 1 });
turns = complete(turns);
assert.equal(turns.command.kind, 'bust');
assert.deepEqual(turns.turns, { A: 1, B: 1 }, 'A bust ends exactly one turn');
turns = complete(complete(turns));
assert.deepEqual(turns.turns, { A: 1, B: 1 }, 'Notice and handoff callbacks do not count twice');
turns = complete(complete(turns));
assert.deepEqual(turns.rolls, { A: 1, B: 2 });
assert.deepEqual(start(turns).rolls, { A: 0, B: 0 });
assert.equal(gameReducer(turns, { type: 'exit' }).startedAt, null);

const customState = { ...game, setup: { kind: 'custom', config: defaultCustomGame() }, opponentDiceMode: 'custom', winner: 'A',
  totals: { A: 10050, B: 5000 }, turns: { A: 7, B: 8 }, rolls: { A: 13, B: 17 } };
const customRecord = matchRecord(customState, startedAt + 3601000);
assert.equal(customRecord.level, null);
assert.equal(customRecord.winner, 'A');
assert.equal(customRecord.opponentTurns, 7);
assert.equal(customRecord.playerRolls, 17);

let raw = null;
const storage = { getItem(key) { assert.equal(key, HISTORY_KEY); return raw; }, setItem(key, value) { assert.equal(key, HISTORY_KEY); raw = value; } };
assert.deepEqual(readHistory(storage), []);
const existingHistory = '[1,[[1793100000123,630,"aabcdv","fghijk",5350,3800,5000,0,11,10,25,24,0,3,1,1]]]';
raw = existingHistory;
assert.deepEqual(readHistory(storage)[0].playerDice, ['normal', 'normal', 'even', 'odd', 'devil', 'merchant']);
saveHistory(storage, readHistory(storage));
assert.equal(raw, existingHistory, 'The shared codec preserves existing history byte for byte');
for (const { id } of DICE_TYPES) {
  const item = { ...customRecord, playerDice: Array(6).fill(id), opponentDice: [id, 'normal', id, 'devil', 'merchant', id] };
  saveHistory(storage, [item]);
  assert.deepEqual(readHistory(storage), [item], `${id} preserves identities and repetitions`);
}
saveHistory(storage, [{ ...record, playerScore: Number.MAX_SAFE_INTEGER, targetScore: Number.MAX_SAFE_INTEGER - 1 }]);
assert.equal(readHistory(storage)[0].playerScore, Number.MAX_SAFE_INTEGER);
assert.equal(readHistory(storage)[0].targetScore, Number.MAX_SAFE_INTEGER - 1);
const overshoot = { ...record, playerScore: 9007199254741050, targetScore: Number.MAX_SAFE_INTEGER - 1 };
saveHistory(storage, [overshoot]);
assert.deepEqual(readHistory(storage), [overshoot], 'Winning totals beyond the target limit round-trip without additional rounding');
let records = [];
for (let i = 0; i < 105; i++) records = appendHistory(records, { ...record, startedAt: startedAt + i });
assert.equal(records.length, 100);
assert.equal(records[0].startedAt, startedAt + 104);
assert.equal(records.at(-1).startedAt, startedAt + 5);
saveHistory(storage, records);
assert.deepEqual(readHistory(storage), records);
assert.ok(raw.length < JSON.stringify(records).length / 4, 'Compact records omit names, object keys and images');
const valid = raw;
for (const invalid of ['{broken', 'null', '[2,[]]', '[1,{}]', '[1,[[]]]']) {
  raw = invalid;
  assert.throws(() => readHistory(storage));
  assert.equal(raw, invalid, 'Read failures do not overwrite storage');
}
for (const [index, value] of [[0, -1], [2, 'zzzzzz'], [3, 'aaaaa'], [4, 1.5], [5, -50], [6, Number.MAX_SAFE_INTEGER], [7, 2], [12, 99], [13, 3], [14, 0]]) {
  const parsed = JSON.parse(valid); parsed[1][0][index] = value; raw = JSON.stringify(parsed);
  assert.throws(() => readHistory(storage));
}
assert.throws(() => readHistory({ getItem() { throw new Error('denied'); } }), /denied/);
assert.throws(() => saveHistory({ setItem() { throw new Error('quota'); } }, records), /quota/);
for (const [query, count, expected] of [['', 0, 1], ['?page=5', 100, 5], ['?page=2', 21, 2], ['?page=9', 20, 1],
  ['?page=-1', 100, 1], ['?page=2.5', 100, 1], ['?page=x', 100, 1]]) assert.equal(historyPage(query, count), expected);
assert.equal(farkleHistoryUrl(2), '/playground/farkle?view=history&page=2');
assert.equal(isFarkleHistory('?view=history&page=2'), true);
assert.equal(isFarkleHistory('?view=unknown'), false);
assert.equal(formatDuration(0), '00:00');
assert.equal(formatDuration(630), '10:30');
assert.equal(formatDuration(3601), '1:00:01');
console.log('Farkle history: counters, settlement snapshots, compact storage, boundaries and pagination passed.');
