import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createModuleLoader } from './module-loader.mjs';

const load = createModuleLoader();
const { defaultLoadout, loadoutSize, canAdjustLoadout, adjustLoadout } =
  (await load('../src/components/playground/farkle/loadout.ts')).exports;
const { CUSTOM_GAME_KEY, CUSTOM_OPPONENT_MODES, OPPONENT_POOL, defaultCustomGame, targetError, readCustomGame, saveCustomGame } =
  (await load('../src/components/playground/farkle/customGame.ts')).exports;
const { gameReducer, initialGame } = (await load('../src/components/playground/farkle/state.ts')).exports;
const english = JSON.parse(readFileSync(new URL('../src/i18n/resources/en/common.json', import.meta.url))).farkle.dice;
const order = Object.keys(OPPONENT_POOL).sort((a, b) => english[a].localeCompare(english[b], 'en'));
const pool = { ...OPPONENT_POOL, even: 1, merchant: 1000 };
let counts = defaultLoadout();
function adjust(type, change) {
  assert.equal(canAdjustLoadout(counts, pool, type, change), true);
  counts = adjustLoadout(counts, type, change, order);
  assert.equal(loadoutSize(counts), 6);
  assert.ok(Object.values(counts).every((count) => Number.isInteger(count) && count >= 0));
  assert.equal(canAdjustLoadout(counts, pool, 'normal', -1), false);
}
assert.equal(canAdjustLoadout(counts, pool, 'normal', 1), false);
for (const type of ['weighted', 'merchant', 'even', 'misfortune', 'aranka', 'odd']) adjust(type, 1);
assert.equal(counts.normal, 0);
for (const type of order.filter((type) => type !== 'normal')) assert.equal(canAdjustLoadout(counts, pool, type, 1), false);
for (const removed of ['aranka', 'misfortune', 'even', 'merchant', 'odd', 'weighted']) {
  adjust('normal', 1);
  assert.equal(counts[removed], 0, `Normal replaces ${english[removed]} in full English order`);
}
adjust('even', 1);
assert.equal(canAdjustLoadout(counts, pool, 'even', 1), false);
adjust('even', -1);
assert.equal(canAdjustLoadout(counts, pool, 'even', -1), false);
for (const type of order.filter((type) => type !== 'normal')) {
  const copies = Math.min(6, pool[type]);
  for (let i = 0; i < copies; i++) adjust(type, 1);
  for (let i = 0; i < copies; i++) adjust(type, -1);
}

for (const target of [2, 1501, 10000, 10001, 10 ** 12, Number.MAX_SAFE_INTEGER - 1]) assert.equal(targetError(String(target)), null);
for (const input of ['', ' ', '1.5', '1.0', '1e3', '0x10', '+1', ' 1', '1 ', 'Infinity', 'NaN']) {
  assert.equal(targetError(input), 'integer', input);
}
for (const input of ['0', '-1', '1', '0001', '-999999999999999999999']) assert.equal(targetError(input), 'minimum');
for (const input of ['9007199254740991', '9007199254740992', '999999999999999999999']) assert.equal(targetError(input), 'maximum');
assert.equal(targetError('0002'), null);
const saved = new Map();
const storage = { getItem: (key) => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value) };
assert.deepEqual(readCustomGame(storage), defaultCustomGame());
assert.equal(saved.size, 0);
for (const mode of CUSTOM_OPPONENT_MODES) {
  const config = { target: 1501, opponentDiceMode: mode, opponentLoadout: { ...defaultLoadout(), normal: 0, weighted: 6 } };
  saveCustomGame(storage, config);
  assert.deepEqual(readCustomGame(storage), config);
  assert.deepEqual(Object.keys(JSON.parse(saved.get(CUSTOM_GAME_KEY))).sort(), ['opponentDiceMode', 'opponentLoadout', 'target']);
}
for (const value of [null, [], {}, ...[0, 1, 1.5, Number.MAX_SAFE_INTEGER].map((target) => ({ ...defaultCustomGame(), target })), { ...defaultCustomGame(), opponentDiceMode: 'invalid' },
  { ...defaultCustomGame(), opponentLoadout: { ...defaultLoadout(), weighted: 6 } }]) {
  saved.set(CUSTOM_GAME_KEY, JSON.stringify(value));
  assert.deepEqual(readCustomGame(storage), defaultCustomGame());
}
saved.set(CUSTOM_GAME_KEY, '{broken');
assert.deepEqual(readCustomGame(storage), defaultCustomGame());
assert.equal(saved.get(CUSTOM_GAME_KEY), '{broken');
assert.throws(() => readCustomGame({ getItem() { throw Error('blocked'); } }), /blocked/);
assert.throws(() => saveCustomGame({ setItem() { throw Error('quota'); } }, defaultCustomGame()), /quota/);

for (const target of [2, 1500, 1501, 10000, 10001, 10 ** 12, Number.MAX_SAFE_INTEGER - 1]) {
  const setup = { kind: 'custom', config: { ...defaultCustomGame(), target } };
  let game = gameReducer(initialGame, { type: 'start', setup,
    loadout: { A: Array(6).fill('normal'), B: Array(6).fill('normal') }, values: [1, 1, 1, 1, 1, 1] });
  assert.equal(game.target, target);
  assert.deepEqual(game.setup, setup);
  const finish = () => { game = gameReducer(game, { type: 'complete', id: game.command.id, values: [1, 1, 1, 1, 1, 1], hoverSample: 0 }); };
  finish(); finish();
  const before = Math.floor((target - 1) / 50) * 50;
  game = { ...game, totals: { A: 0, B: before } };
  game = gameReducer(game, { type: 'pass', actor: 'human' });
  assert.equal(game.winner, null, 'The real target is not capped at 10000');
  while (game.command) finish();
  game = { ...game, player: 'B', rounds: { A: 0, B: 100 } };
  game = gameReducer(game, { type: 'pass', actor: 'human' });
  assert.equal(game.winner, 'B');
}
console.log('Farkle six-die balancing, English replacement order, custom storage and safe integer targets passed.');
